import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fixtures'))
from synthetic import make_motion_clip,make_positions_clip
from video_manager.errors import InputError,ToolError
from video_manager.internal_motion import analyze_sources
from video_manager.job_schema import load_job,normalize_job,run_job,save_job,validate_job
from video_manager.probe import probe
from video_manager.report import write_report
from video_manager.retime import retime


class JobTests(unittest.TestCase):
    def config(self,root):
        inputs=root/'한글 입력';inputs.mkdir()
        paths=[make_motion_clip(inputs/f'클립 {i}.mp4',5+i*20,25+i*20,count=40) for i in range(3)]
        return dict(schema_version=1,output=dict(directory='출력 결과/job',fps=24,audio_mode='mute'),
            clips=[dict(id=f'shot_{i}',path=str(p.relative_to(root)),target_seconds=t,
                        protect_seconds=psec,max_speed=5,ramp_seconds=.3,correction_enabled=enabled)
                   for i,(p,t,psec,enabled) in enumerate(zip(paths,[2,1.5,1.5],[.5,.3,.2],[False,True,True]))],
            boundaries=[{'from':'shot_0','to':'shot_1','window_seconds':.25,'local_speed':True,'strength':.8},
                        {'from':'shot_1','to':'shot_2','enabled':False,'window_seconds':.5,'local_speed':True}])

    def test_relative_roundtrip_fps_override_and_api_equivalence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);raw=self.config(root)
            config=normalize_job(raw,root);path=root/'작업 설정.json';save_job(config,path)
            loaded=load_job(path);self.assertEqual(loaded,config)
            _,validation=validate_job(loaded)
            self.assertEqual(validation['total_frames'],120)
            self.assertFalse(Path(config['output']['directory']).exists())
            job=run_job(path)
            report=json.loads((job/'results/report.json').read_text())
            self.assertEqual(report['stage'],'C')
            self.assertEqual(report['corrected']['fps'],'24')
            self.assertEqual(report['timeline_validation']['decoded_frames'],120)
            self.assertEqual(report['decisions'][0]['exclusion_reason'],'adjacent_clip_disabled')
            self.assertEqual(report['decisions'][1]['exclusion_reason'],'boundary_disabled')
            self.assertTrue(all(d['speed_requested'] for d in report['decisions']))
            self.assertEqual([b['segment_end_frame']-b['segment_start_frame'] for b in report['corrected']['boundaries']],[12,24])
            self.assertEqual(json.loads((job/'results/executed_job.json').read_text()),config)
            self.assertEqual(report['clips'][0]['id'],'shot_0')
            clips=config['clips']
            direct=retime([c['path'] for c in clips],str(root/'direct'),
                targets=[c['target_seconds'] for c in clips],protect=[c['protect_seconds'] for c in clips],
                max_speed=[c['max_speed'] for c in clips],ramp=[c['ramp_seconds'] for c in clips],
                disabled_clips=[1],clip_ids=[c['id'] for c in clips],output_fps=24,boundary_options=config['boundaries'])
            other=json.loads((direct/'results/report.json').read_text())
            self.assertEqual(report['corrected']['mapping'],other['corrected']['mapping'])
            self.assertEqual(report['timeline_validation'],other['timeline_validation'])
            with self.assertRaises(InputError):
                run_job(path)

    def test_strict_invalid_config_and_no_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);raw=self.config(root)
            bad=[]
            item=copy.deepcopy(raw);item['surprise']=1;bad.append(item)
            item=copy.deepcopy(raw);item['clips'][0]['target_seconds']=True;bad.append(item)
            item=copy.deepcopy(raw);item['clips'][0]['target_seconds']=float('nan');bad.append(item)
            item=copy.deepcopy(raw);item['clips'][1]['id']='shot_0';bad.append(item)
            item=copy.deepcopy(raw);item['boundaries'][0]['to']='shot_2';bad.append(item)
            item=copy.deepcopy(raw);item['output']['fps']=False;bad.append(item)
            item=copy.deepcopy(raw);item['clips'][0]['correction_enabled']='false';bad.append(item)
            item=copy.deepcopy(raw);item['boundaries'][0]['extra']=3;bad.append(item)
            for value in bad:
                with self.assertRaises(InputError):normalize_job(value,root)
            path=root/'invalid.json';path.write_text('{"schema_version":1,"schema_version":1}')
            with self.assertRaises(InputError):load_job(path)
            path.write_text('{"schema_version":NaN}')
            with self.assertRaises(InputError):load_job(path)
            missing=normalize_job(raw,root);missing['clips'][1]['path']=str(root/'missing.mp4')
            with self.assertRaises(InputError):validate_job(missing)
            conflict=normalize_job(raw,root);conflict['output']['directory']=conflict['clips'][0]['path']
            with self.assertRaises(InputError):validate_job(conflict)
            broken=root/'broken-output';broken.symlink_to(root/'absent-target')
            symlink_config=copy.deepcopy(raw);symlink_config['output']['directory']=str(broken)
            with self.assertRaises(InputError):normalize_job(symlink_config,root)
            with self.assertRaises(InputError):validate_job(normalize_job(raw,root),broken)
            self.assertTrue(broken.is_symlink())
            self.assertFalse((root/'absent-target').exists())
            dependency=root/'motion-report.json';dependency.write_text('preserve me')
            safe=normalize_job(raw,root);safe['internal_motion']['reports']=[str(dependency)]
            with self.assertRaises(InputError):save_job(safe,dependency,overwrite=True)
            self.assertEqual(dependency.read_text(),'preserve me')
            self.assertFalse((root/'출력 결과').exists())

    def test_stale_motion_rejected_before_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);raw=self.config(root);config=normalize_job(raw,root)
            path=Path(config['clips'][1]['path'])
            # Existing fixture is replaced only inside this test's disposable directory.
            path.unlink();make_positions_clip(path,list(range(5,15))+[15]*10+list(range(15,35)))
            clips=[probe(Path(c['path']),c['id']) for c in config['clips']]
            analysis=analyze_sources(clips);reportpath=root/'analysis.json';write_report(reportpath,analysis)
            selected=analysis['sources'][1]['regions'][0]['id']
            config['internal_motion']={'reports':[str(reportpath)],'selected_ids':[selected],'excluded_ids':[]}
            with path.open('ab') as stream:stream.write(b'changed')
            with self.assertRaises(InputError):validate_job(config)
            self.assertFalse(Path(config['output']['directory']).exists())

    def test_runtime_failure_and_cancel_never_publish_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=normalize_job(self.config(root),root)
            for label,error,status in [('failure',ToolError('simulated encoder failure'),'failed'),
                                       ('cancel',KeyboardInterrupt(),'cancelled')]:
                output=root/label
                with patch('video_manager.retime.render_clips',side_effect=error):
                    with self.assertRaises(type(error)):run_job(config,output)
                self.assertFalse((output/'results').exists())
                self.assertEqual(json.loads((output/'status.json').read_text())['status'],status)


if __name__=='__main__':unittest.main()
