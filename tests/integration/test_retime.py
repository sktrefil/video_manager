from fractions import Fraction
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fixtures'))
from synthetic import make_motion_clip
from video_manager.errors import InputError
from video_manager.probe import probe
from video_manager.render import decode_frames
from video_manager.report import file_hash
from video_manager.retime import retime
from video_manager.tools import run_tool


class RetimeTests(unittest.TestCase):
    def check_report(self,job,targets,protects):
        report=json.loads((job/'results/report.json').read_text())
        self.assertEqual(report['timeline_validation']['status'],'passed')
        self.assertAlmostEqual(report['timeline_validation']['measured_total_seconds'],sum(targets),places=5)
        fps=float(Fraction(report['corrected']['fps']))
        for ci,item in enumerate(report['timeline']):
            self.assertAlmostEqual(item['measured_clip_seconds'],targets[ci],places=5)
            rows=[r for r in report['corrected']['mapping'] if r['clip_id']==item['clip_id']]
            source=report['clips'][ci]['frames']
            self.assertEqual(rows[0]['source_frame'],0)
            self.assertEqual(rows[-1]['source_frame'],len(source)-1)
            self.assertEqual([r['source_frame'] for r in rows],sorted(r['source_frame'] for r in rows))
            for index,row in enumerate(rows):
                t=index/fps
                if t<=protects[ci]:
                    nearest=min(range(len(source)),key=lambda j:abs(source[j]['source_seconds']-t))
                    self.assertEqual(row['source_frame'],nearest)
            self.assertEqual(report['clips'][ci]['sha256'],file_hash(Path(report['clips'][ci]['path'])))
        return report

    def test_eleven_and_eight_second_budgets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            inputs=[make_motion_clip(root/f'{i}.mp4',5,85,count=n,fps=20) for i,n in enumerate([200,80,200])]
            job=retime([str(p) for p in inputs],str(root/'eleven'),targets=[3,4,4],protect=[1,1,1],
                       local_speed=True,remove_duplicates=True)
            report=self.check_report(job,[3,4,4],[1,1,1])
            self.assertEqual(report['corrected']['frame_count'],220)
            self.assertFalse(report['timeline'][1]['mapping']['compressed'])
            self.assertTrue(all(not d['duplicate_removed'] for d in report['decisions']))
            # Verify actual decoded endpoints against selected originals, not just report rows.
            for item,source in zip(report['timeline'],inputs):
                original=list(decode_frames(probe(source,'src'),160,96))
                output=list(decode_frames(probe(job/'results'/item['files'][0],'out'),160,96))
                for index in [0,-1]:
                    mae=sum(abs(a-b) for a,b in zip(original[index],output[index]))/len(output[index])
                    self.assertLess(mae,5)
            job=retime([str(inputs[0]),str(inputs[2])],str(root/'eight'),targets=[4,4],protect=1)
            self.check_report(job,[4,4],[1,1])

    def test_ten_to_four_six_to_five_and_disabled_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            inputs=[make_motion_clip(root/'ten.mp4',5,85,count=200),make_motion_clip(root/'six.mp4',85,120,count=120)]
            job=retime([str(p) for p in inputs],str(root/'job'),targets=[4,5],protect=[2,3],max_speed=8)
            self.check_report(job,[4,5],[2,3])
            with self.assertRaises(InputError):
                retime([str(p) for p in inputs],str(root/'disabled'),targets=[4,5],disabled_clips=[1])
            with self.assertRaises(InputError):
                retime([str(p) for p in inputs],str(root/'audio'),targets=[4,5],audio_mode='preserve')

    def test_vfr_nonzero_start_mixed_fps_fractional_budgets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            first=make_motion_clip(root/'first.mp4',5,85,count=60,fps=24)
            second=root/'vfr.mkv'
            run_tool(['ffmpeg','-v','error','-n','-f','lavfi','-i','testsrc2=size=96x160:rate=10:duration=3',
                      '-vf',"setpts='if(lt(N,15),N*0.1,1.5+(N-15)*0.2)/TB+2/TB'",'-fps_mode','vfr',
                      '-c:v','ffv1','-threads','2',str(second)])
            job=retime([str(first),str(second)],str(root/'job'),targets=[2.01,2.01],protect=.5,ramp=.3)
            report=json.loads((job/'results/report.json').read_text())
            self.assertTrue(report['clips'][1]['vfr'])
            self.assertGreater(report['clips'][1]['first_pts'],0)
            self.assertEqual(report['timeline_validation']['decoded_frames'],round(4.02*24))
            self.assertLess(abs(report['timeline_validation']['error_seconds']),1/24)
            self.assertTrue(all(abs(t['error_seconds'])<1/24 for t in report['timeline']))
            for item in report['timeline']:
                rows=[r for r in report['corrected']['mapping'] if r['clip_id']==item['clip_id']]
                self.assertEqual(rows[0]['source_frame'],0)
                self.assertEqual(rows[-1]['source_frame'],len(report['clips'][report['timeline'].index(item)]['frames'])-1)


if __name__=='__main__':
    unittest.main()

class EffectiveBoundaryVelocityTests(unittest.TestCase):
    def test_compressed_tail_targets_fixed_protected_next_clip(self):
        from synthetic import make_positions_clip
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            left=make_positions_clip(root/'left.mp4',[5]*180+[5+2*i for i in range(20)])
            right=make_positions_clip(root/'right.mp4',[43+3*i for i in range(25)]+[115]*55)
            job=retime([str(left),str(right)],str(root/'job'),targets=[3,4],protect=1,
                       local_speed=True,window=.8,strength=.5)
            report=json.loads((job/'results/report.json').read_text())
            decision=report['decisions'][0];planning=decision['velocity_planning']
            self.assertLess(planning['source_before'],planning['source_after'])
            self.assertGreater(planning['effective_before'],planning['effective_after'])
            self.assertLess(decision['left_alpha'],0)
            self.assertEqual(planning['target'],planning['effective_after'])
            self.assertEqual(decision['side_results']['right'],'protected_interval_priority')
