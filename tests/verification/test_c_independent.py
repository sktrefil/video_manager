"""Independent JSON CLI round-trip and actual output equivalence."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import numpy as np
from test_a3_independent import frames
from video_manager.job_schema import normalize_job,save_job,load_job,run_job
from video_manager.internal_motion import analyze_sources
from video_manager.probe import probe
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests/fixtures'))
from synthetic import make_positions_clip,make_motion_clip

class IndependentC(unittest.TestCase):
 def test_cli_new_directory_roundtrip_motion_exclusion_fps_pixels(self):
  with tempfile.TemporaryDirectory() as temp:
   d=Path(temp);src=d/'한글 입력';src.mkdir()
   a=make_positions_clip(src/'멈춤 1.mp4',list(range(5,25))+[25]*10+list(range(25,55)))
   b=make_motion_clip(src/'정상 2.mp4',55,100,count=60)
   analysis=analyze_sources([probe(a,'first'),probe(b,'second')]);mp=d/'분석.json';mp.write_text(json.dumps(analysis))
   rid=analysis['sources'][0]['regions'][0]['id']
   raw={'schema_version':1,'output':{'directory':'결과','fps':24},'clips':[
    {'id':'first','path':str(a.relative_to(d)),'target_seconds':2,'protect_seconds':.2},
    {'id':'second','path':str(b.relative_to(d)),'target_seconds':2,'protect_seconds':.2}],
    'boundaries':[{'from':'first','to':'second','enabled':False,'window_seconds':.25,'local_speed':True}],
    'internal_motion':{'reports':['분석.json'],'selected_ids':[rid],'excluded_ids':[rid]}}
   cfg=normalize_job(raw,d);jobfile=d/'다른 폴더/작업.json';save_job(cfg,jobfile)
   self.assertEqual(load_job(jobfile),cfg)
   self.assertEqual(load_job(jobfile)['internal_motion']['reports'],[str(mp)])
   cli=str(ROOT/'.venv/bin/video-manager')
   subprocess.run([cli,'validate-job',str(jobfile)],capture_output=True,check=True)
   self.assertFalse((d/'결과').exists())
   subprocess.run([cli,'run-job',str(jobfile)],capture_output=True,check=True)
   r=json.loads((d/'결과/results/report.json').read_text())
   self.assertEqual(r['timeline_validation']['decoded_frames'],96)
   self.assertEqual(r['decisions'][0]['exclusion_reason'],'boundary_disabled')
   self.assertTrue(all(not dec['applied'] for dec in r['internal_motion']['decisions']))
   self.assertEqual(r['corrected']['boundaries'][0]['segment_end_frame']-r['corrected']['boundaries'][0]['segment_start_frame'],12)
   direct=run_job(cfg,d/'direct')
   actual=frames(d/'결과/results/corrected.mp4');other=frames(direct/'results/corrected.mp4')
   self.assertEqual(len(actual),96);self.assertTrue(np.array_equal(actual,other))
   meta=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','stream=r_frame_rate,duration','-of','json',str(d/'결과/results/corrected.mp4')]))['streams'][0]
   self.assertEqual(meta['r_frame_rate'],'24/1');self.assertAlmostEqual(float(meta['duration']),4)
   rerun=subprocess.run([cli,'run-job',str(jobfile)],capture_output=True)
   self.assertEqual(rerun.returncode,2)

if __name__=='__main__':unittest.main()
