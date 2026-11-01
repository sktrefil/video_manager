"""Independent real encoding/decoding of combined phase-2 effects."""
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
import cv2

from verify_motion_phase2 import fixtures,registered_path,sharpness,texture
from video_manager.frame_effects import FrameEffects
from video_manager.render import Encoder,render_clips,decode_frames,ENHANCEMENT_ENCODING
from video_manager.probe import probe
from video_manager.time_map import build_map,select_schedule


def main():
    root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=False)
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in Path('src/video_manager').rglob('*.py')}
    _,_,cases=fixtures(991027);clips=[];schedules=[];times=[]
    for name in ['shake','pan','zoom']:
        encoder=Encoder(root/(name+'.mp4'),240,160,Fraction(20))
        try:
            for frame in cases[name]['frames']:encoder.write(frame.tobytes())
        finally:encoder.close()
        clip=probe(root/(name+'.mp4'),name);clips.append(clip)
        mapping=build_map(clip,4,.1,12,.4,80,Fraction(20))
        schedules.append(select_schedule(clip,mapping));times.append([mapping.source_time(i/20) for i in range(80)])
    baseline=render_clips(clips,root,schedules,prefix='off',output_fps=20)
    off=render_clips(clips,root,schedules,prefix='explicitoff',output_fps=20,
        enhancements={'interpolation':{'enabled':False},'stabilization':{'enabled':False}},source_times=times,protects=[.1]*len(clips))
    assert baseline['mapping']==off['mapping']
    left=list(decode_frames(probe(root/'off.mp4','a'),240,160))
    right=list(decode_frames(probe(root/'explicitoff.mp4','b'),240,160))
    assert left==right
    options={'interpolation':{'enabled':True},'stabilization':{'enabled':True}}
    # Check pre-encoding endpoint/protection bytes, which lossy encoding cannot prove.
    preencode_detail={}
    for clip,schedule,stamps in zip(clips,schedules,times):
        decoded=list(decode_frames(clip,240,160))
        enhanced=list(FrameEffects(clip,240,160,options,.1).frames(schedule,stamps,Fraction(20)))
        assert len(enhanced)==80
        for i in [0,1,2,79]:assert enhanced[i][1]==decoded[schedule[i]]
        ratios=[sharpness(np.frombuffer(row[1],np.uint8).reshape(160,240,3))/
                sharpness(np.frombuffer(decoded[schedule[i]],np.uint8).reshape(160,240,3))
                for i,row in enumerate(enhanced)]
        preencode_detail[clip.id]=dict(min_ratio=float(min(ratios)),worst_frame=int(np.argmin(ratios)))
    combined=render_clips(clips,root,schedules,prefix='combined',output_fps=20,
        enhancements=options,source_times=times,protects=[.1]*len(clips))
    video=probe(root/'combined.mp4','combined')
    assert len(video.frames)==240 and abs(video.duration-12)<.05
    # Compare processed quality at identical codec settings; legacy CRF18 is
    # separately retained for exact disabled-behavior checks, not as a CRF1 proxy.
    encoder=Encoder(root/'matched_codec_off.mp4',240,160,Fraction(20),fidelity=True)
    try:
        for clip,schedule in zip(clips,schedules):
            original=list(decode_frames(clip,240,160))
            for index in schedule:encoder.write(original[index])
    finally:encoder.close()
    matched=list(decode_frames(probe(root/'matched_codec_off.mp4','matched'),240,160))
    assert len(matched)==240
    actual=list(decode_frames(video,240,160));quality=[]
    for index,name in enumerate(['shake','pan','zoom']):
        before=np.array([np.frombuffer(b,np.uint8).reshape(160,240,3) for b in left[index*80:(index+1)*80]])
        after=np.array([np.frombuffer(b,np.uint8).reshape(160,240,3) for b in actual[index*80:(index+1)*80]])
        before_path,before_matrices=registered_path(before,return_matrices=True);after_path,matrices=registered_path(after,return_matrices=True)
        detail=min(sharpness(a)/sharpness(b) for a,b in zip(after,before))
        matched_frames=np.array([np.frombuffer(b,np.uint8).reshape(160,240,3) for b in matched[index*80:(index+1)*80]])
        matched_detail=min(sharpness(a)/sharpness(b) for a,b in zip(after,matched_frames))
        canvas=texture(991027);canvas_to_first=np.array([[1.,0.,-32.],[0.,1.,-32.],[0.,0.,1.]])
        truth=[cv2.warpAffine(canvas,(np.vstack((matrix,[0,0,1]))@canvas_to_first)[:2],(240,160),
                  flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT_101) for matrix in matrices]
        baseline_truth=[cv2.warpAffine(canvas,(np.vstack((matrix,[0,0,1]))@canvas_to_first)[:2],(240,160),
                  flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT_101) for matrix in before_matrices]
        analytic_ratios=np.array([sharpness(a)/sharpness(b) for a,b in zip(after,truth)])
        baseline_ratios=np.array([sharpness(a)/sharpness(b) for a,b in zip(before,baseline_truth)])
        normalized_ratios=analytic_ratios/baseline_ratios
        assert np.all(baseline_ratios/baseline_ratios==1.)
        analytic_detail=min(analytic_ratios)
        row=dict(name=name,min_decoded_sharpness_ratio=float(detail),min_analytic_view_sharpness_ratio=float(analytic_detail),
                 min_baseline_analytic_ratio=float(min(baseline_ratios)),min_pose_normalized_detail_retention=float(min(normalized_ratios)),
                 worst_retention_frame=int(np.argmin(normalized_ratios)),off_selfcheck_ratio=1.)
        row['min_preencode_source_sharpness_ratio']=preencode_detail[name]['min_ratio']
        row['min_matched_codec_sharpness_ratio']=float(matched_detail)
        row['preencode_worst_frame']=preencode_detail[name]['worst_frame']
        row['reference_policy']='received_source_and_matched_codec_control; legacy codec and analytic ratios diagnostic only'
        if name=='shake':
            row['rms_ratio']=float(np.sqrt(np.mean(after_path[8:-8,:2]**2))/np.sqrt(np.mean(before_path[8:-8,:2]**2)))
            row['motion_pass']=row['rms_ratio']<=.5
        elif name=='pan':
            before_velocity=np.polyfit(np.arange(80),before_path[:,0],1)[0]
            after_velocity=np.polyfit(np.arange(80),after_path[:,0],1)[0]
            row['velocity_relative_error']=float(abs(after_velocity-before_velocity)/abs(before_velocity))
            row['residual_velocity_error']=float(np.max(abs(np.diff(after_path[:,0])-np.diff(before_path[:,0]))))
            row['motion_pass']=row['velocity_relative_error']<=.1 and row['residual_velocity_error']<=.5
        else:
            row['scale_max_error']=float(np.max(abs(after_path[:,2]-before_path[:,2])))
            row['motion_pass']=row['scale_max_error']<=.01
        row['passed']=bool(row['motion_pass'] and matched_detail>=.8 and preencode_detail[name]['min_ratio']>=.8)
        quality.append(row)
    unchanged=hashes=={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in hashes}
    result=dict(product_hashes=hashes,product_unchanged=unchanged,decoded_frames=len(video.frames),
                duration=video.duration,off_exact=True,endpoints_protection_exact=True,audit=combined)
    result['combined_quality']=quality
    result['quality_control_encoding']=ENHANCEMENT_ENCODING
    result['combined_quality_passed']=all(r['passed'] for r in quality)
    (root/'audit.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    assert unchanged
    print('PASS decoded240frames12s/off_exact/protected_exact',flush=True)
    print('Combined quality:',quality,flush=True)
    for item in combined['enhancements']:
        print(item['clip_id'],item['stabilization']['applied'],item['stabilization']['reason'],
              item['transformed_output_frames'],item['interpolated_output_frames'],flush=True)
    assert result['combined_quality_passed'],'Independent combined quality gates failed; see audit.json'


if __name__=='__main__':main()
