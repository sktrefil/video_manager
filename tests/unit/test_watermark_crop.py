import unittest

import numpy as np

from video_manager.enhancements import normalize_enhancements
from video_manager.errors import InputError
from video_manager.watermark_crop import DEFAULT_REGIONS, apply_crop, plan_crop


class WatermarkCropTests(unittest.TestCase):
    def assert_no_logo_intersection(self, plan):
        x,y,w,h=plan['rect']
        for x0,y0,x1,y1 in plan['excluded_boxes']:
            self.assertFalse(x<x1 and x+w>x0 and y<y1 and y+h>y0)

    def test_both_logos_removed_with_more_scene_than_old_fixed_crop(self):
        plan=plan_crop(1344,768)
        self.assert_no_logo_intersection(plan)
        self.assertGreater(plan['retained_area_fraction'],.75)
        self.assertLess(plan['zoom'],1.15)
        x,y,w,h=plan['rect']
        self.assertLessEqual(abs(w/1344-h/768),1/768)

    def test_actual_lower_logo_annotation_retains_more_of_the_scene(self):
        both=plan_crop(1344,768)
        actual=plan_crop(1344,768,[DEFAULT_REGIONS[1]])
        self.assertGreater(actual['retained_area_fraction'],both['retained_area_fraction'])
        self.assert_no_logo_intersection(actual)

    def test_region_disappears_from_pixels_without_inpainting(self):
        frame=np.full((180,320,3),30,np.uint8)
        for x,y,w,h in DEFAULT_REGIONS:
            frame[int(y*180):int((y+h)*180)+1,int(x*320):int((x+w)*320)+1]=(255,0,0)
        result=apply_crop(frame,plan_crop(320,180))
        self.assertEqual(result.shape,frame.shape)
        self.assertTrue(np.all(result==30))

    def test_stabilization_motion_is_included_in_fixed_crop(self):
        transforms=[[[1,0,0],[0,1,0]],[[1,0,-80],[0,1,-50]],[[1,0,20],[0,1,10]]]
        plan=plan_crop(1344,768,transforms=transforms)
        self.assert_no_logo_intersection(plan)
        self.assertTrue(plan['stabilization_envelope'])
        self.assertLess(plan['retained_area_fraction'],plan_crop(1344,768)['retained_area_fraction'])
        self.assertLess(plan['excluded_boxes'][0][0],plan_crop(1344,768)['excluded_boxes'][0][0])

    def test_no_regions_preserves_every_pixel(self):
        frame=np.random.default_rng(1).integers(0,256,(180,320,3),dtype=np.uint8)
        self.assertTrue(np.array_equal(frame,apply_crop(frame,plan_crop(320,180,[]))))

    def test_central_region_and_portrait_canvas(self):
        plan=plan_crop(180,320,[[.45,.45,.10,.10]])
        self.assert_no_logo_intersection(plan)

    def test_invalid_and_impossible_regions_are_rejected(self):
        for regions in ([[0,0,1,1]],[[.9,.9,.2,.2]],[[float('nan'),0,.1,.1]],[[True,0,.1,.1]]):
            with self.assertRaises(InputError):plan_crop(320,180,regions)

    def test_options_roundtrip_preserves_annotations(self):
        original={'watermark':{'enabled':True,'profile':'both','regions':[[.8,.9,.15,.06]]}}
        normalized=normalize_enhancements(original)
        self.assertEqual(normalized,normalize_enhancements(normalized))
        self.assertEqual(original['watermark']['regions'],normalized['watermark']['regions'])


if __name__=='__main__':unittest.main()
