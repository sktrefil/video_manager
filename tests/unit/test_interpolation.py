from fractions import Fraction
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from video_manager.interpolation import CPUFlowInterpolator,create_backend
from video_manager.probe import probe
from video_manager.render import Encoder,decode_frames


class InterpolationTests(unittest.TestCase):
    def setUp(self):
        rng=np.random.default_rng(2026)
        self.left=cv2.GaussianBlur(rng.integers(20,230,(96,160,3),np.uint8),(5,5),.8)
        self.backend=CPUFlowInterpolator()

    def shifted(self,x,y=0):
        return cv2.warpAffine(self.left,np.float32([[1,0,x],[0,1,y]]),(160,96),borderMode=cv2.BORDER_REFLECT_101)

    def test_arbitrary_time_translation_improves_over_nearest_and_blending(self):
        right=self.shifted(4)
        roi=np.s_[12:-12,12:-12,:]
        for alpha in (.25,.5,.75):
            expected=self.shifted(4*alpha)
            actual,audit=self.backend.synthesize(self.left,right,alpha)
            nearest=self.left if alpha<=.5 else right
            blend=(1-alpha)*self.left.astype(float)+alpha*right
            error=float(np.mean(abs(actual[roi].astype(float)-expected[roi])))
            self.assertTrue(audit['applied'],audit)
            self.assertLess(error,.8*np.mean(abs(nearest[roi].astype(float)-expected[roi])))
            self.assertLess(error,.8*np.mean(abs(blend[roi]-expected[roi])))
            sharp=lambda a:float(cv2.Laplacian(cv2.cvtColor(a,cv2.COLOR_RGB2GRAY),cv2.CV_64F).var())
            self.assertGreater(sharp(actual[roi]),.9*sharp(expected[roi]))

    def test_decoded_translation_ground_truth(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'translation.mp4'
            encoder=Encoder(path,160,96,Fraction(20))
            for frame in (self.left,self.shifted(2),self.shifted(4)): encoder.write(frame.tobytes())
            encoder.close()
            clip=probe(path,'translation')
            left,expected,right=[np.frombuffer(raw,np.uint8).reshape(96,160,3) for raw in decode_frames(clip,160,96)]
            actual,audit=self.backend.synthesize(left,right,.5)
            region=np.s_[12:-12,12:-12,:]
            error=lambda a:float(np.mean(abs(a[region].astype(float)-expected[region])))
            self.assertTrue(audit['applied'],audit)
            self.assertLess(error(actual),.75*error(left))
            self.assertLess(error(actual),12)

    def test_occlusion_exposure_cut_and_lowtexture_fallback_exactly(self):
        occluded=self.shifted(4);occluded[28:62,55:95]=0
        cases=[occluded,np.clip(self.left.astype(int)+18,0,255).astype(np.uint8),255-self.left,
               np.full_like(self.left,100)]
        for right in cases:
            for alpha in (.25,.75):
                actual,audit=self.backend.synthesize(self.left,right,alpha)
                self.assertFalse(audit['applied'],audit)
                self.assertTrue(np.array_equal(actual,self.left if alpha<=.5 else right))

    def test_endpoints_input_validation_and_backend_failure(self):
        right=self.shifted(4)
        for alpha,expected in ((0,self.left),(1,right)):
            actual,audit=self.backend.synthesize(self.left,right,alpha)
            self.assertTrue(np.array_equal(actual,expected));self.assertFalse(audit['applied'])
        for alpha in (-.1,1.1,float('nan'),True):
            with self.assertRaises(ValueError):self.backend.synthesize(self.left,right,alpha)
        with self.assertRaises(ValueError):self.backend.synthesize(self.left.astype(float),right,.5)
        with self.assertRaises(ValueError):self.backend.synthesize(self.left,right[:30],.5)
        with self.assertRaises(ValueError):create_backend('rife')
        with patch('video_manager.interpolation.cv2.calcOpticalFlowFarneback',side_effect=cv2.error('failed')):
            actual,audit=self.backend.synthesize(self.left,right,.5)
        self.assertEqual(audit['reason'],'backend_error');self.assertTrue(np.array_equal(actual,self.left))
        # Cached pair bypasses preparation and fails specifically in synthesis.
        self.backend.synthesize(self.left,right,.25)
        with patch('video_manager.interpolation.cv2.remap',side_effect=cv2.error('warp failed')):
            actual,audit=self.backend.synthesize(self.left,right,.75)
        self.assertEqual(audit['reason'],'backend_error');self.assertTrue(np.array_equal(actual,right))

    def test_single_pair_cache_is_content_bound_and_does_not_modify_inputs(self):
        right=self.shifted(4);original_left=self.left.copy();original_right=right.copy()
        self.backend.synthesize(self.left,right,.25)
        with patch.object(self.backend,'_prepare',wraps=self.backend._prepare) as prepare:
            self.backend.synthesize(self.left,right,.75)
            self.assertEqual(prepare.call_count,0)
            right[:]=255-right
            self.backend.synthesize(self.left,right,.75)
            self.assertEqual(prepare.call_count,1)
        self.assertTrue(np.array_equal(self.left,original_left))
        self.assertTrue(np.array_equal(original_right,self.shifted(4)))

    def test_subpixel_image_resampling_and_single_pass_affine_composition(self):
        rng=np.random.default_rng(701)
        base=cv2.GaussianBlur(rng.integers(20,235,(120,192,3),np.uint8),(3,3),.6)
        def move(frame,x):
            return cv2.warpAffine(frame,np.float32([[1,0,x],[0,1,0]]),(192,120),
                flags=cv2.INTER_LANCZOS4,borderMode=cv2.BORDER_REFLECT_101)
        region=np.s_[16:-16,16:-16,:]
        sharp=lambda frame:float(cv2.Laplacian(cv2.cvtColor(frame[region],cv2.COLOR_RGB2GRAY),cv2.CV_64F).var())
        transforms=(np.float32([[1,0,.35],[0,1,0]]),np.float32([[1,0,-.2],[0,1,0]]))
        for dx in (1.,2.5):
            right=move(base,dx)
            for alpha in (.3,.5):
                for composed in (False,True):
                    if composed:
                        left_s=move(base,.35);right_s=move(right,-.2)
                        actual,audit=self.backend.synthesize(left_s,right_s,alpha,
                            source_frames=(base,right),source_transforms=transforms)
                        expected=move(base,.35+(dx-.55)*alpha)
                    else:
                        actual,audit=self.backend.synthesize(base,right,alpha)
                        expected=move(base,dx*alpha)
                    self.assertTrue(audit['applied'],audit)
                    self.assertEqual(audit['single_pass_composition'],composed)
                    self.assertEqual(audit['source_resample_passes'],1)
                    self.assertGreaterEqual(sharp(actual)/sharp(expected),.8)
                    self.assertLessEqual(sharp(actual)/sharp(expected),1.25)
                    self.assertLess(np.mean(abs(actual[region].astype(float)-expected[region])),3)

    def test_composed_validation_endpoints_and_uncertain_fallback_use_stabilized_inputs(self):
        right=self.shifted(4);identity=[[1,0,0],[0,1,0]]
        with self.assertRaises(ValueError):
            self.backend.synthesize(self.left,right,.5,source_frames=(self.left,right))
        with self.assertRaises(ValueError):
            self.backend.synthesize(self.left,right,.5,source_frames=(self.left,right),
                                    source_transforms=(identity,[[0,0,0],[0,0,0]]))
        stabilized=self.shifted(.5)
        actual,audit=self.backend.synthesize(stabilized,right,0,source_frames=(self.left,right),
                                             source_transforms=(identity,identity))
        self.assertTrue(np.array_equal(actual,stabilized));self.assertFalse(audit['applied'])
        cut=255-right
        actual,audit=self.backend.synthesize(stabilized,cut,.25,source_frames=(self.left,right),
                                             source_transforms=(identity,identity))
        self.assertFalse(audit['applied']);self.assertTrue(np.array_equal(actual,stabilized))

    def test_reference_switch_alpha_sweep_keeps_position_and_truth_error_bounded(self):
        rng=np.random.default_rng(705)
        base=cv2.GaussianBlur(rng.integers(20,235,(120,192,3),np.uint8),(3,3),.6)
        def moved(x):
            return cv2.warpAffine(base,np.float32([[1,0,x],[0,1,0]]),(192,120),
                flags=cv2.INTER_LANCZOS4,borderMode=cv2.BORDER_REFLECT_101)
        right=moved(2.5);near_switch={}
        for alpha in sorted(set(np.linspace(0,1,21).tolist()+[.499,.501])):
            actual,audit=self.backend.synthesize(base,right,alpha)
            truth=moved(2.5*alpha)
            self.assertLess(np.mean(abs(actual[16:-16,16:-16].astype(float)-truth[16:-16,16:-16])),12)
            if 0<alpha<1:self.assertTrue(audit['applied'],audit)
            if alpha in (.499,.501):near_switch[alpha]=actual[16:-16,16:-16]
        first=cv2.cvtColor(near_switch[.499],cv2.COLOR_RGB2GRAY).astype(np.float32)
        second=cv2.cvtColor(near_switch[.501],cv2.COLOR_RGB2GRAY).astype(np.float32)
        displacement,confidence=cv2.phaseCorrelate(first,second)
        self.assertGreater(confidence,.8)
        self.assertLess(np.linalg.norm(np.array(displacement)-[2.5*.002,0]),.5)
