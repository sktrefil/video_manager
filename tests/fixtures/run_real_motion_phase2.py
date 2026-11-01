"""Four original-ship technical comparisons; execute only after phase2 freeze."""
import argparse
from dataclasses import replace
from datetime import datetime,timezone
from fractions import Fraction
import json
from pathlib import Path
import time

import numpy as np

from motion_benchmark import memory,sha,write_json
from video_manager.probe import probe
from video_manager.render import render_clips,decode_frames,Encoder,ENHANCEMENT_ENCODING
from video_manager.frame_effects import FrameEffects
from video_manager.time_map import build_map,select_schedule
from video_manager.tools import run_tool


def pixel_comparison(baseline,variant,width,height):
    first=probe(baseline,'baseline');second=probe(variant,'variant')
    left=decode_frames(first,width,height);right=decode_frames(second,width,height)
    count=changed=0;mae=[]
    try:
        for a,b in zip(left,right,strict=True):
            count+=1;changed+=int(a!=b)
            mae.append(float(np.mean(abs(np.frombuffer(a,np.uint8).astype(float)-np.frombuffer(b,np.uint8)))))
    finally:left.close();right.close()
    return dict(decoded_frames=count,decoded_changed_frames=changed,
                mean_pixel_difference=float(np.mean(mae)),max_frame_mean_pixel_difference=max(mae))


def raw_control(clip,folder,schedule,width,height):
    """Same-codec baseline plus bounded preencoding reference hashes."""
    import hashlib
    hashes=[];cursor=0
    encoder=Encoder(folder/'baseline_fidelity.mp4',width,height,clip.fps,fidelity=True)
    failed=True
    try:
        for index,data in enumerate(decode_frames(clip,width,height)):
            while cursor<len(schedule) and schedule[cursor]==index:
                hashes.append(hashlib.sha256(data).hexdigest());encoder.write(data);cursor+=1
        if cursor!=len(schedule):raise ValueError('Fidelity control schedule incomplete')
        failed=False
    finally:encoder.close(failed)
    return hashes


def raw_effect_attribution(clip,schedule,requested,options,width,height,baseline_hashes):
    import hashlib
    changed=[];interpolated=[];spatial=[]
    effects=FrameEffects(clip,width,height,options,1.)
    frames=effects.frames(schedule,requested,clip.fps)
    try:
        for index,(_,data,audit) in enumerate(frames):
            if hashlib.sha256(data).hexdigest()!=baseline_hashes[index]:changed.append(index)
            if audit['interpolation']['applied']:interpolated.append(index)
            if any(not np.allclose(row['matrix'],[[1,0,0],[0,1,0]],atol=1e-10)
                   for row in audit.get('spatial_transforms',[])):spatial.append(index)
    finally:frames.close()
    return dict(changed_output_frames=len(changed),changed_frame_indices=changed,
                interpolated_output_frames=len(interpolated),spatial_output_frames=len(spatial),
                reference='SHA256 exact preencoding RGB vs original target-matched frames')


def run(output):
    directory=output/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');directory.mkdir(parents=True)
    before={str(p):sha(p) for p in Path('src/video_manager').rglob('*.py')}
    inventory_path=Path('outputs/motion-m0/real_ship_regions.json')
    job_path=Path('jobs/spanish_armada_18_clips.json')
    inventory=json.loads(inventory_path.read_text(encoding='utf-8'))
    targets={Path(row['path']).stem.replace('_','-'):row['target_seconds']
             for row in json.loads(job_path.read_text(encoding='utf-8'))['clips']}
    chosen=[]
    for row in inventory['regions']:
        if row['path'] not in [item['path'] for item in chosen]:chosen.append(row)
        if len(chosen)==4:break
    options={name:dict(interpolation=dict(enabled=interpolation,backend='cpu_flow'),
                      stabilization=dict(enabled=stabilization,strength=.7,smoothing_seconds=.4,max_crop_fraction=.05))
             for name,interpolation,stabilization in [('baseline',False,False),('interpolation',True,False),
                                                     ('stabilization',False,True),('combined',True,True)]}
    write_json(directory/'options.json',options)
    results=[]
    for item in chosen:
        source=Path(item['path']);assert sha(source)==item['sha256'],'Original source changed'
        clip=probe(source,source.stem);target=targets[source.stem.replace('_','-')]
        count=round(target*float(clip.fps));mapping=build_map(clip,target,1,12,.5,count,clip.fps)
        schedule=select_schedule(clip,mapping)
        requested=[mapping.source_time(i/float(clip.fps)) for i in range(count)]
        width=640;height=max(2,round(clip.height/(clip.width*float(clip.sample_aspect_ratio))*width/2)*2)
        preview=replace(clip,width=width,height=height,sample_aspect_ratio=Fraction(1))
        folder=directory/source.stem;folder.mkdir();variants={}
        baseline_hashes=raw_control(preview,folder,schedule,width,height)
        for name,setting in options.items():
            print(f'{source.name}: {name}',flush=True);started=time.perf_counter()
            result=render_clips([preview],folder,[schedule],prefix=name,enhancements=setting,
                                source_times=[requested],protects=[1.])
            elapsed=time.perf_counter()-started
            write_json(folder/f'{name}_mapping.json',result)
            decoded=probe(folder/f'{name}.mp4',name)
            if len(decoded.frames)!=count or abs(decoded.duration-target)>1/float(clip.fps):
                raise ValueError('Rendered frame budget/duration mismatch')
            rows=result['mapping']
            if [r['source_frame'] for r in rows]!=schedule:raise ValueError('Unexpected source selection change')
            for i,row in enumerate(rows):
                if i in (0,count-1) or requested[i]<=1:
                    if row.get('interpolation',{}).get('applied'):raise ValueError('Endpoint/protection interpolation violation')
                    if any(not np.allclose(s['matrix'],[[1,0,0],[0,1,0]],atol=1e-9)
                           for s in row.get('spatial_transforms',[])):raise ValueError('Endpoint/protection transform violation')
            variants[name]=dict(render_seconds=elapsed,frame_count=len(decoded.frames),duration_seconds=decoded.duration,
                video_sha256=sha(folder/f'{name}.mp4'),mapping_sha256=sha(folder/f'{name}_mapping.json'),
                encoding=result.get('encoding',dict(profile='legacy',codec='libx264',crf=18)),
                enhancements=result.get('enhancements',[]))
            if name!='baseline':
                variants[name]['decoded_comparison']=pixel_comparison(folder/'baseline_fidelity.mp4',folder/f'{name}.mp4',width,height)
                tick=time.perf_counter()
                variants[name]['preencoding_attribution']=raw_effect_attribution(preview,schedule,requested,setting,width,height,baseline_hashes)
                variants[name]['attribution_check_seconds']=time.perf_counter()-tick
        montage=folder/'comparison.mp4'
        command=['ffmpeg','-v','error','-nostdin','-n']
        for name in options:command+=['-i',str(folder/('baseline_fidelity.mp4' if name=='baseline' else f'{name}.mp4'))]
        command+=['-filter_complex','[0:v][1:v]hstack=inputs=2[top];[2:v][3:v]hstack=inputs=2[bottom];[top][bottom]vstack=inputs=2[v]',
                  '-map','[v]','-an','-c:v','libx264','-threads','2','-preset','veryfast','-crf','1','-pix_fmt','yuv420p',str(montage)]
        run_tool(command,timeout=180)
        if len(probe(montage,'comparison').frames)!=count:raise ValueError('Montage frame budget mismatch')
        if sha(source)!=item['sha256']:raise ValueError('Original changed during processing')
        results.append(dict(source=str(source),source_sha256=item['sha256'],source_size=[clip.width,clip.height],
            source_fps=str(clip.fps),target_seconds=target,protect_seconds=1.,preview_size=[width,height],variants=variants,
            same_codec_control=dict(file='baseline_fidelity.mp4',sha256=sha(folder/'baseline_fidelity.mp4'),encoding=ENHANCEMENT_ENCODING),
            comparison=str(montage.resolve()),comparison_sha256=sha(montage),
            layout=[['baseline','interpolation'],['stabilization','combined']],
            human_quality_review='pending; preview-scale technical comparison only'))
        write_json(directory/'results.json',results)
    after={str(p):sha(p) for p in Path('src/video_manager').rglob('*.py')}
    write_json(directory/'provenance.json',dict(code_before=before,code_after=after,code_unchanged=before==after,
        inventory_sha256=sha(inventory_path),target_job_sha256=sha(job_path),peak_process_memory_bytes=memory(),
        source_policy='Original paths/timestamps and hashes retained; source guards decode from native original files',
        preview_policy='640px square-pixel previews, no v2 time warp; CRF1 same-codec control and preencoding RGB attribution',
        originals_unchanged=all(sha(Path(row['path']))==row['sha256'] for row in chosen)))
    print(directory,flush=True)
    return directory


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=Path('outputs/motion-phase2-real'))
    run(parser.parse_args().output)
