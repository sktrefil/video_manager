"""Calibration-only M1-M3 comparison. Never reads or runs holdout fixtures.

python tests/fixtures/run_motion_phase1.py --output outputs/motion-phase1
Each run gets a fresh directory; historical measurements are preserved.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import sys

import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from motion_benchmark import memory, sha, write_json
from video_manager.internal_motion import analyze_sources,apply_region
from video_manager.probe import probe
from video_manager.render import render_clips
from video_manager.time_map import build_map,select_schedule


def run(output):
    directory=output/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    directory.mkdir(parents=True)
    code_before={p.name:sha(p) for p in Path('src/video_manager').glob('*.py')}
    baseline=Path('outputs/motion-m0')
    fixtures=[f for f in json.loads((baseline/'fixtures_manifest.json').read_text(encoding='utf-8'))
              if f['split']=='calibration']
    gates=json.loads((baseline/'acceptance_gates.json').read_text(encoding='utf-8'))
    write_json(directory/'gates.json',gates)
    rows=[];started=time.perf_counter()
    for fixture in fixtures:
        path=Path(fixture['path'])
        if sha(path)!=fixture['sha256']:raise ValueError(f'Fixture changed: {path}')
        clip=probe(path,fixture['case']);case_dir=directory/fixture['case'];case_dir.mkdir()
        target=3.0 if fixture['case']=='speed_jump' else clip.duration
        output_count=round(target*float(clip.fps))
        versions={}; original=None
        for version in ('motion-v1','motion-v2'):
            tick=time.perf_counter();report=analyze_sources([clip],version=version)
            elapsed=time.perf_counter()-tick
            write_json(case_dir/f'{version}_report.json',report)
            mapping=build_map(clip,target,.5,12,.5,output_count,clip.fps)
            original=select_schedule(clip,mapping)
            reasons=[apply_region(mapping,r) for r in report['sources'][0]['regions']]
            selected=select_schedule(clip,mapping)
            positions=np.array([t['object_x'] for t in fixture['truth']])
            before=float(np.var(np.diff(positions[original],n=2)))
            after=float(np.var(np.diff(positions[selected],n=2)))
            versions[version]={'analysis_seconds':elapsed,'region_count':len(reasons),'decisions':reasons,
                'changed_frames':sum(a!=b for a,b in zip(original,selected)),
                'schedule':selected,'acceleration_variance_before':before,'acceleration_variance_after':after,
                'duration_error_frames':abs(len(selected)-output_count),
                'analytic_acceleration_variance_reduction':1-after/before if before>1e-10 else None,
                'additional_repeat_fraction':float(np.mean(np.diff(selected)==0)-np.mean(np.diff(original)==0)),
                'movement_extent_ratio':float(np.ptp(positions[selected])/np.ptp(positions[original])) if np.ptp(positions[original])>0 else None,
                'endpoints_preserved':selected[0]==0 and selected[-1]==len(clip.frames)-1,
                'protected_preserved':selected[:11]==original[:11],'monotonic':selected==sorted(selected),
                'diagnostics':report['sources'][0].get('diagnostics')}
            cuts=report['sources'][0].get('diagnostics',{}).get('cuts',[])
            versions[version]['cut_crossings']=sum(r['start_seconds']<c<r['end_seconds']
                for r in report['sources'][0]['regions'] for c in cuts)
            pairs=report['sources'][0].get('motion_components',[])
            errors=[]
            for pair in pairs:
                if pair.get('camera_confidence',0)<=0:continue
                i=pair['frame'];truth=fixture['truth']
                scale=fixture['width']/report['sources'][0]['diagnostics']['analysis_size'][0]
                errors.append(float(np.hypot(pair['camera_dx']*scale-(truth[i]['camera_x']-truth[i-1]['camera_x']),
                    pair['camera_dy']*scale-(truth[i]['camera_y']-truth[i-1]['camera_y']))))
            versions[version]['camera_displacement_median_error_source_px']=float(np.median(errors)) if errors else None
            versions[version]['camera_measured_pairs']=len(errors)
        if fixture['case'] in ('repeated_frames','speed_jump','exposure_change','scene_cut'):
            render_clips([clip],case_dir,[original],prefix='original')
            for version in versions:
                tick=time.perf_counter()
                rendered=render_clips([clip],case_dir,[versions[version]['schedule']],prefix=version)
                decoded=probe(case_dir/f'{version}.mp4',version)
                versions[version]['render_seconds']=time.perf_counter()-tick
                versions[version]['decoded_duration_seconds']=decoded.duration
                versions[version]['decoded_frame_count']=len(decoded.frames)
                versions[version]['render_sha256']=sha(case_dir/f'{version}.mp4')
        rows.append({'case':fixture['case'],'target_seconds':target,'expected_action':fixture['expected_action'],
                     'input_sha256':fixture['sha256'],'versions':versions})
        write_json(directory/'results.json',rows)
        print(fixture['case'],[(v,d['region_count'],d['changed_frames']) for v,d in versions.items()],flush=True)
    normal=[r for r in rows if r['expected_action']=='do_not_correct']
    defects=[r for r in rows if r['expected_action']=='temporal_candidate']
    summary={}
    for version in ('motion-v1','motion-v2'):
        summary[version]={'normal_correction_rate':sum(r['versions'][version]['changed_frames']>0 for r in normal)/len(normal),
            'temporal_suspicion_recall':sum(r['versions'][version]['region_count']>0 for r in defects)/len(defects),
            'invariant_failures':sum(not all(r['versions'][version][k] for k in ('endpoints_preserved','protected_preserved','monotonic')) for r in rows),
            'analysis_seconds':sum(r['versions'][version]['analysis_seconds'] for r in rows),
            'cut_crossings':sum(r['versions'][version]['cut_crossings'] for r in rows)}
        metric=summary[version];limits=gates['gates']
        metric['evaluated_gates']={
            'normal_false_correction':metric['normal_correction_rate']<=limits['normal_clip_false_correction_rate_max'],
            'temporal_suspicion_recall':metric['temporal_suspicion_recall']>=limits['synthetic_repeat_and_speed_jump_recall_min'],
            'schedule_invariants':metric['invariant_failures']==0,
            'cut_crossings':metric['cut_crossings']==0,
            'runtime':metric['analysis_seconds']/(len(fixtures)*4)<=limits['analysis_cpu_seconds_per_video_second_max']}
    code_after={p.name:sha(p) for p in Path('src/video_manager').glob('*.py')}
    write_json(directory/'summary.json',{'split':'calibration_only','metrics':summary,
        'code_sha256':code_before,'code_stable_during_run':code_before==code_after,
        'gates_sha256':sha(baseline/'acceptance_gates.json'),'total_seconds':time.perf_counter()-started,
        'python_peak_rss_bytes':memory(),'human_visual_verdict':'pending',
        'limitations':'Suspicion recall is not type classification. Analytic scalar acceleration is not visual quality. Holdout belongs to independent verifier.'})
    real=baseline/'real_ship_regions.json'
    if real.exists():write_json(directory/'real_ship_inventory_pending_review.json',json.loads(real.read_text(encoding='utf-8')))
    print('RESULT',directory,flush=True)
    return directory


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=Path('outputs/motion-phase1'))
    run(parser.parse_args().output)
