import unittest

import cv2
import numpy as np

from video_manager.errors import InputError
from video_manager.stabilization import GATES,apply_transform,plan_from_frames


class StabilizationTests(unittest.TestCase):
    def test_reconstruction_preserves_flat_field_and_integer_translation(self):
        rng=np.random.default_rng(714)
        frame=rng.integers(20,230,(30,48,3),dtype=np.uint8)
        translated=apply_transform(frame,[[1,0,1],[0,1,2]])
        np.testing.assert_array_equal(translated[2:,1:],frame[:-2,:-1])
        flat=np.full_like(frame,127)
        np.testing.assert_array_equal(apply_transform(flat,[[1.02,-.01,.3],[.01,1.02,-.4]]),flat)

    def fixture(self,count=60,kind='shake'):
        rng=np.random.default_rng(713)
        background=cv2.GaussianBlur(rng.integers(20,230,(180,320,3),dtype=np.uint8),(3,3),0)
        if kind in ('fast_texture','raw_noise'):
            detail=rng.integers(20,230,(180,320,3),dtype=np.uint8)
            # Continuous high-contrast texture (not independent Nyquist noise).
            background=(np.clip((cv2.GaussianBlur(detail,(3,3),0).astype(float)-125)*2+125,20,230).astype(np.uint8)
                        if kind=='fast_texture' else detail)
        times=np.arange(count)/20;frames=[];truth=[]
        for i in range(count):
            dx=2.5*np.sin(i*1.6);dy=1.7*np.cos(i*1.2);angle=.3*np.sin(i*1.5)
            if kind=='pan':dx=i*.5;dy=0;angle=0
            if kind in ('fast_texture','raw_noise'):dx=3.5*np.sin(i*1.6);dy=2.5*np.cos(i*1.4);angle=.15*np.sin(i*1.2)
            zoom=1+i*.002 if kind=='zoom' else 1
            matrix=cv2.getRotationMatrix2D((159.5,89.5),angle,zoom);matrix[:,2]+=[dx,dy]
            frames.append(cv2.warpAffine(background,matrix,(320,180),borderMode=cv2.BORDER_REFLECT))
            full=np.eye(3);full[:2]=matrix;truth.append(full)
        return frames,times,truth

    def test_known_shake_reduced_and_crop_bounded_with_exact_protection(self):
        frames,times,truth=self.fixture()
        plan=plan_from_frames(frames,times,protect_seconds=.5)
        self.assertTrue(plan['audit']['applied'],plan['audit'])
        self.assertLessEqual(plan['audit']['max_crop_fraction'],.05+1e-10)
        interior=[crop for t,crop in zip(times,plan['audit']['crop_fractions']) if .8<=t<=times[-1]-.3]
        self.assertLess(max(interior)-min(interior),1e-10,'Interior crop must not pump with camera shake')
        # Independently apply estimated correction to the known generating
        # camera trajectory, not to a second call of the motion estimator.
        center=np.array([159.5,89.5,1.]);before=[];after=[];angles_before=[];angles_after=[]
        for i,(frame,matrix) in enumerate(zip(frames,plan['transforms'])):
            full=np.eye(3);full[:2]=matrix
            before.append((truth[i]@center)[:2]);after.append((full@truth[i]@center)[:2])
            composed=full@truth[i]
            angles_before.append(np.arctan2(truth[i][1,0],truth[i][0,0]))
            angles_after.append(np.arctan2(composed[1,0],composed[0,0]))
            if times[i]<=.5 or i==len(times)-1:
                np.testing.assert_array_equal(apply_transform(frame,matrix),frame)
        before=np.array(before)[15:-4];after=np.array(after)[15:-4]
        gain=1-np.mean(np.diff(after,n=2,axis=0)**2)/np.mean(np.diff(before,n=2,axis=0)**2)
        self.assertGreaterEqual(gain,GATES['synthetic_acceleration_energy_reduction_min'])
        rotation_gain=1-np.mean(np.diff(angles_after[15:-4],n=2)**2)/np.mean(np.diff(angles_before[15:-4],n=2)**2)
        self.assertGreaterEqual(rotation_gain,GATES['synthetic_acceleration_energy_reduction_min'])
        transformed=apply_transform(frames[30],plan['transforms'][30])
        self.assertEqual(transformed.shape,frames[30].shape)
        self.assertFalse(np.any(np.all(transformed==0,axis=2)),'No new unfilled border pixels')

    def test_linear_pan_and_zoom_are_not_stabilized(self):
        frames,times,_=self.fixture(kind='pan')
        plan=plan_from_frames(frames,times)
        self.assertFalse(plan['audit']['applied'],plan['audit'])
        self.assertEqual(plan['audit']['reason'],'steady_pan_or_no_shake')
        frames,times,_=self.fixture(kind='zoom')
        plan=plan_from_frames(frames,times)
        self.assertFalse(plan['audit']['applied'])
        self.assertEqual(plan['audit']['reason'],'intentional_or_unknown_zoom')

    def test_cut_low_texture_and_zero_budget_abstain(self):
        frames,times,_=self.fixture()
        frames[30:]=[255-f for f in frames[30:]]
        cut_plan=plan_from_frames(frames,times)
        self.assertFalse(cut_plan['audit']['applied'])
        self.assertIn(cut_plan['audit']['reason'],('scene_cut','unreliable_camera_model'))
        frames=[np.full((90,160,3),100,np.uint8)]*12
        self.assertEqual(plan_from_frames(frames,np.arange(12)/20)['audit']['reason'],'unreliable_camera_model')
        frames,times,_=self.fixture()
        self.assertFalse(plan_from_frames(frames,times,crop_budget=0)['audit']['applied'])

    def test_scale_to_renderer_pixels_and_validation(self):
        frames,times,_=self.fixture(count=30)
        a=plan_from_frames(frames,times)
        b=plan_from_frames(frames,times,output_size=(640,360))
        self.assertTrue(b['audit']['applied'])
        self.assertEqual(b['audit']['output_size'],[640,360])
        # Rotation/scale stay comparable; center displacement doubles.
        ma=np.array(a['transforms'][15]);mb=np.array(b['transforms'][15])
        np.testing.assert_allclose(ma[:,:2],mb[:,:2],atol=.002)
        np.testing.assert_allclose(ma[:,2]*2,mb[:,2],atol=.1)
        with self.assertRaises(InputError):plan_from_frames(frames,times,crop_budget=.8)
        with self.assertRaises(InputError):plan_from_frames(frames,times[:-1])

    def test_high_texture_diagonal_motion_is_not_a_cut_and_keeps_detail(self):
        frames,times,truth=self.fixture(kind='fast_texture')
        plan=plan_from_frames(frames,times)
        self.assertTrue(plan['audit']['applied'],plan['audit'])
        before=[];after=[];sharpness=[];center=np.array([159.5,89.5,1.])
        for i in range(8,len(frames)-8):
            matrix=np.eye(3);matrix[:2]=plan['transforms'][i]
            before.append((truth[i]@center)[:2]);after.append((matrix@truth[i]@center)[:2])
            a=cv2.cvtColor(frames[i],cv2.COLOR_RGB2GRAY)[30:-30,30:-30]
            b=cv2.cvtColor(apply_transform(frames[i],matrix[:2]),cv2.COLOR_RGB2GRAY)[30:-30,30:-30]
            sharpness.append(cv2.Laplacian(b,cv2.CV_64F).var()/cv2.Laplacian(a,cv2.CV_64F).var())
        gain=1-np.mean(np.diff(after,n=2,axis=0)**2)/np.mean(np.diff(before,n=2,axis=0)**2)
        self.assertGreaterEqual(gain,.30)
        self.assertGreaterEqual(float(min(sharpness)),.8)


if __name__=='__main__':unittest.main()
