from fractions import Fraction
from types import SimpleNamespace
import unittest

from video_manager.errors import InputError
from video_manager.time_map import add_boundary_warp, allocate_frames, build_map, select_schedule


def clip(duration=10,fps=20):
    return SimpleNamespace(id='test',duration=duration,frames=[{'source_seconds':i/fps} for i in range(round(duration*fps))])


class TimeMapTests(unittest.TestCase):
    def test_smooth_protected_curve_endpoints_and_speed(self):
        c=clip()
        m=build_map(c,4,2,8,.5,80,Fraction(20))
        self.assertAlmostEqual(m.source_time(0),0)
        self.assertAlmostEqual(m.source_time(m.output_end),c.frames[-1]['source_seconds'])
        self.assertEqual(m.source_time(1.5),1.5)
        self.assertAlmostEqual(m.base_speed(2),1)
        self.assertLess(abs(m.base_speed(2+1e-6)-m.base_speed(2-1e-6)),1e-8)
        self.assertLessEqual(m.peak,8)
        samples=[m.source_time(i*m.output_end/1000) for i in range(1001)]
        self.assertEqual(samples,sorted(samples))
        schedule=select_schedule(c,m)
        self.assertEqual(schedule[:41],list(range(41)))
        self.assertEqual(schedule[-1],199)

    def test_total_budget_does_not_accumulate_rounding(self):
        targets=[1.01]*10
        counts=allocate_frames(targets,Fraction(24))
        self.assertEqual(sum(counts),round(10.1*24))
        self.assertTrue(all(abs(n/24-1.01)<1/24 for n in counts))
        self.assertEqual(allocate_frames([3,4,4],Fraction(24)),[72,96,96])
        self.assertEqual(allocate_frames([4,4],Fraction(24)),[96,96])

    def test_invalid_constraints(self):
        c=clip()
        for kwargs in [dict(target=4,protect=4,max_speed=12,ramp=.5),
                       dict(target=4,protect=2,max_speed=2,ramp=.5),
                       dict(target=11,protect=1,max_speed=12,ramp=.5),
                       dict(target=4,protect=3.8,max_speed=12,ramp=.5),
                       dict(target=4,protect=-1,max_speed=12,ramp=.5),
                       dict(target=4,protect=1,max_speed=True,ramp=.5)]:
            with self.assertRaises(InputError):
                build_map(c,count=80,fps=Fraction(20),**kwargs)
        for bad in [True,float('nan'),float('inf'),0,-1]:
            with self.assertRaises(InputError):
                allocate_frames([bad],Fraction(20))
        with self.assertRaises(InputError):
            build_map(c,4,1,12,.5,80,Fraction(20),enabled=False)

    def test_identity_and_composed_warp_constraints(self):
        c=clip(4)
        with self.assertRaises(InputError):
            build_map(c,4,5,12,.5,80,Fraction(20),enabled=False)
        m=build_map(c,4,1,12,.5,80,Fraction(20),enabled=False)
        self.assertFalse(m.compressed)
        self.assertEqual(select_schedule(c,m),list(range(80)))
        self.assertEqual(add_boundary_warp(m,'head',.5,.3),'protected_interval_priority')
        self.assertEqual(add_boundary_warp(m,'tail',.5,.3),'candidate_requires_visual_review')
        self.assertEqual(m.source_time(.5),.5)
        limited=build_map(clip(),4,2,4.6,.5,80,Fraction(20))
        self.assertEqual(add_boundary_warp(limited,'tail',.5,.5),'composed_speed_limit')


if __name__=='__main__':
    unittest.main()
