import copy
from fractions import Fraction
from types import SimpleNamespace
import unittest

import numpy as np

from video_manager.motion_optimizer import optimize_region, _score
from video_manager.time_map import build_map


class MotionOptimizerTests(unittest.TestCase):
    def inputs(self,target=2.5):
        times=np.arange(80)/20
        positions=np.round(np.where(np.arange(80)<40,.3*np.arange(80),12+2*(np.arange(80)-40)))
        speeds=np.diff(positions)*20
        clip=SimpleNamespace(id='synthetic',duration=4,frames=[{'source_seconds':float(t)} for t in times])
        mapping=build_map(clip,target,0,12,.5,round(target*20),Fraction(20))
        region=dict(start_seconds=1.4,end_seconds=2.4,confidence=1.,fully_static=False,
            motion_samples=[dict(seconds=float(t),speed=float(v),confidence=1.)
                            for t,v in zip(times[1:],speeds) if 1.4<t<=2.4],
            context_motion_samples=[dict(seconds=float(t),speed=float(v),confidence=1.,dt=.05)
                                    for t,v in zip(times[1:],speeds)],
            source_frame_times=times.tolist())
        return mapping,region

    def test_compression_candidate_measured_improvement_preserves_constraints(self):
        mapping,region=self.inputs()
        result=optimize_region(mapping,region)
        self.assertTrue(result['accepted'],result)
        self.assertGreaterEqual(result['metrics']['acceleration_variance_reduction'],.1)
        self.assertEqual(mapping.knot_warps,[])
        modified=copy.deepcopy(mapping); modified.knot_warps.append(result['knots'])
        self.assertLessEqual(modified.speed_bound(),mapping.max_speed)
        values=[modified.source_time(t) for t in np.linspace(0,mapping.output_end,500)]
        self.assertTrue(np.all(np.diff(values)>=0))
        self.assertEqual(values[0],0)
        self.assertAlmostEqual(values[-1],mapping.source_end)
        self.assertEqual(result['knots'][0],[1.4,1.4])
        self.assertEqual(result['knots'][-1],[2.4,2.4])

    def test_unhelpful_and_protected_candidates_leave_map_unchanged(self):
        mapping,region=self.inputs(4)
        self.assertFalse(optimize_region(mapping,region)['accepted'])
        mapping.protect=1.5
        self.assertEqual(optimize_region(mapping,region)['reason'],'protected_interval_priority')
        mapping.protect=0
        region['confidence']=.1
        self.assertEqual(optimize_region(mapping,region)['reason'],'low_tracking_confidence')
        region['confidence']=1
        for sample in region['motion_samples']: sample['speed']=20.
        self.assertEqual(optimize_region(mapping,region)['reason'],'steady_motion_no_correction')
        self.assertEqual(mapping.knot_warps,[])

    def test_ambiguous_hold_is_diagnostic_even_when_combined_with_speed_change(self):
        mapping,region=self.inputs()
        self.assertTrue(optimize_region(mapping,region)['accepted'])
        before=copy.deepcopy(mapping)
        for kinds in (['repeat_or_hold'],['repeat_or_hold','speed_change']):
            region['kinds']=kinds
            result=optimize_region(mapping,region)
            self.assertFalse(result['accepted'])
            self.assertEqual(result['reason'],'ambiguous_hold_intent')
            self.assertEqual(mapping,before)
        region['kinds']=['speed_change'];region['ambiguous_hold_overlap']=True
        self.assertEqual(optimize_region(mapping,region)['reason'],'ambiguous_hold_intent')
        self.assertEqual(mapping,before)

    def test_full_context_required_and_constant_motion_has_no_false_boundary_acceleration(self):
        times=np.arange(80)/20
        metric=_score(times[20:50],times,np.full(80,20.),20.)
        self.assertAlmostEqual(metric['acceleration_variance'],0.,places=8)
        mapping,region=self.inputs()
        del region['context_motion_samples']
        self.assertEqual(optimize_region(mapping,region)['reason'],'missing_full_motion_context')
        self.assertEqual(mapping.knot_warps,[])

    def test_interval_end_displacement_matches_discrete_source_positions(self):
        times=np.arange(80)/20
        positions=np.round(np.where(np.arange(80)<40,.3*np.arange(80),12+2*(np.arange(80)-40)))
        speeds=np.r_[0,np.diff(positions)*20]
        selected=np.array([0,1,3,5,7,10,15,20,25,30,35,40,43,46,50,55,60,65,70,75,79])
        measured=_score(times[selected],times,speeds,20)
        expected=float(np.var(np.diff(positions[selected],n=2)*20**2))
        self.assertAlmostEqual(measured['acceleration_variance'],expected,places=6)
        self.assertAlmostEqual(measured['movement_extent'],positions[-1]-positions[0],places=6)
