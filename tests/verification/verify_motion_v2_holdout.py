"""Independent frozen holdout evaluation. No tuning on results."""
import hashlib
import json
from pathlib import Path
import time
import sys

import numpy as np

from video_manager.internal_motion import analyze_sources, apply_region
from video_manager.probe import probe
from video_manager.time_map import build_map, select_schedule


def main():
    root=Path(sys.argv[1] if len(sys.argv)>1 else 'outputs/motion-v2-independent');root.mkdir(exist_ok=True)
    files=['motion_analysis.py','motion_optimizer.py','internal_motion.py','time_map.py','retime.py','ui/app.py','cli.py','tools.py']
    hashes={f:hashlib.sha256((Path('src/video_manager')/f).read_bytes()).hexdigest() for f in files}
    manifest=json.loads(Path('outputs/motion-m0/fixtures_manifest.json').read_text(encoding='utf-8'))
    rows=[]
    for fixture in manifest:
        if fixture['split']!='holdout':continue
        clip=probe(Path(fixture['path']),fixture['case'])
        tick=time.perf_counter();report=analyze_sources([clip]);elapsed=time.perf_counter()-tick
        source=report['sources'][0]
        truth=fixture['truth'];positions=np.array([t['object_x'] for t in truth])
        pairs=source['motion_components'];errors=[]
        for pair in pairs:
            i=pair['frame'];expected=np.array([truth[i]['camera_x']-truth[i-1]['camera_x'],truth[i]['camera_y']-truth[i-1]['camera_y']])
            errors.append(float(np.linalg.norm(np.array([pair['camera_dx'],pair['camera_dy']])-expected)))
        trials=[]
        for target in (4.,2.5,5.,3.):
            mapping=build_map(clip,target,.5,12,.5,round(target*20),clip.fps)
            original=select_schedule(clip,mapping)
            reasons=[apply_region(mapping,r) for r in source['regions']]
            final=select_schedule(clip,mapping)
            before=float(np.var(np.diff(positions[original],n=2)));after=float(np.var(np.diff(positions[final],n=2)))
            repeats=lambda s:float(np.mean(np.diff(positions[s])==0))
            assert final[0]==0 and final[-1]==79 and final==sorted(final)
            assert final[:11]==original[:11] and mapping.speed_bound()<=12
            assert not any(r['start_seconds']<cut<r['end_seconds'] for r in source['regions'] for cut in source['diagnostics']['cuts'])
            trials.append(dict(target=target,reasons=reasons,changed=sum(a!=b for a,b in zip(original,final)),
                analytic_acceleration_gain=1-after/before if before else None,
                repeat_increase=repeats(final)-repeats(original),schedule=final,
                optimization=mapping.optimization_reviews))
        row=dict(case=fixture['case'],analysis_seconds=elapsed,regions=len(source['regions']),
                 kinds=[r['kinds'] for r in source['regions']],camera_median_error=float(np.median(errors)),
                 diagnostics=source['diagnostics'],trials=trials)
        rows.append(row);print(fixture['case'],row['regions'],[(t['target'],t['changed'],t['analytic_acceleration_gain']) for t in trials],flush=True)
    assert hashes=={f:hashlib.sha256((Path('src/video_manager')/f).read_bytes()).hexdigest() for f in files},'Product changed during verification'
    (root/'holdout.json').write_text(json.dumps(dict(hashes=hashes,rows=rows),indent=2),encoding='utf-8')


if __name__=='__main__':main()
