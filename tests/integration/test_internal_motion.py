import copy
from fractions import Fraction
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fixtures'))
from synthetic import make_motion_clip,make_positions_clip
from video_manager.errors import InputError
from video_manager.internal_motion import (analyze_sources,apply_region,digest,inspect_motion,
                                           load_selections,region_id)
from video_manager.probe import probe
from video_manager.render import decode_frames
from video_manager.report import write_report
from video_manager.retime import retime
from video_manager.time_map import build_map,select_schedule


class InternalMotionTests(unittest.TestCase):
    def make_inputs(self,root):
        pause=make_positions_clip(root/'pause.mp4',list(range(5,45))+[45]*20+list(range(45,105)))
        steady=make_motion_clip(root/'steady.mp4',5,125,count=120)
        return pause,steady

    def test_detection_steady_pause_speed_change_and_static(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);pause,steady=self.make_inputs(root)
            speed=make_positions_clip(root/'speed.mp4',[5+i*.3 for i in range(60)]+[23+i*1.5 for i in range(60)])
            static=make_positions_clip(root/'static.mp4',[30]*80)
            clips=[probe(p,str(i)) for i,p in enumerate([steady,pause,speed,static])]
            report=analyze_sources(clips)
            self.assertEqual(report['sources'][0]['regions'],[])
            self.assertTrue(any('repeat_or_hold' in r['kinds'] for r in report['sources'][1]['regions']))
            self.assertTrue(any('speed_change' in r['kinds'] for r in report['sources'][2]['regions']))
            self.assertTrue(report['sources'][3]['regions'][0]['fully_static'])
            self.assertEqual(report['analysis_id'],analyze_sources(clips)['analysis_id'])
            region=report['sources'][1]['regions'][0]
            m=build_map(clips[1],4,2.5,12,.5,80,Fraction(20))
            original=select_schedule(clips[1],m)
            self.assertEqual(apply_region(m,region),'protected_interval_priority')
            self.assertEqual(original,select_schedule(clips[1],m))
            m=build_map(clips[3],4,1,12,.5,80,Fraction(20))
            self.assertEqual(apply_region(m,report['sources'][3]['regions'][0]),'fully_static_no_new_motion')

    def test_previews_explicit_selection_no_default_and_fixed_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);pause,steady=self.make_inputs(root)
            inspection=inspect_motion([str(pause),str(steady)],str(root/'inspect'))
            report_path=inspection/'results/motion_report.json'
            report=json.loads(report_path.read_text())
            region=report['sources'][0]['regions'][0]['id']
            self.assertEqual(report['default_selected'],[])
            self.assertFalse(report['previews'][0]['selected_for_final'])
            self.assertGreater(report['previews'][0]['changed_source_selections'],0)
            comp=report['previews'][0]['comparison']
            video=probe(inspection/'results'/comp['video'],'comparison')
            self.assertEqual(len(video.frames),len(comp['mapping']))
            for row in comp['mapping']:
                if row['original'] and row['proposal']:
                    self.assertEqual(row['original']['output_frame'],row['proposal']['output_frame'])
            off=retime([str(pause),str(steady)],str(root/'off'),targets=[4,4],motion_reports=[report_path])
            on=retime([str(pause),str(steady)],str(root/'on'),targets=[4,4],motion_reports=[report_path],selected_regions=[region])
            a=json.loads((off/'results/report.json').read_text());b=json.loads((on/'results/report.json').read_text())
            self.assertTrue(all(not d['applied'] for d in a['internal_motion']['decisions']))
            selected=next(d for d in b['internal_motion']['decisions'] if d['region_id']==region)
            self.assertTrue(selected['applied']);self.assertGreater(selected['changed_source_selections'],0)
            self.assertEqual(a['corrected']['frame_count'],b['corrected']['frame_count'])
            self.assertAlmostEqual(b['timeline_validation']['measured_total_seconds'],8)
            for left,right in zip(a['corrected']['mapping'],b['corrected']['mapping']):
                if left['clip_id']=='clip_02' or left['output_seconds']<=1:
                    self.assertEqual(left,right)
            left=list(decode_frames(probe(off/'results/corrected.mp4','a'),160,96))
            right=list(decode_frames(probe(on/'results/corrected.mp4','b'),160,96))
            self.assertTrue(any(x!=y for x,y in zip(left,right)))
            self.assertEqual(b['corrected']['mapping'][0]['source_frame'],0)
            self.assertEqual(b['corrected']['mapping'][79]['source_frame'],119)
            clips=[probe(p,str(i)) for i,p in enumerate([pause,steady])]
            _,chosen=load_selections([report_path],clips,[region],[region])
            self.assertEqual(chosen,[])

    def test_stale_unknown_tampered_and_overlap_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);pause,steady=self.make_inputs(root)
            clips=[probe(p,str(i)) for i,p in enumerate([pause,steady])]
            report=analyze_sources(clips);path=root/'report.json';write_report(path,report)
            region=report['sources'][0]['regions'][0]['id']
            with self.assertRaises(InputError):
                load_selections([path],clips,['unknown'],[])
            tampered=copy.deepcopy(report);tampered['options']['window_seconds']=.5
            altered=root/'altered.json';write_report(altered,tampered)
            with self.assertRaises(InputError):
                load_selections([altered],clips,[region],[])
            overlap=copy.deepcopy(report)
            other=copy.deepcopy(overlap['sources'][0]['regions'][0]);other['end_seconds']-=.1
            other['id']=region_id(overlap['sources'][0]['sha256'],overlap['options'],other)
            overlap['sources'][0]['regions'].append(other)
            overlap['analysis_id']=digest({k:overlap[k] for k in ['version','options','sources']})
            path2=root/'overlap.json';write_report(path2,overlap)
            with self.assertRaises(InputError):
                load_selections([path2],clips,[region,other['id']],[])
            with pause.open('ab') as stream:
                stream.write(b'changed')
            with self.assertRaises(InputError):
                load_selections([path],clips,[region],[])


if __name__=='__main__':
    unittest.main()
