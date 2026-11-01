"""Opt-in CPU rigid stabilization, with bounded crop and exact protected frames.

Matrices map decoded source-raster pixels to output pixels. Crop is the total
removed dimension fraction ``1 - 1 / zoom`` (half per edge for centered scaling).
No border synthesis is accepted: inverse-mapped output corners must lie inside
the input. A scene cut, unreliable camera model or zoom abstains for the clip.
"""
import math

import cv2
import numpy as np

from .errors import InputError

VERSION = 'stabilization-v1.2'
GATES = {'synthetic_acceleration_energy_reduction_min': .30,
         'linear_pan_correction_pixels_max': .05,
         'crop_over_budget_frames_max': 0,
         'protected_endpoint_pixel_changes_max': 0}


def _identity():
    return np.array([[1., 0., 0.], [0., 1., 0.]])


_LANCZOS_OFFSETS=np.arange(-7,9)
_LANCZOS_PHASES=4096
_lanczos_distance=np.arange(_LANCZOS_PHASES+1)[:,None]/_LANCZOS_PHASES-_LANCZOS_OFFSETS[None]
_LANCZOS_TABLE=np.sinc(_lanczos_distance)*np.sinc(_lanczos_distance/8)
_LANCZOS_TABLE=(_LANCZOS_TABLE/_LANCZOS_TABLE.sum(axis=1,keepdims=True)).astype(np.float32)
del _lanczos_distance


def _lanczos_weights(coordinate):
    base=np.floor(coordinate).astype(np.int32)
    # A standard phase table avoids per-pixel transcendental functions. Maximum
    # coordinate quantization is 1/8192 pixel; weights remain normalized.
    phase=np.rint((coordinate-base)*_LANCZOS_PHASES).astype(np.int32)
    weights=np.moveaxis(_LANCZOS_TABLE[phase],-1,0)
    return base,_LANCZOS_OFFSETS,weights


def _lanczos8_affine(frame,matrix):
    """Two 16-tap shear passes, with float32 intermediate and bounded row chunks.

For inverse affine x=aX+bY+c, y=dX+eY+f, first interpolate source
x=(a-b*d/e)X+(b/e)y+c-b*f/e on each source row. Then interpolate
this intermediate at y=dX+eY+f. No quantization or sharpening between passes.
The near-singular shear case cannot arise in supported small rigid corrections
and is rejected explicitly instead of silently changing reconstruction quality.
"""
    height,width=frame.shape[:2]
    inverse=cv2.invertAffineTransform(matrix)
    (a,b,c),(d,e,f)=inverse
    if abs(e)<1e-6:
        raise InputError('Stabilization transform exceeds supported shear geometry')
    intermediate=np.empty((height,width,3),np.float32)
    output=np.empty_like(frame)
    for first in range(0,height,64):
        last=min(height,first+64)
        yy,xx=np.mgrid[first:last,:width]
        coordinate=(a-b*d/e)*xx+(b/e)*yy+c-b*f/e
        base,offsets,weights=_lanczos_weights(coordinate)
        row=np.zeros((last-first,width,3),np.float32)
        source_rows=yy.astype(np.float32)
        for index,offset in enumerate(offsets):
            sampled=cv2.remap(frame,(base+offset).astype(np.float32),source_rows,
                              cv2.INTER_NEAREST,borderMode=cv2.BORDER_REPLICATE)
            row+=sampled*weights[index,...,None]
        intermediate[first:last]=row
    for first in range(0,height,64):
        last=min(height,first+64)
        yy,xx=np.mgrid[first:last,:width]
        base,offsets,weights=_lanczos_weights(d*xx+e*yy+f)
        row=np.zeros((last-first,width,3),np.float32)
        source_columns=xx.astype(np.float32)
        for index,offset in enumerate(offsets):
            sampled=cv2.remap(intermediate,source_columns,(base+offset).astype(np.float32),
                              cv2.INTER_NEAREST,borderMode=cv2.BORDER_REPLICATE)
            row+=sampled*weights[index,...,None]
        output[first:last]=np.clip(np.rint(row),0,255).astype(np.uint8)
    return output


def apply_transform(frame, matrix):
    """Apply an output-pixel affine to RGB uint8, retaining identity bytes exactly."""
    matrix=np.asarray(matrix,dtype=float)
    if matrix.shape!=(2,3) or not np.all(np.isfinite(matrix)):
        raise InputError('Invalid stabilization transform')
    if np.array_equal(matrix,_identity()):return frame
    height,width=frame.shape[:2]
    return _lanczos8_affine(frame,matrix)


def _rigid(dx,dy,angle,width,height):
    c,s=math.cos(angle),math.sin(angle)
    rotation=np.array([[c,-s],[s,c]])
    center=np.array([(width-1)/2,(height-1)/2])
    matrix=np.eye(3);matrix[:2,:2]=rotation
    matrix[:2,2]=center-rotation@center+np.array([dx,dy])
    return matrix


def _coverage(matrix,width,height):
    corners=np.array([[0,0,1],[width-1,0,1],[width-1,height-1,1],[0,height-1,1]],dtype=float).T
    source=np.linalg.inv(matrix)@corners
    return bool(np.all(source[0]>=-1e-7) and np.all(source[0]<=width-1+1e-7)
                and np.all(source[1]>=-1e-7) and np.all(source[1]<=height-1+1e-7))


def _cover(matrix,width,height,budget):
    if _coverage(matrix,width,height):return matrix,0.
    center=np.array([(width-1)/2,(height-1)/2])
    def zoomed(zoom):
        scale=np.eye(3);scale[:2,:2]*=zoom;scale[:2,2]=center*(1-zoom)
        return scale@matrix
    lo,hi=1.,1/(1-budget)
    if not _coverage(zoomed(hi),width,height):return None,None
    for _ in range(32):
        middle=(lo+hi)/2
        if _coverage(zoomed(middle),width,height):hi=middle
        else:lo=middle
    return zoomed(hi),1-1/hi


def _camera_pair(previous,current):
    """Fit geometry before using image differences as evidence of a cut.

Unaligned correlation is not a cut detector on high-texture camera motion.
Require spatially distributed forward/backward tracks, robust affine inliers,
and agreement after warping. A moving foreground alone cannot establish camera.
"""
    height,width=current.shape
    result=dict(camera_confidence=0.,camera_scale=None,cut=False,
                abstain_reason='unreliable_camera_model')
    groups=[]
    for row in range(3):
        for col in range(3):
            x0,x1=col*width//3,(col+1)*width//3
            y0,y1=row*height//3,(row+1)*height//3
            points=cv2.goodFeaturesToTrack(previous[y0:y1,x0:x1],60,.02,5,blockSize=5)
            if points is not None:
                points+=np.array([x0,y0],np.float32);groups.append(points)
    if not groups:return result
    points=np.concatenate(groups)
    if len(points)<20:return result
    nxt,status,_=cv2.calcOpticalFlowPyrLK(previous,current,points,None,winSize=(31,31),maxLevel=4)
    if nxt is None:return result
    back,back_status,_=cv2.calcOpticalFlowPyrLK(current,previous,nxt,None,winSize=(31,31),maxLevel=4)
    if back is None:return result
    good=(status.ravel()>0)&(back_status.ravel()>0)&(np.linalg.norm(back-points,axis=2).ravel()<1.)
    p=points.reshape(-1,2)[good];q=nxt.reshape(-1,2)[good]
    if len(p)<20:return result
    affine,inliers=cv2.estimateAffinePartial2D(p,q,method=cv2.RANSAC,ransacReprojThreshold=1.,
                                             maxIters=2000,confidence=.995,refineIters=10)
    if affine is None:return result
    mask=inliers.ravel().astype(bool)
    cells=np.clip((p/np.array([width,height])*3).astype(int),0,2)
    coverage=len(set(map(tuple,cells[mask])))
    confidence=float(np.mean(mask)*len(p)/len(points))
    if coverage<5 or confidence<.6:return result
    aligned=cv2.warpAffine(previous,affine,(width,height),flags=cv2.INTER_LINEAR)
    valid=cv2.warpAffine(np.ones_like(previous),affine,(width,height),flags=cv2.INTER_NEAREST)>0
    # Exclude the interpolation footprint at the transformed image boundary.
    valid=cv2.erode(valid.astype(np.uint8),np.ones((3,3),np.uint8)).astype(bool)
    # Compare a common low-pass support: subpixel camera motion resamples fine
    # texture, so raw pixel residuals include aliasing even for a correct fit.
    a=cv2.GaussianBlur(aligned,(5,5),0)[valid].astype(float)
    b=cv2.GaussianBlur(current,(5,5),0)[valid].astype(float)
    if len(a)<100 or np.std(a)<2 or np.std(b)<2:return result
    correlation=float(np.corrcoef(a,b)[0,1])
    difference=b-a;residual=float(np.mean(abs(difference-np.median(difference))))
    if correlation<.75 or residual>max(12.,.35*float(np.std(b))):
        result.update(cut=correlation<.4,abstain_reason='photometric_fit_failed')
        return result
    center=np.array([(width-1)/2,(height-1)/2])
    displacement=affine[:,:2]@center+affine[:,2]-center
    result.update(camera_confidence=confidence,camera_scale=float(np.hypot(affine[0,0],affine[1,0])),
                  camera_dx=float(displacement[0]),camera_dy=float(displacement[1]),
                  camera_rotation=float(np.arctan2(affine[1,0],affine[0,0])),
                  abstain_reason='',aligned_correlation=correlation,aligned_mae=residual)
    return result


def plan_from_frames(frames,times,*,output_size=None,crop_budget=.05,smooth_seconds=.4,
                     protect_seconds=0.,strength=.7):
    """Streaming camera analysis; returns JSON-ready transforms and audit.

Input frames must share the renderer's fitted/padded aspect. Only the previous
analysis image is held. ``output_size`` converts the analysis affine into final
output pixels. Linear drift is removed before smoothing and then restored, so
constant-speed pans are not erased. No semantic claim about intent is made.
"""
    values=(crop_budget,smooth_seconds,protect_seconds,strength)
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in values):
        raise InputError('Stabilization settings must be finite numbers')
    if not 0<=crop_budget<=.25 or not 0<smooth_seconds<=2 or protect_seconds<0 or not 0<=strength<=1:
        raise InputError('Invalid stabilization crop, smoothing, protection or strength')
    times=np.asarray(times,dtype=float)
    if times.ndim!=1 or len(times)<1 or not np.all(np.isfinite(times)) or np.any(np.diff(times)<=0):
        raise InputError('Stabilization times must increase')
    previous=None;pairs=[];shape=None;scale_log=0.;max_scale_log=0.;count=0
    for index,frame in enumerate(frames):
        if index>=len(times):raise InputError('Extra stabilization frame')
        gray=cv2.cvtColor(frame,cv2.COLOR_RGB2GRAY) if frame.ndim==3 else np.asarray(frame,dtype=np.uint8)
        if shape is None:shape=gray.shape
        if gray.shape!=shape:raise InputError('Stabilization dimensions changed')
        if previous is not None:
            pair=_camera_pair(previous,gray)
            scale=pair['camera_scale']
            if scale is not None and scale>0:
                scale_log+=math.log(scale);max_scale_log=max(max_scale_log,abs(scale_log))
            pairs.append(pair)
        previous=gray;count+=1
    if count!=len(times):raise InputError('Missing stabilization frame')
    height,width=shape
    output_width,output_height=output_size or (width,height)
    if min(output_width,output_height)<2:raise InputError('Invalid stabilization output size')
    transforms=[_identity().tolist() for _ in times]
    audit={'version':VERSION,'applied':False,'reason':'','analysis_size':[width,height],
           'output_size':[output_width,output_height],'coordinate_space':'decoded_output_pixels_source_to_output',
           'crop_budget_fraction':crop_budget,'crop_definition':'total_dimension_removed_1_minus_inverse_zoom',
           'crop_policy':'constant_interior_zoom_with_protection_and_endpoint_fades',
           'protect_seconds':protect_seconds,'strength_requested':strength,'smooth_seconds':smooth_seconds,
           'crop_fractions':[0.]*count,'max_crop_fraction':0.,'changed_frames':0,
           'zoom_policy':'abstain_if_cumulative_scale_exceeds_0.8_percent',
           'pan_policy':'preserve_linear_drift; uncertain_intent_requires_review',
           'confidence_min':min((p['camera_confidence'] for p in pairs),default=0.),
           'requires_visual_review':True}
    audit['reconstruction']='Lanczos8_two_shear_passes_float32_intermediate_no_sharpening'
    audit['detail_limitation']='Near-Nyquist white-noise texture can lose detail under subpixel resampling; visual review required'
    def reject(reason):
        audit['reason']=reason
        return {'transforms':transforms,'audit':audit}
    if count<5:return reject('insufficient_frames')
    if strength==0:return reject('strength_zero')
    if any(p['cut'] for p in pairs):return reject('scene_cut')
    if any(p['camera_confidence']<.6 or p['camera_scale'] is None or p['abstain_reason'] for p in pairs):
        return reject('unreliable_camera_model')
    if max_scale_log>math.log(1.008):return reject('intentional_or_unknown_zoom')
    path=np.zeros((count,3));current=np.eye(3)
    center=np.array([(width-1)/2,(height-1)/2,1.])
    for index,pair in enumerate(pairs,1):
        current=_rigid(pair['camera_dx'],pair['camera_dy'],pair['camera_rotation'],width,height)@current
        displacement=current@center-center
        path[index]=[displacement[0],displacement[1],math.atan2(current[1,0],current[0,0])]
    path[:,2]=np.unwrap(path[:,2])
    u=(times-times[0])/(times[-1]-times[0]);trend=u[:,None]*path[-1]
    residual=path-trend
    radius=max(1,int(round(smooth_seconds/float(np.median(np.diff(times))))))
    kernel=np.r_[np.arange(1,radius+2),np.arange(radius,0,-1)].astype(float);kernel/=sum(kernel)
    smoothed=np.column_stack([np.convolve(np.pad(residual[:,i],radius,mode='edge'),kernel,mode='valid') for i in range(3)])+trend
    correction=smoothed-path
    # Fade from the protected source time and into the last original frame.
    start=max(times[0],protect_seconds)
    envelope=np.zeros(count)
    if times[-1]>start:
        active=times>start
        edge=min(.3,(times[-1]-start)/3)
        envelope[active]=np.minimum(1,(times[active]-start)/edge)*np.minimum(1,(times[-1]-times[active])/edge)
    envelope[[0,-1]]=0
    correction*=envelope[:,None]
    pixel_magnitude=np.hypot(correction[:,0],correction[:,1])+abs(correction[:,2])*math.hypot(width,height)/2
    if np.max(pixel_magnitude)<.15:return reject('steady_pan_or_no_shake')
    scaling=np.diag([output_width/width,output_height/height,1.])
    scaling[:2,2]=[(output_width/width-1)/2,(output_height/height-1)/2]
    for candidate_strength in (strength,strength*.75,strength*.5,strength*.25):
        raw_matrices=[];required_zoom=[]
        for index,delta in enumerate(correction*candidate_strength):
            if envelope[index]==0:
                raw_matrices.append(np.eye(3));required_zoom.append(1.);continue
            actual=_rigid(*path[index],width,height)
            desired=_rigid(*(path[index]+delta),width,height)
            matrix=scaling@desired@np.linalg.inv(actual)@np.linalg.inv(scaling)
            covered,crop=_cover(matrix,output_width,output_height,crop_budget)
            if covered is None:break
            raw_matrices.append(matrix);required_zoom.append(1/(1-crop))
        if len(raw_matrices)==count:
            # Varying minimum crop on every frame creates visible zoom pumping.
            # Share one interior zoom; only the mandatory protection/end fade varies.
            excess=max((z-1)/e for z,e in zip(required_zoom,envelope) if e>0)
            if 1+excess>1/(1-crop_budget)+1e-10:continue
            candidate=[];crops=[]
            center_out=np.array([(output_width-1)/2,(output_height-1)/2])
            for matrix,e in zip(raw_matrices,envelope):
                z=1+excess*e
                zoom=np.eye(3);zoom[:2,:2]*=z;zoom[:2,2]=center_out*(1-z)
                covered=zoom@matrix
                if not _coverage(covered,output_width,output_height):break
                candidate.append(covered[:2].tolist());crops.append(1-1/z)
            if len(candidate)!=count:continue
            changed=sum(not np.allclose(m,_identity(),atol=1e-10,rtol=0) for m in candidate)
            audit.update(applied=bool(changed),reason='candidate_requires_visual_review',
                         strength_applied=candidate_strength,crop_fractions=crops,max_crop_fraction=max(crops),
                         changed_frames=changed,estimated_camera_path=path.tolist(),
                         path_coordinate_space='analysis_pixels_and_radians',
                         applied_correction_path=(correction*candidate_strength).tolist())
            return {'transforms':candidate,'audit':audit}
    return reject('crop_budget_insufficient')


def plan_stabilization(clip,*,output_size=None,crop_budget=.05,smooth_seconds=.4,
                       protect_seconds=0.,strength=.7):
    """Plan for the same DAR-fitted raster that render.decode_frames produces."""
    from .render import decode_frames
    from .progress import report
    if output_size is None:
        output_size=(max(2,round(clip.width*float(clip.sample_aspect_ratio)/2)*2),max(2,round(clip.height/2)*2))
    factor=min(1.,480/max(output_size))
    width=max(2,round(output_size[0]*factor/2)*2);height=max(2,round(output_size[1]*factor/2)*2)
    def frames():
        for i,raw in enumerate(decode_frames(clip,width,height)):
            report(f'Analyze stabilization · {clip.id}',i+1,len(clip.frames))
            yield np.frombuffer(raw,np.uint8).reshape(height,width,3)
    return plan_from_frames(frames(),[f['source_seconds'] for f in clip.frames],output_size=output_size,
                            crop_budget=crop_budget,smooth_seconds=smooth_seconds,
                            protect_seconds=protect_seconds,strength=strength)
