"""Encoded/exported enhancement detail and exact legacy-disabled behavior."""
from fractions import Fraction
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from video_manager.probe import probe
from video_manager.render import Encoder,decode_frames,render_clips
from video_manager.retime import export_clip_outputs


class EncodingFidelityTests(unittest.TestCase):
    def test_fidelity_encode_and_export_preserve_processed_detail(self):
        rng=np.random.default_rng(881)
        texture=cv2.GaussianBlur(rng.integers(20,235,(180,320,3),dtype=np.uint8),(3,3),0)
        frames=[cv2.warpAffine(texture,np.float32([[1.02,-.003,.3+i*.6],[.003,1.02,-.7]]),
            (320,180),flags=cv2.INTER_LANCZOS4,borderMode=cv2.BORDER_REPLICATE) for i in range(16)]
        def sharp(frame):
            return cv2.Laplacian(cv2.cvtColor(frame,cv2.COLOR_RGB2GRAY)[20:-20,20:-20],cv2.CV_64F).var()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name,fidelity in (('corrected',True),('corrected_diagnostic',False),('legacy',False)):
                encoder=Encoder(root/f'{name}.mp4',320,180,Fraction(20),fidelity=fidelity)
                try:
                    for frame in frames:encoder.write(frame.tobytes())
                finally:encoder.close()
            result=dict(fps='20',clip_ranges=[dict(clip_id='part',start_frame=0,end_frame=16)],
                        encoding=dict(profile='enhancement_fidelity_v1'))
            exported=export_clip_outputs(root,result)
            self.assertEqual(exported[0]['encoding']['encoder_crf'],1)
            self.assertEqual(exported[0]['encoding']['profile'],'enhancement_fidelity_v1')
            ratios={}
            for name in ('legacy','corrected','part'):
                clip=probe(root/f'{name}.mp4',name)
                self.assertEqual(len(clip.frames),16)
                self.assertAlmostEqual(clip.duration,.8,places=5)
                decoded=[np.frombuffer(raw,np.uint8).reshape(180,320,3) for raw in decode_frames(clip,320,180)]
                ratios[name]=min(sharp(a)/sharp(b) for a,b in zip(decoded,frames))
            self.assertGreaterEqual(ratios['corrected'],.97)
            self.assertGreaterEqual(ratios['part'],.95)
            self.assertGreater(ratios['corrected'],ratios['legacy'])

    def test_all_disabled_retains_legacy_encoding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);encoder=Encoder(root/'source.mp4',64,48,Fraction(10))
            rng=np.random.default_rng(882)
            try:
                for _ in range(5):encoder.write(rng.integers(20,230,(48,64,3),dtype=np.uint8).tobytes())
            finally:encoder.close()
            clip=probe(root/'source.mp4','source');schedule=list(range(5))
            old=render_clips([clip],root,[schedule],prefix='off')
            disabled=render_clips([clip],root,[schedule],prefix='disabled',disabled_clips=[1],
                enhancements={'stabilization':{'enabled':True}})
            self.assertNotIn('encoding',old);self.assertNotIn('encoding',disabled)
            self.assertEqual((root/'off.mp4').read_bytes(),(root/'disabled.mp4').read_bytes())


if __name__=='__main__':unittest.main()
