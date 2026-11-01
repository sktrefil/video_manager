"""Native-source analysis and 640px technical review previews, not quality approval."""
import argparse
from dataclasses import replace
from datetime import datetime, timezone
from fractions import Fraction
import json
from pathlib import Path
import time

from motion_benchmark import sha, write_json, memory
from video_manager.internal_motion import analyze_sources, apply_region
from video_manager.probe import probe
from video_manager.render import render_clips
from video_manager.time_map import build_map, select_schedule
from video_manager.tools import run_tool


def run(output):
    directory=output/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    directory.mkdir(parents=True)
    code_before={str(p):sha(p) for p in Path('src/video_manager').rglob('*.py')}
    inventory_path=Path('outputs/motion-m0/real_ship_regions.json')
    inventory=json.loads(inventory_path.read_text(encoding='utf-8'))
    job_path=Path('jobs/spanish_armada_18_clips.json')
    job=json.loads(job_path.read_text(encoding='utf-8'))
    targets={Path(c['path']).stem.replace('_','-'):c['target_seconds'] for c in job['clips']}
    chosen=[]
    for row in inventory['regions']:
        if row['path'] not in [item['path'] for item in chosen]: chosen.append(row)
        if len(chosen)==4: break
    results=[]
    for item in chosen:
        source=Path(item['path'])
        if sha(source)!=item['sha256']: raise ValueError('Source changed since M0 inventory')
        print(f'Analyze original source {source.name}',flush=True)
        clip=probe(source,source.stem);target=targets[source.stem.replace('_','-')]
        folder=directory/source.stem;folder.mkdir()
        count=round(target*float(clip.fps))
        base=build_map(clip,target,1,12,.5,count,clip.fps)
        original=select_schedule(clip,base)
        schedules={'baseline':original};versions={}
        for version in ('motion-v1','motion-v2'):
            tick=time.perf_counter();report=analyze_sources([clip],version=version)
            elapsed=time.perf_counter()-tick
            write_json(folder/f'{version}_analysis.json',report)
            mapping=build_map(clip,target,1,12,.5,count,clip.fps)
            decisions=[dict(region_id=r['id'],reason=apply_region(mapping,r)) for r in report['sources'][0]['regions']]
            selected=select_schedule(clip,mapping)
            schedules[version]=selected
            versions[version]=dict(analysis_seconds=elapsed,analysis_report_sha256=sha(folder/f'{version}_analysis.json'),
                decisions=decisions,changed_frames=sum(a!=b for a,b in zip(original,selected)),
                region_count=len(decisions),mapping=mapping.describe(),optimization=mapping.optimization_reviews)
        width=640; height=max(2,round(clip.height/(clip.width*float(clip.sample_aspect_ratio))*width/2)*2)
        preview_clip=replace(clip,width=width,height=height,sample_aspect_ratio=Fraction(1))
        rendered={}
        for label,schedule in schedules.items():
            tick=time.perf_counter()
            metadata=render_clips([preview_clip],folder,[schedule],prefix=label)
            decoded=probe(folder/f'{label}.mp4',label)
            rendered[label]=dict(render_seconds=time.perf_counter()-tick,width=decoded.width,height=decoded.height,
                duration_seconds=decoded.duration,frame_count=len(decoded.frames),sha256=sha(folder/f'{label}.mp4'))
            write_json(folder/f'{label}_mapping.json',metadata)
            if len(decoded.frames)!=count or abs(decoded.duration-target)>1/float(clip.fps):
                raise ValueError('Preview duration validation failed')
            if schedule[0]!=0 or schedule[-1]!=len(clip.frames)-1 or schedule!=sorted(schedule):
                raise ValueError('Frame schedule constraint failed')
            if any(a!=b for i,(a,b) in enumerate(zip(original,schedule)) if i/float(clip.fps)<=1):
                raise ValueError('Protected interval changed')
        comparison=folder/'comparison.mp4'
        run_tool(['ffmpeg','-v','error','-nostdin','-n','-i',str(folder/'baseline_diagnostic.mp4'),
            '-i',str(folder/'motion-v1_diagnostic.mp4'),'-i',str(folder/'motion-v2_diagnostic.mp4'),
            '-filter_complex','[0:v][1:v][2:v]hstack=inputs=3[v]','-map','[v]','-an',
            '-c:v','libx264','-threads','2','-preset','veryfast','-crf','18','-pix_fmt','yuv420p',str(comparison)],timeout=180)
        comp=probe(comparison,'comparison')
        if len(comp.frames)!=count: raise ValueError('Comparison frame count changed')
        row=dict(source=str(source),source_sha256=item['sha256'],target_seconds=target,protect_seconds=1,
            source_dimensions=[clip.width,clip.height],source_fps=str(clip.fps),versions=versions,
            previews=rendered,comparison=str(comparison.resolve()),comparison_order=['baseline_target_timing','legacy_v1','measured_v2'],
            visual_quality='pending human review; resized re-encoded previews only')
        results.append(row)
        write_json(directory/'results.json',results)
        print(f'Completed {source.name}: v1 changed {versions["motion-v1"]["changed_frames"]}, v2 changed {versions["motion-v2"]["changed_frames"]}',flush=True)
    code_after={str(p):sha(p) for p in Path('src/video_manager').rglob('*.py')}
    write_json(directory/'provenance.json',dict(code_before=code_before,code_after=code_after,
        code_unchanged=code_before==code_after,inventory_sha256=sha(inventory_path),target_job_sha256=sha(job_path),
        peak_process_memory_bytes=memory(),source_analysis='native file, v2 aspect-preserving max480 analysis',
        preview='source decoded directly to square-pixel 640px frames; source frame indices preserved',
        selection='first four distinct clips from frozen M0 suspicion inventory; not random or generalization proof'))
    print(directory,flush=True)
    return directory


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=Path('outputs/motion-phase1-real'))
    run(parser.parse_args().output)
