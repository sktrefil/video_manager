"""Independent compressed-velocity planning and optional UI import checks."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests/fixtures'))
from synthetic import make_motion_clip
from video_manager.retime import retime

class IndependentD(unittest.TestCase):
 def test_effective_velocity_reverses_source_speed_order(self):
  with tempfile.TemporaryDirectory() as temp:
   d=Path(temp)
   left=make_motion_clip(d/'slow.mp4',5,65,count=100,fps=20)
   right=make_motion_clip(d/'fast.mp4',65,125,count=40,fps=20)
   out=retime([str(left),str(right)],d/'job',targets=[2,2],protect=.5,local_speed=True,window=.8,strength=1)
   r=json.loads((out/'results/report.json').read_text());plan=r['decisions'][0]
   self.assertLess(r['source_measurements'][0]['before']['speed'],r['source_measurements'][0]['after']['speed'])
   velocity=plan['velocity_planning']
   self.assertGreater(velocity['effective_before'],velocity['effective_after'])
   self.assertLess(plan['left_alpha'],0)
   self.assertEqual(plan['side_results']['right'],'protected_interval_priority')
   self.assertEqual(plan['side_results']['left'],'candidate_requires_visual_review')
   self.assertEqual(r['timeline_validation']['decoded_frames'],80)
   for ci,item in enumerate(r['timeline']):
    rows=[row for row in r['corrected']['mapping'] if row['clip_id']==item['clip_id']]
    self.assertEqual([row['source_frame'] for row in rows[:11]],list(range(11)))
    self.assertEqual(rows[-1]['source_frame'],[99,39][ci])
    self.assertLessEqual(item['mapping']['conservative_composed_speed_bound'],12)

 def test_cli_core_does_not_import_qt(self):
  p=subprocess.run([sys.executable,'-c','import sys; from video_manager.cli import main; main(["doctor"]); assert not any(n.startswith("PySide6") for n in sys.modules)'],capture_output=True)
  self.assertEqual(p.returncode,0,p.stderr.decode())

if __name__=='__main__':unittest.main()
