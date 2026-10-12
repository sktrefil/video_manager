"""Independent CLI/decoded-pixel checks for A2 and F1."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT/'.venv/bin/video-manager'

def run(*args, data=None):
    p = subprocess.run(list(map(str,args)), input=data, capture_output=True)
    if p.returncode:
        raise AssertionError(p.stderr.decode(errors='replace'))
    return p.stdout

def decode(path):
    raw = run('ffmpeg','-v','error','-i',path,'-map','0:v:0','-fps_mode','passthrough','-f','rawvideo','-pix_fmt','rgb24','-')
    size=160*96*3
    return [raw[i:i+size] for i in range(0,len(raw),size)]

class IndependentA2(unittest.TestCase):
    def test_actual_cli_vfr_ids_order_padding_diagnostics_and_failure(self):
        with tempfile.TemporaryDirectory(prefix='a2-independent-') as tmp:
            d=Path(tmp); first=d/'원본 1.mkv'; second=d/'portrait.mp4'
            # Flat gray frame identities remain independently readable through H.264.
            values=[25+20*i for i in range(10)]
            raw=b''.join(bytes([v])*160*96*3 for v in values)
            run('ffmpeg','-v','error','-f','rawvideo','-pix_fmt','rgb24','-s','160x96','-r','10','-i','-',
                '-vf',"setpts='if(lt(N,5),N*0.1,0.5+(N-5)*0.2)/TB+2/TB'",'-fps_mode','vfr','-c:v','ffv1',first,data=raw)
            run('ffmpeg','-v','error','-f','lavfi','-i','color=blue:s=96x160:r=12:d=1',
                '-f','lavfi','-i','sine=frequency=440:duration=1','-c:v','libx264','-threads','2','-c:a','aac','-shortest',second)
            inputs=[first,second,first]
            hashes=[hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs]
            out=d/'결과'; run(CLI,'baseline',*inputs,'--output',out)
            report=json.loads((out/'results/report.json').read_text())
            clean=decode(out/'results/baseline.mp4'); diag=decode(out/'results/baseline_diagnostic.mp4')
            self.assertEqual(len(clean),len(report['mapping']))
            self.assertTrue(report['clips'][0]['vfr'])
            self.assertGreater(report['clips'][0]['first_pts'],0)
            self.assertTrue(report['clips'][1]['has_audio'])
            self.assertEqual([c['path'] for c in report['clips']],list(map(str,inputs)))
            # Decode pixels independently for EVERY source selection, including repeated VFR frames.
            observed=[]
            for row,frame in zip(report['mapping'],clean):
                px=frame[(70*160+80)*3:(70*160+80)*3+3]
                if row['clip_id'] in ('clip_01','clip_03'):
                    identity=min(range(10),key=lambda i:abs(values[i]-px[0]))
                    self.assertEqual(identity,row['source_frame'])
                    expected_time=identity*.1 if identity<5 else .5+(identity-5)*.2
                    self.assertAlmostEqual(row['source_seconds'],expected_time,places=5)
                    self.assertAlmostEqual(row['pts_seconds'],expected_time+2,places=5)
                    observed.append(identity)
                else:
                    self.assertGreater(px[2],200)
                    self.assertLess(max(frame[(70*160+2)*3:(70*160+2)*3+3]),10)
            self.assertIn(0,observed); self.assertIn(9,observed)
            # Clean production frame top is flat; diagnostic top includes visible white glyphs.
            self.assertLess(max(clean[0][:160*35*3]),40)
            self.assertGreater(max(diag[0][:160*35*3]),150)
            info=json.loads(run('ffprobe','-v','error','-show_streams','-of','json',out/'results/baseline.mp4'))
            self.assertEqual(len(info['streams']),1)
            self.assertEqual(info['streams'][0]['codec_type'],'video')
            for boundary in report['boundaries']:
                segment=decode(out/'results'/boundary['segment'])
                self.assertEqual(len(segment),boundary['segment_end_frame']-boundary['segment_start_frame'])
            before=(out/'results/report.json').read_bytes()
            rerun=subprocess.run([str(CLI),'baseline',*map(str,inputs),'--output',str(out)],capture_output=True)
            self.assertEqual(rerun.returncode,2)
            self.assertEqual(before,(out/'results/report.json').read_bytes())
            self.assertEqual(hashes,[hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs])
            bad=d/'bad.mp4'; bad.write_text('not media')
            failed=subprocess.run([str(CLI),'baseline',str(first),str(bad),'--output',str(d/'badjob')],capture_output=True)
            self.assertEqual(failed.returncode,2)
            self.assertFalse((d/'badjob/results').exists())
            self.assertEqual(json.loads((d/'badjob/status.json').read_text())['status'],'failed')

if __name__=='__main__': unittest.main()
