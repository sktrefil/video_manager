"""Independent extension pixels, positive smooth curve, and compression regression."""
from fractions import Fraction
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
import numpy as np
from test_a3_independent import frames
from video_manager.errors import InputError
from video_manager.time_map import build_map,select_schedule,add_boundary_warp
from video_manager.retime import retime
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests/fixtures'))
from synthetic import make_motion_clip

class ExtensionIndependent(unittest.TestCase):
 def test_stretched_actual_pixels_protected_and_distributed(self):
  with tempfile.TemporaryDirectory() as tmp:
   d=Path(tmp);paths=[make_motion_clip(d/f'{i}.mp4',5,120,count=96,fps=24) for i in range(2)]
   out=retime([str(p) for p in paths],d/'out',targets=[5,5],protect=1,ramp=.5)
   r=json.loads((out/'results/report.json').read_text());decoded=frames(out/'results/corrected.mp4')
   self.assertEqual(len(decoded),240)
   self.assertAlmostEqual(r['timeline_validation']['measured_total_seconds'],10,places=5)
   for ci,p in enumerate(paths):
    source=frames(p);rows=r['corrected']['mapping'][ci*120:(ci+1)*120];ids=[x['source_frame'] for x in rows]
    self.assertEqual(ids[:25],list(range(25)));self.assertEqual(ids[-1],95);self.assertEqual(ids,sorted(ids))
    repeats=[i for i in range(1,120) if ids[i]==ids[i-1]]
    self.assertGreaterEqual(len(repeats),24);self.assertGreater(len(set(i//24 for i in repeats)),2)
    self.assertLessEqual(ids.count(95),2)
    for i,idx in enumerate(ids):self.assertLess(np.abs(decoded[ci*120+i].astype(float)-source[idx]).mean(),4)

 def test_curve_bound_infeasible_and_original_compression(self):
  clip=lambda n:SimpleNamespace(id='test',duration=n,frames=[{'source_seconds':i/24} for i in range(n*24)])
  m=build_map(clip(4),5,1,1,.5,120,Fraction(24))
  self.assertTrue(m.stretched);self.assertFalse(m.compressed);self.assertLess(m.peak,1)
  self.assertEqual(m.speed_bound(),1);self.assertAlmostEqual(m.source_time(m.output_end),95/24)
  speeds=[m.base_speed(float(t)) for t in np.linspace(0,m.output_end,1001)]
  self.assertGreater(min(speeds),0);self.assertEqual(speeds,sorted(speeds,reverse=True))
  self.assertAlmostEqual(m.base_speed(1+1e-6),1,places=9)
  self.assertEqual(add_boundary_warp(m,'tail',.5,.2),'composed_speed_limit')
  for protect,ramp in [(4,.5),(3.9,1),(1,5)]:
   with self.assertRaises(InputError):build_map(clip(4),5,protect,12,ramp,120,Fraction(24))
  with self.assertRaises(InputError):build_map(clip(4),5,1,12,.5,120,Fraction(24),enabled=False)
  c=build_map(clip(10),3,1,12,.5,72,Fraction(24))
  self.assertTrue(c.compressed);self.assertFalse(c.stretched)
  self.assertAlmostEqual(c.peak,1+7/((71/24-1)-.25))
  self.assertEqual(select_schedule(clip(10),c)[:25],list(range(25)))
  self.assertEqual(select_schedule(clip(10),c)[-1],239)

if __name__=='__main__':unittest.main()
