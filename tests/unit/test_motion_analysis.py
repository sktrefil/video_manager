import unittest

import cv2
import numpy as np

from video_manager.motion_analysis import analysis_size, analyze_frames


class MotionAnalysisTests(unittest.TestCase):
    def test_aspect_ratio_and_anamorphic_display(self):
        self.assertEqual(analysis_size(1920,1080),(480,270))
        self.assertEqual(analysis_size(1080,1920),(270,480))
        self.assertEqual(analysis_size(720,576,sample_aspect_ratio=16/15),(480,360))

    def test_cuts_are_barriers_and_brightness_is_not_motion(self):
        rng=np.random.default_rng(123)
        a=rng.integers(20,150,(90,160),dtype=np.uint8)
        b=rng.integers(50,220,(90,160),dtype=np.uint8)
        frames=[a]*8+[b]*8
        report=analyze_frames(frames,np.arange(16)/20)
        self.assertIn(.4,report['diagnostics']['cuts'])
        self.assertFalse(any(r['start_seconds']<.4<r['end_seconds'] for r in report['regions']))
        report=analyze_frames([a,a+20,a+20],[0,.05,.1])
        self.assertEqual(report['pairs'][0]['abstain_reason'],'illumination_change')
        self.assertFalse(report['pairs'][0]['cut'])

    def test_camera_translation_separated_from_subject(self):
        rng=np.random.default_rng(124)
        background=cv2.GaussianBlur(rng.integers(20,130,(120,180),dtype=np.uint8),(3,3),0)
        frames=[cv2.warpAffine(background,np.float32([[1,0,i],[0,1,0]]),(180,120),
                    borderMode=cv2.BORDER_REFLECT) for i in range(12)]
        report=analyze_frames(frames,np.arange(12)/20)
        self.assertLess(abs(np.median([p['camera_dx'] for p in report['pairs']])-1),.2)
        self.assertLess(np.median([p['object_speed'] for p in report['pairs']]),1)
        self.assertEqual(report['regions'],[])

    def test_low_texture_and_incomplete_decode_abstain(self):
        frame=np.full((90,160),65,np.uint8)
        report=analyze_frames([frame]*6,np.arange(6)/20)
        self.assertEqual(report['diagnostics']['abstentions']['low_texture'],5)
        self.assertEqual(report['regions'],[])
        with self.assertRaises(ValueError): analyze_frames([frame],[0,.1])
        with self.assertRaises(ValueError): analyze_frames([frame,frame],[0,0])

    def test_subpixel_repeat_cadence_does_not_swallow_later_speed_jump(self):
        # Calibration-only regression: repeated pixel positions are normal at
        # <1px/frame. They must not merge a later jump into an opening hold.
        rng=np.random.default_rng(521)
        background=cv2.GaussianBlur(rng.integers(20,100,(90,240),dtype=np.uint8),(3,3),0)
        tile=rng.integers(120,240,(20,20),dtype=np.uint8)
        def frames(positions):
            for position in positions:
                frame=background.copy(); x=20+round(position)
                frame[30:50,x:x+20]=tile
                yield frame
        positions=[i*.15 if i<60 else 9+(i-60)*1.5 for i in range(100)]
        report=analyze_frames(frames(positions),np.arange(100)/20)
        changes=[r for r in report['regions'] if 'speed_change' in r['kinds']]
        self.assertTrue(changes)
        self.assertTrue(all(r['start_seconds']>.5 for r in changes))
        self.assertFalse(any('repeat_or_hold' in r['kinds'] for r in report['regions']))
        normal=analyze_frames(frames([i*.15 for i in range(100)]),np.arange(100)/20)
        self.assertEqual(normal['regions'],[])
        paused=[i*.15 if i<40 else 6 if i<64 else 6+(i-64)*.15 for i in range(100)]
        report=analyze_frames(frames(paused),np.arange(100)/20)
        self.assertTrue(any('repeat_or_hold' in r['kinds'] for r in report['regions']))
        self.assertTrue(all(r['ambiguous_hold_overlap'] for r in report['regions']))
        from fractions import Fraction
        from types import SimpleNamespace
        from video_manager.motion_optimizer import optimize_region
        from video_manager.time_map import build_map
        clip=SimpleNamespace(id='intentional_stop',duration=5,
            frames=[{'source_seconds':i/20} for i in range(100)])
        mapping=build_map(clip,3,.5,12,.5,60,Fraction(20))
        self.assertTrue(all(not optimize_region(mapping,r)['accepted'] for r in report['regions']))
        self.assertEqual(mapping.knot_warps,[])
        # Independent kinds remain independently actionable even if windows touch.
        self.assertTrue(all(len(r['kinds'])==1 for r in report['regions']))
        hold_then_jump=[i*.15 if i<30 else 4.5 if i<48 else 4.5+(i-48)*.15 if i<62
                        else 6.6+(i-62)*1.5 for i in range(100)]
        report=analyze_frames(frames(hold_then_jump),np.arange(100)/20)
        self.assertTrue(any(r['kinds']==['repeat_or_hold'] for r in report['regions']))
        self.assertTrue(any(r['kinds']==['speed_change'] and r['start_seconds']>.5 for r in report['regions']))
        self.assertTrue(all(len(r['kinds'])==1 for r in report['regions']))

    def test_small_subject_motion_overrides_low_whole_frame_difference(self):
        rng=np.random.default_rng(523)
        background=cv2.GaussianBlur(rng.integers(30,110,(270,480),dtype=np.uint8),(5,5),0)
        tile=rng.integers(120,240,(18,18),dtype=np.uint8)
        frames=[]
        for i in range(30):
            frame=background.copy();frame[100:118,30+i:48+i]=tile;frames.append(frame)
        report=analyze_frames(frames,np.arange(30)/20)
        self.assertTrue(all(p['mae']<.5 for p in report['pairs']))
        self.assertGreater(np.median([p['object_speed'] for p in report['pairs']]),10)
        self.assertFalse(any('repeat_or_hold' in r['kinds'] for r in report['regions']))

