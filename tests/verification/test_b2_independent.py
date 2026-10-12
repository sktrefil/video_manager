"""Independent actual-pixel review/selection checks for B2."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import numpy as np
from test_a3_independent import frames
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests/fixtures'))
from synthetic import make_positions_clip,make_motion_clip

class IndependentB2(unittest.TestCase):
 def test_cli_review_explicit_pixels_exclusion_and_budget(self):
  with tempfile.TemporaryDirectory() as temp:
   d=Path(temp);pause=make_positions_clip(d/'pause.mp4',list(range(5,45))+[45]*20+list(range(45,105)))
   steady=make_motion_clip(d/'steady.mp4',5,125,count=120)
   cli=str(ROOT/'.venv/bin/video-manager')
   subprocess.run([cli,'inspect-motion',str(pause),str(steady),'--output',str(d/'review')],capture_output=True,check=True)
   reportpath=d/'review/results/motion_report.json';report=json.loads(reportpath.read_text())
   self.assertEqual(report['default_selected'],[]);self.assertFalse(report['sources'][1]['regions'])
   region=report['sources'][0]['regions'][0]['id'];preview=next(p for p in report['previews'] if p['region_id']==region)
   self.assertFalse(preview['selected_for_final'])
   originals=frames(pause)
   for name in ['original','proposal']:
    video=frames(d/'review/results'/f'{region}_{name}.mp4')
    for index,row in enumerate(preview[name]['mapping']):
     self.assertLess(np.abs(video[index].astype(float)-originals[row['source_frame']]).mean(),4)
   comp=preview['comparison'];pixels=frames(d/'review/results'/comp['video'],320,120)
   diagnostics={n:frames(d/'review/results'/f'{region}_{n}_diagnostic.mp4') for n in ['original','proposal']}
   for index,row in enumerate(comp['mapping']):
    if row['original'] and row['proposal']:self.assertEqual(row['original']['output_frame'],row['proposal']['output_frame'])
    for side,name in enumerate(['original','proposal']):
     if row[name]:
      expected=diagnostics[name][row[name]['output_frame'],46:91,10:150]
      actual=pixels[index,70:115,side*160+10:side*160+150]
      self.assertLess(np.abs(actual.astype(float)-expected).mean(),4)
   reports={}
   for label,flags in [('off',[]),('on',['--select-region',region]),('excluded',['--select-region',region,'--exclude-region',region])]:
    out=d/label
    subprocess.run([cli,'retime',str(pause),str(steady),'--targets','4','4','--motion-report',str(reportpath),'--output',str(out),*flags],capture_output=True,check=True)
    reports[label]=json.loads((out/'results/report.json').read_text())
   self.assertEqual(reports['off']['corrected']['mapping'],reports['excluded']['corrected']['mapping'])
   self.assertNotEqual(reports['off']['corrected']['mapping'],reports['on']['corrected']['mapping'])
   video=frames(d/'on/results/corrected.mp4');sources=[originals,frames(steady)]
   self.assertEqual(len(video),160)
   for index,row in enumerate(reports['on']['corrected']['mapping']):
    source=sources[int(row['clip_id'].split('_')[1])-1]
    self.assertLess(np.abs(video[index].astype(float)-source[row['source_frame']]).mean(),4)
    if index<=20 or 80<=index<=100:self.assertEqual(row['source_frame'],index%80)
   self.assertEqual(reports['on']['corrected']['mapping'][79]['source_frame'],119)
   self.assertEqual(reports['on']['corrected']['mapping'][-1]['source_frame'],119)
   # Invalid identifiers rejected by installed CLI, with no successful result.
   invalid=subprocess.run([cli,'retime',str(pause),str(steady),'--targets','4','4','--motion-report',str(reportpath),'--select-region','unknown','--output',str(d/'bad')],capture_output=True)
   self.assertEqual(invalid.returncode,2);self.assertFalse((d/'bad/results').exists())

if __name__=='__main__':unittest.main()
