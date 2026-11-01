"""Reproducible M0 fixtures and frozen-engine baseline. Run from repository root.

python tests/fixtures/motion_benchmark.py --output outputs/motion-m0
The baseline package must already be copied to OUTPUT/baseline/video_manager.
No source media is modified. Ground truth is analytic, not detector-derived.
"""
import argparse
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time

import cv2
import numpy as np

CASES = ('constant', 'intentional_acceleration', 'intentional_stop', 'camera_shake',
         'object_only', 'opposing_objects', 'occlusion', 'repeated_frames',
         'exposure_change', 'scene_cut', 'low_texture', 'large_motion', 'speed_jump')
# Freeze these before running holdout or implementing M1-M3. They are acceptance
# requirements, NOT claimed achieved accuracy on unseen real-world footage.
GATES = {
    'normal_clip_false_correction_rate_max': 0.0,
    'cut_crossing_correction_count_max': 0,
    'synthetic_repeat_and_speed_jump_recall_min': 0.75,
    'camera_object_separation_median_error_px_per_frame_max': 1.5,
    'selected_candidate_acceleration_variance_reduction_min': 0.10,
    'selected_candidate_movement_extent_ratio_min': 0.95,
    'selected_candidate_new_repeat_fraction_increase_max': 0.02,
    'output_duration_error_frames_max': 1,
    'endpoint_or_protection_or_monotonicity_failures_max': 0,
    'analysis_cpu_seconds_per_video_second_max': 5.0,
    'analysis_python_peak_rss_bytes_max': 1073741824,
    'human_review_required_for_real_video': True,
}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')


def make_fixture(path, case, seed, width=320, height=180, count=80, fps=20):
    from video_manager.render import Encoder
    rng = np.random.default_rng(seed)
    background = rng.integers(30, 110, (height, width, 3), dtype=np.uint8)
    background = cv2.GaussianBlur(background, (5, 5), 0)
    tile = rng.integers(100, 240, (32, 32, 3), dtype=np.uint8)
    frames, truth = [], []
    for i in range(count):
        x = 24 + i*1.1
        camera_x = camera_y = 0.0
        if case == 'intentional_acceleration': x = 24 + .012*i*i
        if case in ('intentional_stop', 'repeated_frames'):
            x = 24 + 1.1*(i if i < 30 else 30 if i < 44 else i-14)
        if case == 'speed_jump': x = 24 + (.3*i if i < 40 else 12+2.0*(i-40))
        if case == 'large_motion': x = 24+(i*6) % (width-65)
        if case == 'camera_shake':
            x = 90
            camera_x, camera_y = 4*np.sin(i*1.7), 3*np.cos(i*1.3)
        frame = background.copy()
        if case == 'low_texture': frame[:] = 65
        ix = int(round(x)); iy = height//2-16
        frame[iy:iy+32, ix:ix+32] = tile
        if case == 'opposing_objects':
            other = int(width-60-i*1.1)
            frame[16:48, other:other+32] = tile[::-1]
        if case == 'occlusion' and 28 <= i < 48:
            frame[iy-8:iy+40, 40:140] = 50
        if case == 'exposure_change':
            frame = np.clip(frame.astype(float)*(1+.3*np.sin(i/7)),0,255).astype(np.uint8)
        if case == 'scene_cut' and i >= 40: frame = 255-frame[:, ::-1]
        if case == 'camera_shake':
            frame = cv2.warpAffine(frame, np.float32([[1,0,camera_x],[0,1,camera_y]]),
                                   (width,height), borderMode=cv2.BORDER_REFLECT)
        if case == 'repeated_frames' and 30 <= i < 44: frame = frames[29].copy()
        if case == 'repeated_frames' and 30 <= i < 44:
            x = 24+1.1*29
        frames.append(frame)
        truth.append({'frame': i, 'seconds': i/fps, 'object_x': float(round(x)),
                      'continuous_object_x': x,
                      'camera_x': float(camera_x), 'camera_y': float(camera_y),
                      'visible': not(case == 'occlusion' and 28 <= i < 48)})
    # Only replace this generated fixture, never a directory or source input.
    if path.exists(): path.unlink()
    enc = Encoder(path, width, height, Fraction(fps))
    try:
        for frame in frames: enc.write(frame.tobytes())
    finally: enc.close()
    defect = case in ('repeated_frames', 'speed_jump', 'camera_shake')
    return {'case':case,'seed':seed,'path':str(path.resolve()),'sha256':sha(path),
            'width':width,'height':height,'fps':fps,'frame_count':count,
            'label':'defect' if defect else 'normal_or_review_only',
            'expected_action': 'review_only' if case in ('occlusion','scene_cut','low_texture','large_motion')
            else 'temporal_candidate' if case in ('repeated_frames','speed_jump')
            else 'spatial_review' if case=='camera_shake' else 'do_not_correct',
            'defect_interval_seconds': [1.5,2.2] if case=='repeated_frames' else [1.6,2.4] if case=='speed_jump' else None,
            'cut_seconds': [2.0] if case=='scene_cut' else [],'truth':truth}


def memory():
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[(n,ctypes.c_size_t) for n in
                ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage',
                 'QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]
        c = Counters(); c.cb=ctypes.sizeof(c)
        kernel=ctypes.WinDLL('kernel32');kernel.GetCurrentProcess.restype=wintypes.HANDLE
        get_info=ctypes.WinDLL('psapi').GetProcessMemoryInfo
        get_info.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
        get_info.restype=wintypes.BOOL
        if not get_info(kernel.GetCurrentProcess(),ctypes.byref(c),c.cb):
            raise ctypes.WinError()
        return int(c.PeakWorkingSetSize)
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024


def run(output):
    snapshot = output/'baseline'
    if not (snapshot/'video_manager/internal_motion.py').exists():
        raise SystemExit('Snapshot missing; do not silently use changed engine')
    sys.path.insert(0,str(snapshot.resolve()))
    from video_manager.internal_motion import analyze_sources, apply_region
    from video_manager.probe import probe
    from video_manager.time_map import build_map, select_schedule
    from video_manager.tools import diagnose
    source_hashes = {p.name:sha(p) for p in sorted((snapshot/'video_manager').glob('*.py'))}
    write_json(output/'acceptance_gates.json', {'version':'m0-frozen-1','gates':GATES,
        'scope':'Synthetic engineering gates; real-world generalization requires labeled human review.',
        'split_rule':'calibration seed 1729; holdout seed 81031; never tune on holdout'})
    write_json(output/'baseline_hashes.json',source_hashes)
    started=time.perf_counter(); fixtures=[]; results=[]
    for split, seed in [('calibration',1729),('holdout',81031)]:
        directory=output/'fixtures'/split;directory.mkdir(parents=True,exist_ok=True)
        for index, case in enumerate(CASES):
            fixture=make_fixture(directory/f'{case}.mp4',case,seed+index,
                                 width=320 if split=='calibration' else 384,
                                 height=180 if split=='calibration' else 216)
            fixture['split']=split; fixtures.append(fixture)
            clip=probe(Path(fixture['path']),case)
            tick=time.perf_counter(); report=analyze_sources([clip]); elapsed=time.perf_counter()-tick
            regions=report['sources'][0]['regions']
            mapping=build_map(clip,clip.duration,.5,12,.5,len(clip.frames),clip.fps)
            original=select_schedule(clip,mapping)
            reasons=[apply_region(mapping,r) for r in regions]
            selected=select_schedule(clip,mapping)
            positions=np.array([t['object_x'] for t in fixture['truth']])
            before=float(np.var(np.diff(positions[original],n=2)))
            after=float(np.var(np.diff(positions[selected],n=2)))
            row={'split':split,'case':case,'analysis_seconds':elapsed,'regions':regions,
                 'analysis_id':report['analysis_id'],'selected_all_for_measurement_only':reasons,
                 'baseline_schedule':original,'candidate_schedule':selected,
                 'changed_frames':sum(a!=b for a,b in zip(original,selected)),
                 'analytic_acceleration_variance_before':before,'analytic_acceleration_variance_after':after,
                 'endpoint_preserved':selected[0]==0 and selected[-1]==len(clip.frames)-1,
                 'protected_frames_preserved':selected[:11]==original[:11],
                 'monotonic':selected==sorted(selected),'output_frames':len(selected)}
            results.append(row)
            write_json(output/'baseline_results.json',results)
            print(split,case,len(regions),round(elapsed,3),flush=True)
    write_json(output/'fixtures_manifest.json',fixtures)
    write_json(output/'environment.json',{'platform':platform.platform(),'processor':platform.processor(),
        'logical_cpu_count':os.cpu_count(),'python':sys.version,'opencv':cv2.__version__,
        'numpy':np.__version__,'tools':diagnose(),'python_peak_rss_bytes':memory(),
        'rss_scope':'Python process high-water mark; excludes ffmpeg child processes and GPU.',
        'gpu':'Not used; CPU baseline','total_wall_seconds':time.perf_counter()-started,
        'baseline_hashes':source_hashes})
    real=Path('outputs/motion-review-63f72b9e/results/motion_report.json')
    if real.exists():
        data=json.loads(real.read_text(encoding='utf-8'))
        regions=[{'path':s['path'],'sha256':s['sha256'],'region':r,
                  'label':'unreviewed detector suspicion; NOT ground truth'}
                 for s in data['sources'] for r in s['regions']]
        # Spread samples over available clips rather than choose by measured quality.
        chosen=[regions[i] for i in np.linspace(0,len(regions)-1,min(5,len(regions)),dtype=int)] if regions else []
        write_json(output/'real_ship_regions.json',{'report_path':str(real.resolve()),'report_sha256':sha(real),
            'regions':chosen,'pending_categories':['person','landscape/camera','product/static','fast action'],
            'status':'Ship regions selected for visual labeling; no real footage quality claim'})


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=Path('outputs/motion-m0'))
    run(parser.parse_args().output)
