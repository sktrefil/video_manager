"""Independent protected timing, actual pixels, and final frame-budget checks."""
from fractions import Fraction
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
import numpy as np
from video_manager.errors import InputError
from video_manager.time_map import allocate_frames,build_map,add_boundary_warp
from test_a3_independent import frames
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests/fixtures'))
from synthetic import make_motion_clip

class IndependentB1(unittest.TestCase):
 def test_cli_eleven_eight_actual_protection_and_endpoints(self):
  with tempfile.TemporaryDirectory() as temp:
   d=Path(temp);sources=[make_motion_clip(d/f'{i}.mp4',5,110,count=n,fps=20) for i,n in enumerate([200,80,200])]
   for name,inputs,targets in [('eleven',sources,[3,4,4]),('eight',[sources[0],sources[2]],[4,4])]:
    out=d/name
    subprocess.run([str(ROOT/'.venv/bin/video-manager'),'retime',*map(str,inputs),'--output',str(out),'--targets',*map(str,targets),'--protect','1'],capture_output=True,check=True)
    r=json.loads((out/'results/report.json').read_text())
    actual=frames(out/'results/corrected.mp4')
    self.assertEqual(len(actual),20*sum(targets))
    info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_frames','-select_streams','v:0','-show_entries','frame=best_effort_timestamp_time','-of','json',str(out/'results/corrected.mp4')]))
    self.assertTrue(all(abs(float(f['best_effort_timestamp_time'])-i/20)<1e-6 for i,f in enumerate(info['frames'])))
    for ci,item in enumerate(r['timeline']):
     original=frames(inputs[ci]);start=item['start_frame'];end=item['end_frame']
     self.assertEqual(end-start,targets[ci]*20)
     # All protected frames plus real last source frame, after compression.
     for offset in list(range(21))+[end-start-1]:
      expected=offset if offset<=20 else len(original)-1
      row=r['corrected']['mapping'][start+offset]
      self.assertEqual(row['source_frame'],expected)
      self.assertLess(np.abs(actual[start+offset].astype(float)-original[expected]).mean(),4)
     m=item['mapping'];self.assertLessEqual(m['conservative_composed_speed_bound'],m['max_speed'])

 def test_curve_finite_constraints_joint_budget_and_composition(self):
  c=SimpleNamespace(id='c',duration=10,frames=[{'source_seconds':i/24} for i in range(240)])
  m=build_map(c,3,1,12,.5,72,Fraction(24))
  self.assertAlmostEqual(m.base_speed(1),1)
  self.assertLess(abs(m.base_speed(1+1e-6)-m.base_speed(1)),1e-8)
  self.assertAlmostEqual(m.source_time(m.output_end),239/24)
  self.assertEqual(add_boundary_warp(m,'head',.5,.3),'protected_interval_priority')
  self.assertEqual(add_boundary_warp(m,'tail',.5,.2),'candidate_requires_visual_review')
  ts=np.linspace(0,m.output_end,20001);ys=np.array([m.source_time(float(t)) for t in ts]);speed=np.diff(ys)/np.diff(ts)
  self.assertGreater(speed.min(),0);self.assertLessEqual(speed.max(),m.speed_bound()+1e-5)
  tight=build_map(c,3,1,12,.5,72,Fraction(24));tight.max_speed=tight.peak
  self.assertEqual(add_boundary_warp(tight,'tail',.5,.2),'composed_speed_limit')
  for n in [3,10,101]:
   targets=[1.013]*n;counts=allocate_frames(targets,Fraction(24))
   self.assertEqual(sum(counts),round(sum(Fraction(str(t))*24 for t in targets)))
   self.assertLessEqual(abs(sum(counts)/24-sum(targets)),1/24)
   self.assertTrue(all(abs(x/24-1.013)<=1/24 for x in counts))
  for bad in [True,'3',None,float('nan'),float('inf'),-1,0]:
   with self.assertRaises(InputError):allocate_frames([bad],Fraction(24))
  for target,protect,limit,ramp,enabled in [(3,3,12,.5,True),(3,1,2,.5,True),(3,1,12,3,True),(10,11,12,.5,False),(3,1,12,.5,False)]:
   with self.assertRaises(InputError):build_map(c,target,protect,limit,ramp,72,Fraction(24),enabled=enabled)

if __name__=='__main__':unittest.main()
