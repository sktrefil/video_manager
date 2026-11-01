"""Public report/loading and mapping contracts for M1-M3."""
import copy
from fractions import Fraction
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fixtures'))
from synthetic import make_positions_clip
from motion_benchmark import make_fixture
from video_manager.errors import InputError
from video_manager.internal_motion import (ANALYZER, VERSION, analyze_sources, apply_region,
    digest, load_selections, region_id, report_payload)
from video_manager.probe import probe
from video_manager.retime import retime
from video_manager.time_map import build_map, select_schedule


class MotionV2Contracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        path=make_positions_clip(cls.root/'한글 pause.mp4',list(range(5,45))+[45]*20+list(range(45,105)))
        cls.clip=probe(path,'pause')

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def save(self,report,name='report.json'):
        path=self.root/name;path.write_text(json.dumps(report),encoding='utf-8');return path

    def measured_report(self):
        report=analyze_sources([self.clip])
        context=[{key:pair[key] for key in ('seconds','speed','confidence','dt')}
                 for pair in report['sources'][0]['motion_components']]
        # Well-formed synthetic measured profile used to test parsing independently
        # of whether this particular detector elects to abstain on the input.
        region={'analysis_version':ANALYZER,'start_seconds':1.,'end_seconds':3.,
            'first_frame':20,'last_frame':60,
            'confidence':.9,'fully_static':False,'review_reason':'intent_unknown',
            'kinds':['speed_change'],'proposal_kind':'optimized','proposal_amount':0.,
            'motion_samples':[copy.deepcopy(pair) for pair in context if 1.<=pair['seconds']<=3.],
            'context_motion_samples':context,
            'source_frame_times':[f['source_seconds'] for f in self.clip.frames]}
        report['sources'][0]['regions']=[region]
        return self.resign(report)

    def resign(self,report):
        for source in report['sources']:
            for region in source['regions']:
                region['id']=region_id(source['sha256'],report['options'],region,report['version'])
        report['analysis_id']=digest(report_payload(report));return report

    def test_legacy_report_and_exclusion_precedence(self):
        report=analyze_sources([self.clip],version='motion-v1')
        self.assertEqual(report['version'],'motion-v1')
        self.assertNotIn('analyzer',report)
        identifier=report['sources'][0]['regions'][0]['id']
        catalog,chosen=load_selections([self.save(report)],[self.clip],[identifier],[identifier])
        self.assertIn(identifier,catalog);self.assertEqual(chosen,[])
        self.assertEqual(len(load_selections([self.save(report)],[self.clip],[identifier],[])[1]),1)

    def test_existing_real_legacy_report_loads_without_mutation(self):
        path=Path('outputs/motion-review-63f72b9e/results/motion_report.json')
        if not path.exists(): self.skipTest('Local historical report not bundled')
        before=path.read_bytes()
        catalog,selected=load_selections([path],[],[],[])
        self.assertGreater(len(catalog),0);self.assertEqual(selected,[])
        self.assertEqual(before,path.read_bytes())

    def test_v2_integrity_analyzer_version_and_input_binding(self):
        report=self.measured_report();path=self.save(report)
        self.assertEqual(report['version'],VERSION)
        self.assertEqual(len(load_selections([path],[self.clip],[],[])[0]),1)
        identifier=report['sources'][0]['regions'][0]['id']
        self.assertEqual(len(load_selections([path],[self.clip],[identifier],[])[1]),1)
        self.assertEqual(load_selections([path],[self.clip],[identifier],[identifier])[1],[])
        for mutation in ('digest','version','analyzer','source'):
            bad=copy.deepcopy(report)
            if mutation=='digest': bad['analysis_id']='0'*64
            elif mutation=='version': bad['version']='future'
            elif mutation=='analyzer': bad['analyzer']='unknown';self.resign(bad)
            else: bad['sources'][0]['sha256']='0'*64;self.resign(bad)
            with self.subTest(mutation=mutation),self.assertRaises(InputError):
                load_selections([self.save(bad)],[self.clip],[],[])

    def test_resigned_malformed_samples_and_cut_crossing_rejected(self):
        report=self.measured_report()
        for mutation in ('negative','duplicate','outside','confidence','cut','missing_first_frame','frame_grid',
                         'absent_context','shifted_context_dt'):
            bad=copy.deepcopy(report);region=bad['sources'][0]['regions'][0]
            if mutation=='negative':region['motion_samples'][0]['speed']=-1
            elif mutation=='duplicate':region['motion_samples'][1]['seconds']=1.
            elif mutation=='outside':region['motion_samples'][-1]['seconds']=1000
            elif mutation=='confidence':region['confidence']=1.1
            elif mutation=='cut':bad['sources'][0]['diagnostics']['cuts']=[2.]
            elif mutation=='missing_first_frame':del region['first_frame']
            elif mutation=='frame_grid':region['source_frame_times'][20]+=.001
            elif mutation=='absent_context':del region['context_motion_samples']
            else:region['context_motion_samples'][20]['dt']+=.01
            self.resign(bad)
            with self.subTest(mutation=mutation),self.assertRaises(InputError):
                load_selections([self.save(bad)],[self.clip],[],[])

    def test_cut_analysis_and_aspect_ratio(self):
        fixture=make_fixture(self.root/'cut.mp4','scene_cut',1777,width=320,height=180)
        clip=probe(Path(fixture['path']),'cut');source=analyze_sources([clip])['sources'][0]
        w,h=source['diagnostics']['analysis_size']
        self.assertAlmostEqual(w/h,320/180,delta=.02)
        self.assertTrue(any(abs(t-2.)<=.05 for t in source['diagnostics']['cuts']))
        for region in source['regions']:
            self.assertFalse(region['start_seconds']<2.<region['end_seconds'])

    def test_protected_and_no_improvement_preserve_schedule(self):
        region=self.measured_report()['sources'][0]['regions'][0]
        mapping=build_map(self.clip,self.clip.duration,2.,12,.5,len(self.clip.frames),self.clip.fps)
        before=select_schedule(self.clip,mapping)
        self.assertEqual(apply_region(mapping,region),'protected_interval_priority')
        self.assertEqual(before,select_schedule(self.clip,mapping))
        mapping=build_map(self.clip,self.clip.duration,.5,12,.5,len(self.clip.frames),self.clip.fps)
        for sample in region['motion_samples']+region['context_motion_samples']:
            sample['speed']=4.;sample['confidence']=.9
        self.assertEqual(apply_region(mapping,region),'steady_motion_no_correction')
        after=select_schedule(self.clip,mapping)
        self.assertEqual(before,after);self.assertEqual(after,sorted(after))
        self.assertEqual((after[0],after[-1]),(0,len(self.clip.frames)-1))

    def test_selected_v2_full_pipeline_keeps_decoded_budget_and_protection(self):
        speed=make_fixture(self.root/'pipeline_speed.mp4','speed_jump',1741)
        constant=make_fixture(self.root/'pipeline_constant.mp4','constant',1729)
        clips=[probe(Path(f['path']),f'clip_{i+1:02d}') for i,f in enumerate((speed,constant))]
        report=analyze_sources(clips)
        selected=[r['id'] for r in report['sources'][0]['regions']]
        self.assertTrue(selected,'Calibration speed jump must supply a review candidate')
        report_path=self.save(report,'pipeline_motion.json')
        result=retime([str(c.path) for c in clips],str(self.root/'pipeline_run'),
                      targets=[3.,4.],protect=.5,motion_reports=[report_path],selected_regions=selected)
        final=json.loads((result/'results/report.json').read_text(encoding='utf-8'))
        decoded=probe(result/'results/corrected.mp4','decoded')
        self.assertEqual(len(decoded.frames),140)
        self.assertAlmostEqual(decoded.duration,7.,places=5)
        applied=[d for d in final['internal_motion']['decisions'] if d['region_id'] in selected]
        self.assertTrue(any(d['applied'] and d['changed_source_selections']>0 for d in applied))
        mapping=final['corrected']['mapping']
        for index,(start,end) in enumerate(((0,60),(60,140))):
            with self.subTest(clip=index):
                indices=[r['source_frame'] for r in mapping[start:end]]
                self.assertEqual((indices[0],indices[-1]),(0,79))
                self.assertEqual(indices,sorted(indices))
                self.assertEqual(indices[:11],list(range(11)))
                exported=probe(result/'results'/f'clip_{index+1:02d}.mp4','export')
                self.assertEqual(len(exported.frames),end-start)
                self.assertAlmostEqual(exported.duration,(end-start)/20,places=5)
        self.assertEqual([r['source_frame'] for r in mapping[60:]],list(range(80)))


if __name__=='__main__':unittest.main()
