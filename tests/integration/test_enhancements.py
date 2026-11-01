import copy
from fractions import Fraction
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from video_manager.enhancements import normalize_enhancements
from video_manager.errors import InputError,ToolError
from video_manager.frame_effects import FrameEffects,interpolation_guard
from video_manager.job_schema import normalize_job,save_job,load_job,run_job
from video_manager.probe import probe
from video_manager.render import Encoder,decode_frames,render_clips
from video_manager.time_map import build_map,select_schedule


def translation(path):
    rng=np.random.default_rng(7026)
    texture=cv2.GaussianBlur(rng.integers(20,230,(96,160,3),np.uint8),(5,5),.8)
    encoder=Encoder(path,160,96,Fraction(12))
    try:
        for i in range(12):
            frame=cv2.warpAffine(texture,np.float32([[1,0,i*2],[0,1,0]]),(160,96),borderMode=cv2.BORDER_REFLECT_101)
            encoder.write(frame.tobytes())
    finally:encoder.close()
    return probe(path,path.stem)


class EnhancementTests(unittest.TestCase):
    def test_legacy_defaults_roundtrip_and_invalid_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            raw=dict(schema_version=1,output=dict(directory='output'),clips=[
                dict(id=f'c{i}',path=f'{i}.mp4',target_seconds=2) for i in range(2)])
            old=normalize_job(raw,root)
            self.assertFalse(old['enhancements']['interpolation']['enabled'])
            self.assertFalse(old['enhancements']['stabilization']['enabled'])
            old['enhancements']=normalize_enhancements(dict(interpolation=dict(enabled=True),
                stabilization=dict(enabled=True,max_crop_fraction=.04,strength=.8)))
            path=root/'한글 설정.json';save_job(old,path)
            self.assertEqual(load_job(path),old)
            for value in ({'x':True},{'interpolation':{'enabled':1}},
                          {'interpolation':{'backend':'rife'}},{'stabilization':{'max_crop_fraction':.4}},
                          {'stabilization':{'strength':float('nan')}}):
                with self.assertRaises(InputError):normalize_enhancements(value)

    def test_stream_endpoints_protect_guards_and_disabled_equivalence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);clip=translation(root/'source.mp4')
            mapping=build_map(clip,2,.1,12,.4,24,Fraction(12))
            schedule=select_schedule(clip,mapping)
            times=[mapping.source_time(i/12) for i in range(24)]
            decoded=list(decode_frames(clip,160,96))
            options=normalize_enhancements({'interpolation':{'enabled':True}})
            effects=FrameEffects(clip,160,96,options,.1)
            frames=list(effects.frames(schedule,times,Fraction(12)))
            self.assertEqual(frames[0][1],decoded[0]);self.assertEqual(frames[-1][1],decoded[-1])
            for i,(_,data,metadata) in enumerate(frames):
                if i/12<=.1:self.assertEqual(data,decoded[schedule[i]])
                p=metadata['interpolation'];self.assertLessEqual(p['right_frame']-p['left_frame'],1)
            self.assertGreater(effects.summary()['interpolated_output_frames'],0)
            def failed_decoder(*args):
                yield from decoded
                raise ToolError('decoder failed after final frame')
            with patch('video_manager.render.decode_frames',side_effect=failed_decoder):
                with self.assertRaisesRegex(ToolError,'after final frame'):
                    list(effects.frames(schedule,times,Fraction(12)))
            pair=dict(cut=False,abstain_reason='',confidence=.1,dt=1/12)
            self.assertEqual(interpolation_guard(pair,1/12),'low_tracking_confidence')
            pair.update(cut=True,abstain_reason='scene_cut',confidence=1)
            self.assertEqual(interpolation_guard(pair,1/12),'scene_cut')
            baseline=render_clips([clip],root,[schedule],prefix='off',output_fps=12)
            other=render_clips([clip],root,[schedule],prefix='disabled',output_fps=12,
                enhancements=options,source_times=[times],protects=[.1],disabled_clips=[1])
            self.assertEqual(baseline['mapping'],other['mapping'])
            left=list(decode_frames(probe(root/'off.mp4','off'),160,96))
            right=list(decode_frames(probe(root/'disabled.mp4','disabled'),160,96))
            self.assertEqual(left,right)

    def test_saved_job_actual_output_budget_and_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);clips=[translation(root/f'input{i}.mp4') for i in range(2)]
            raw=dict(schema_version=1,output=dict(directory=str(root/'result'),fps=12),
                clips=[dict(id=c.id,path=str(c.path),target_seconds=2 if i==0 else 1,protect_seconds=.1,
                    correction_enabled=i==0) for i,c in enumerate(clips)],
                enhancements=dict(interpolation=dict(enabled=True),stabilization=dict(enabled=True)))
            path=root/'job.json';save_job(raw,path)
            directory=run_job(path)
            report=json.loads((directory/'results/report.json').read_text(encoding='utf-8'))
            self.assertEqual(report['timeline_validation']['decoded_frames'],36)
            self.assertAlmostEqual(report['timeline_validation']['measured_total_seconds'],3,places=6)
            enhanced=report['corrected']['enhancements']
            self.assertGreater(enhanced[0]['interpolated_output_frames'],0)
            self.assertEqual(enhanced[1]['reason'],'clip_correction_disabled')
            first=report['corrected']['mapping'][0];last=report['corrected']['mapping'][23]
            self.assertEqual(first['source_frame'],0);self.assertEqual(last['source_frame'],11)
            self.assertFalse(first['interpolation']['applied']);self.assertFalse(last['interpolation']['applied'])
            rows=[row for row in report['corrected']['mapping'] if row.get('interpolation',{}).get('applied')]
            self.assertTrue(all(0<row['interpolation']['alpha']<1 for row in rows))
            self.assertTrue(all(row['interpolation']['details']['source_resample_passes']==1 for row in rows))
            self.assertTrue(all(row['interpolation']['details']['single_pass_composition'] for row in rows))
            self.assertTrue(report['settings']['enhancements']['interpolation']['enabled'])


if __name__=='__main__':unittest.main()
