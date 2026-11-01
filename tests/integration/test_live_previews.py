"""Boundary preview notices are emitted only after a playable MP4 is finished."""
from fractions import Fraction
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2

from video_manager.comparison import compare_boundaries
from video_manager.pipeline import job_directory
from video_manager.render import Encoder


class LivePreviewTests(unittest.TestCase):
    def test_result_publication_retries_short_preview_read_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            original=Path.rename;attempts=[]
            def intermittently_locked(path,target):
                attempts.append(1)
                if len(attempts)<3:raise PermissionError('preview copy still reading')
                return original(path,target)
            with patch.object(Path,'rename',autospec=True,side_effect=intermittently_locked):
                with job_directory(Path(tmp)/'job',[]) as job:
                    (job.work/'comparison_boundary_01.mp4').write_bytes(b'complete')
            self.assertEqual(len(attempts),3)
            self.assertTrue((Path(tmp)/'job/results/comparison_boundary_01.mp4').is_file())

    def test_comparison_progress_announces_finalized_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);work=root/'.work-test';work.mkdir()
            for name in ('baseline','corrected'):
                encoder=Encoder(work/f'{name}_diagnostic.mp4',64,48,Fraction(10))
                try:
                    for shade in (40,60,80):encoder.write(bytes([shade,shade,shade])*64*48)
                finally:encoder.close()
            report=dict(fps='10',width=64,height=48,frame_count=3,
                        boundaries=[dict(output_frame=1)],mapping=[{} for _ in range(3)])
            notices=[]
            def record(stage,done,total,*,completed_video=None):
                if completed_video:
                    capture=cv2.VideoCapture(str(completed_video))
                    try:
                        self.assertTrue(capture.isOpened())
                        self.assertEqual(int(capture.get(cv2.CAP_PROP_FRAME_COUNT)),3)
                        self.assertTrue(capture.read()[0])
                    finally:capture.release()
                notices.append((stage,done,total,completed_video))
            with patch('video_manager.progress.report',side_effect=record):
                result=compare_boundaries(work,report,report,.1,
                                          preview_output=root/'.live-previews')
            self.assertEqual(len(result),1)
            self.assertEqual(notices[0],('Creating comparison videos',0,1,None))
            self.assertEqual(notices[-1],('Creating comparison videos',1,1,
                                         root/'.live-previews/comparison_boundary_01.mp4'))
            preview_handle=(root/'.live-previews/comparison_boundary_01.mp4').open('rb')
            try:work.rename(root/'results')
            finally:preview_handle.close()
            self.assertTrue((root/'results/comparison_boundary_01.mp4').is_file())


if __name__=='__main__':unittest.main()
