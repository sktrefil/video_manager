"""A3 independent decoded-pixel and exclusion validation."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests/fixtures'))
from synthetic import make_motion_clip, make_sequence
from video_manager.boundary import analyze_boundaries, correction_schedules
from video_manager.probe import probe
from video_manager.render import frame_schedule


def frames(path,w=160,h=96):
    p=subprocess.run(['ffmpeg','-v','error','-i',str(path),'-fps_mode','passthrough','-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True,check=True)
    return np.frombuffer(p.stdout,np.uint8).reshape(-1,h,w,3)

def cli(paths,out,*options):
    subprocess.run([str(ROOT/'.venv/bin/video-manager'),'boundaries',*map(str,paths),'--output',str(out),*options],capture_output=True,check=True)
    return json.loads((out/'results/report.json').read_text())

class IndependentA3(unittest.TestCase):
    def test_speed_actual_pixels_and_disabled_precedence(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp)
            paths=[make_motion_clip(d/'fast.mp4',5,85),make_motion_clip(d/'slow.mp4',85,110),make_motion_clip(d/'reverse.mp4',110,20)]
            report=cli(paths,d/'job','--local-speed','--window','1','--strength','1')
            actual=frames(d/'job/results/corrected.mp4')
            source=[frames(p) for p in paths]
            mapping=report['corrected']['mapping']
            self.assertNotEqual([r['source_frame'] for r in mapping],[r['source_frame'] for r in report['baseline']['mapping']])
            for i,row in enumerate(mapping):
                ci=int(row['clip_id'].split('_')[1])-1
                mae=np.abs(actual[i].astype(float)-source[ci][row['source_frame']]).mean()
                self.assertLess(mae,4,(i,mae))
            for ci in range(3):
                selected=[r['source_frame'] for r in mapping if r['clip_id']==f'clip_{ci+1:02d}']
                self.assertEqual(selected,sorted(selected)); self.assertEqual((selected[0],selected[-1]),(0,39))
            clips=[probe(p,f'clip_{i+1:02d}') for i,p in enumerate(paths)]
            measurements=analyze_boundaries(clips,1)
            self.assertEqual(measurements[1]['reason'],'direction_conflict')
            defaults=[frame_schedule(c,clips[0].fps) for c in clips]
            for disabled_clips,disabled_boundaries in [([2],[]),([],[1,2]),([1],[2])]:
                schedules,decisions=correction_schedules(clips,measurements,window=1,strength=1,local_speed=True,remove_duplicates=True,
                    disabled_clips=disabled_clips,disabled_boundaries=disabled_boundaries)
                self.assertEqual(schedules,defaults)
                self.assertFalse(any(r['speed_applied'] or r['duplicate_removed'] for r in decisions))
            static=probe(make_motion_clip(d/'static.mp4',85,85),'static')
            measure=analyze_boundaries([clips[0],static],1)
            _,decision=correction_schedules([clips[0],static],measure,window=1,strength=1,local_speed=True,remove_duplicates=False)
            self.assertFalse(decision[0]['speed_applied'])

    def test_duplicate_and_comparison_pixels_share_clock_no_hold(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp); paths=make_sequence(d/'inputs',3)
            report=cli(paths,d/'job','--remove-duplicates','--window','2')
            corrected=report['corrected']; baseline=report['baseline']
            self.assertEqual(corrected['frame_count'],baseline['frame_count']-2)
            for ci in range(3):
                selected=[r['source_frame'] for r in corrected['mapping'] if r['clip_id']==f'clip_{ci+1:02d}']
                self.assertEqual(selected,list(range(0 if ci==0 else 1,10)))
            diagnostics={name:frames(d/'job/results'/f'{name}_diagnostic.mp4') for name in ['baseline','corrected']}
            outside_count=0
            for comp in report['comparisons']:
                rendered=frames(d/'job/results'/comp['video'],320,120)
                self.assertEqual(len(rendered),len(comp['mapping']))
                self.assertEqual(comp['mapping'][comp['boundary_frame_in_comparison']]['relative_seconds'],0)
                for index,row in enumerate(comp['mapping']):
                    for side,name in enumerate(['baseline','corrected']):
                        # Bottom interior avoids text and checks content, not merely mapping JSON.
                        patch=rendered[index,70:115,side*160+10:side*160+150]
                        if row[name] is None:
                            outside_count+=1; self.assertLess(float(patch.mean()),2)
                        else:
                            boundary=report[name]['boundaries'][comp['boundary']-1]['output_frame']
                            wanted=boundary+row['relative_frame']
                            self.assertEqual(row[name]['output_frame'],wanted)
                            expected=diagnostics[name][wanted,46:91,10:150]
                            self.assertLess(np.abs(patch.astype(float)-expected).mean(),4)
            self.assertGreater(outside_count,0)

if __name__=='__main__': unittest.main()
