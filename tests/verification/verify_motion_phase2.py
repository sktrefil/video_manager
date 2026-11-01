"""Independent phase-2 ground truth and frozen gates; adapter wired at handoff."""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import time

import cv2
import numpy as np

GATES = dict(clean_applied_min=6,clean_case_count=9,mae_vs_nearest_max=.75,
             absolute_mae_max=12.,sharpness_ratio_min=.80,sharpness_ratio_max=1.25,
             unsafe_fallback_rate_min=1.,shake_rms_ratio_max=.5,crop_each_edge_max=.08,
             pan_velocity_relative_error_max=.10,pan_residual_px_per_frame_max=.5,
             zoom_absolute_scale_error_max=.01,duration_error_frames_max=1)


def texture(seed,width=240,height=160,pad=32):
    rng=np.random.default_rng(seed)
    image=rng.integers(25,225,(height+2*pad,width+2*pad,3),dtype=np.uint8)
    image=cv2.GaussianBlur(image,(3,3),.7)
    for x in range(12,image.shape[1],29):cv2.line(image,(x,0),(x,image.shape[0]-1),(235,220,205),1)
    for y in range(19,image.shape[0],31):cv2.line(image,(0,y),(image.shape[1]-1,y),(20,35,50),1)
    return image


def view(canvas,dx=0.,dy=0.,scale=1.,width=240,height=160,pad=32):
    matrix=np.array([[scale,0,-pad+dx+(1-scale)*width/2],
                     [0,scale,-pad+dy+(1-scale)*height/2]],np.float32)
    return cv2.warpAffine(canvas,matrix,(width,height),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT_101)


def fixtures(seed):
    canvas=texture(seed);clean=[]
    for dx,dy in [(4.,0.),(0.,4.),(4.,4.)]:
        for alpha in (.25,.5,.75):
            clean.append(dict(name=f'translate_{dx}_{dy}_{alpha}',left=view(canvas),right=view(canvas,dx,dy),
                              expected=view(canvas,dx*alpha,dy*alpha),alpha=alpha,confidence=1.,cut=False))
    left=view(canvas);right=view(canvas,4.,0.)
    occluded=right.copy();cv2.rectangle(occluded,(70,35),(160,125),(5,5,5),-1)
    unsafe=[dict(name='scene_cut',left=left,right=view(texture(seed+97)),alpha=.5,confidence=1.,cut=True),
            dict(name='occlusion',left=left,right=occluded,alpha=.5,confidence=1.,cut=False),
            dict(name='low_confidence',left=left,right=right,alpha=.5,confidence=.1,cut=False)]
    n=61;t=np.arange(n,dtype=float)/20
    envelope=np.sin(np.pi*np.arange(n)/(n-1))**2
    shake=np.column_stack((4*np.sin(np.arange(n)*1.7)*envelope,3*np.cos(np.arange(n)*1.3)*envelope))
    camera={
        'shake':dict(frames=np.array([view(canvas,*p) for p in shake]),trajectory=shake,times=t),
        'pan':dict(frames=np.array([view(canvas,i*.25,0) for i in range(n)]),trajectory=np.column_stack((np.arange(n)*.25,np.zeros(n))),times=t),
        'zoom':dict(frames=np.array([view(canvas,scale=1+i*.0005) for i in range(n)]),scales=1+np.arange(n)*.0005,times=t)}
    return clean,unsafe,camera


def mae(a,b):return float(np.mean(np.abs(a[12:-12,12:-12].astype(float)-b[12:-12,12:-12])))


def sharpness(a):
    gray=cv2.cvtColor(a[12:-12,12:-12],cv2.COLOR_RGB2GRAY)
    return float(cv2.Laplacian(gray,cv2.CV_64F).var())


def registered_path(frames,return_matrices=False):
    """Independent pixel registration, not the product's reported transforms."""
    reference=cv2.cvtColor(frames[0],cv2.COLOR_RGB2GRAY).astype(np.float32)/255.
    center=np.array([frames.shape[2]/2,frames.shape[1]/2],dtype=float)
    rows=[];matrices=[]
    for frame in frames:
        gray=cv2.cvtColor(frame,cv2.COLOR_RGB2GRAY).astype(np.float32)/255.
        shift,_=cv2.phaseCorrelate(reference,gray)
        initial=np.eye(2,3,dtype=np.float32);initial[:,2]=shift
        _,matrix=cv2.findTransformECC(reference,gray,initial,cv2.MOTION_AFFINE,
                                    (cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,150,1e-6),None,3)
        rows.append([*(matrix[:,:2]@center+matrix[:,2]-center),float(np.sqrt(abs(np.linalg.det(matrix[:,:2]))))])
        matrices.append(matrix.copy())
    return (np.array(rows),np.array(matrices)) if return_matrices else np.array(rows)


def evaluate_stabilization(adapter,camera,output):
    rows=[]
    for name,f in camera.items():
        result=adapter.stabilize(f['frames'],f['times'],max_crop_fraction=.05,
                                 smoothing_seconds=.4,strength=.7,protect_seconds=0.)
        actual=np.asarray(result['frames']);path=registered_path(actual)
        crop_measured=[];covered=True
        corners=np.array([[0,0,1],[actual.shape[2]-1,0,1],[0,actual.shape[1]-1,1],[actual.shape[2]-1,actual.shape[1]-1,1]]).T
        for matrix in result['transforms']:
            full=np.vstack((matrix,[0,0,1]));points=np.linalg.inv(full)@corners
            covered=covered and bool(np.all(points[0]>=-1e-6) and np.all(points[0]<=actual.shape[2]-1+1e-6) and np.all(points[1]>=-1e-6) and np.all(points[1]<=actual.shape[1]-1+1e-6))
            crop_measured.append(max(0.,1-1/np.sqrt(abs(np.linalg.det(full[:2,:2])))))
        row=dict(name=name,applied=bool(result['applied']),reason=result.get('reason',''),
                 endpoint_exact=bool(np.array_equal(actual[0],f['frames'][0]) and np.array_equal(actual[-1],f['frames'][-1])),
                 min_sharpness_ratio=min(sharpness(a)/sharpness(b) for a,b in zip(actual,f['frames'])),
                 no_black_border=bool(np.all(np.any(actual!=0,axis=-1))),
                 crop_fraction=max(crop_measured),coverage=covered)
        if name=='shake':
            section=slice(6,-6)
            row['rms_ratio']=float(np.sqrt(np.mean(path[section,:2]**2))/np.sqrt(np.mean(f['trajectory'][section]**2)))
            row['effect_pass']=row['applied'] and row['rms_ratio']<=.5
        elif name=='pan':
            velocity=np.polyfit(np.arange(len(path)),path[:,0],1)[0]
            row['velocity_relative_error']=float(abs(velocity-.25)/.25)
            row['residual_velocity_error']=float(np.max(abs(np.diff(path[:,0])-.25)))
            row['effect_pass']=row['velocity_relative_error']<=.1 and row['residual_velocity_error']<=.5
        else:
            row['scale_max_error']=float(np.max(abs(path[:,2]-f['scales'])))
            row['effect_pass']=row['scale_max_error']<=.01
        row['passed']=bool(row['effect_pass'] and row['endpoint_exact'] and row['min_sharpness_ratio']>=.8
                           and row['crop_fraction']<=.05+1e-9 and row['no_black_border'] and row['coverage'])
        np.savez_compressed(output/(name+'_output.npz'),frames=actual,path=path)
        rows.append(row)
    return dict(rows=rows,passed=all(r['passed'] for r in rows))


def evaluate_interpolation(adapter,clean,unsafe,output):
    rows=[]
    for f in clean+unsafe:
        result=adapter.interpolate(f['left'],f['right'],f['alpha'],confidence=f['confidence'],cut=f['cut'])
        actual=np.asarray(result['frame']);nearest=f['left'] if f['alpha']<=.5 else f['right']
        row=dict(name=f['name'],applied=bool(result['applied']),reason=result.get('reason',''))
        if f['name'] in {u['name'] for u in unsafe}:
            row['passed']=not row['applied'] and np.array_equal(actual,nearest)
        else:
            row.update(mae=mae(actual,f['expected']),nearest_mae=mae(nearest,f['expected']),sharpness_ratio=sharpness(actual)/sharpness(f['expected']))
            row['passed']=(not row['applied'] and np.array_equal(actual,nearest)) or (row['applied'] and row['mae']<=12 and row['mae']<=.75*row['nearest_mae'] and .8<=row['sharpness_ratio']<=1.25)
            np.savez_compressed(output/(f['name']+'.npz'),truth=f['expected'],nearest=nearest,candidate=actual)
        rows.append(row)
    accepted=sum(r['applied'] for r in rows[:len(clean)])
    return dict(rows=rows,applied_clean=accepted,passed=accepted>=6 and all(r['passed'] for r in rows))


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--adapter');args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    clean,unsafe,camera=fixtures(991027)
    payload={}
    for f in clean+unsafe:
        for key in ('left','right','expected'):
            if key in f:payload[f['name']+'_'+key]=f[key]
    for name,data in camera.items():
        for key,value in data.items():payload[name+'_'+key]=value
    np.savez_compressed(args.output/'fixtures.npz',**payload)
    result=dict(status='not_evaluated',seed=991027,gates=GATES,fixture_sha256=hashlib.sha256((args.output/'fixtures.npz').read_bytes()).hexdigest())
    if args.adapter:
        started=time.perf_counter()
        product_files=list(Path('src/video_manager').rglob('*.py'))
        hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in product_files}
        adapter=importlib.import_module(args.adapter)
        result['interpolation']=evaluate_interpolation(adapter,clean,unsafe,args.output)
        result['stabilization']=evaluate_stabilization(adapter,camera,args.output)
        result['status']='adapter_evaluated_integration_required'
        result['wall_seconds']=time.perf_counter()-started
        result['product_hashes']=hashes
        result['product_unchanged']=hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in product_files}
    (args.output/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(result['status'])


if __name__=='__main__':main()
