import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'fixtures'))
from synthetic import make_sequence
from video_manager.errors import InputError
from video_manager.pipeline import baseline
from video_manager.probe import probe
from video_manager.render import decode_frames
from video_manager.report import file_hash
from video_manager.tools import run_tool


class BaselineTests(unittest.TestCase):
    def test_four_clips_order_mapping_hashes_and_decode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clips = make_sequence(root / '한글 입력')
            before = [file_hash(p) for p in clips]
            job = baseline([str(p) for p in clips], str(root / '출력 결과'))
            report = json.loads((job / 'results/report.json').read_text())
            self.assertEqual(report['frame_count'], 40)
            self.assertEqual(report['decoded_frame_count'], 40)
            self.assertAlmostEqual(report['decoded_duration_seconds'], 4.0)
            self.assertEqual(before, [file_hash(p) for p in clips])
            mapping = report['mapping']
            self.assertEqual([r['source_frame'] for r in mapping], list(range(10)) * 4)
            for number in range(4):
                self.assertEqual(mapping[number * 10]['clip_id'], f'clip_{number+1:02d}')
            output_clip = probe(job / 'results/baseline.mp4', 'output')
            output = list(decode_frames(output_clip, 160, 96))
            for number, source in enumerate(clips):
                original = list(decode_frames(probe(source, 'source'), 160, 96))
                for frame in (0, 9):
                    actual = output[number * 10 + frame]
                    expected = original[frame]
                    mae = sum(abs(a-b) for a,b in zip(actual, expected)) / len(actual)
                    self.assertLess(mae, 5, (number, frame, mae))
            for item in report['boundaries']:
                segment = probe(job / 'results' / item['segment'], 'segment')
                self.assertEqual(len(segment.frames), 10)
                self.assertAlmostEqual(item['boundary_seconds_in_segment'], 0.5)
            diag = list(decode_frames(probe(job / 'results/baseline_diagnostic.mp4', 'diag'), 160, 96))
            self.assertNotEqual(diag[0], output[0])
            with self.assertRaises(InputError):
                baseline([str(p) for p in clips], str(job))

    def test_vfr_nonzero_pts_mixed_aspect_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / 'vfr.mkv'
            run_tool(['ffmpeg', '-v', 'error', '-n', '-f', 'lavfi', '-i', 'testsrc2=size=160x96:rate=10:duration=1',
                      '-vf', "setpts='if(lt(N,5),N*0.1,0.5+(N-5)*0.2)/TB+2/TB'",
                      '-fps_mode', 'vfr', '-c:v', 'ffv1', '-threads', '2', str(first)])
            second = root / 'audio.mp4'
            run_tool(['ffmpeg', '-v', 'error', '-n', '-f', 'lavfi', '-i', 'color=blue:size=96x160:rate=12:duration=1',
                      '-f', 'lavfi', '-i', 'sine=frequency=400:duration=1', '-c:v', 'libx264', '-threads', '2',
                      '-c:a', 'aac', '-shortest', str(second)])
            info = probe(first, 'vfr')
            self.assertTrue(info.vfr)
            self.assertGreater(info.frames[0]['pts_seconds'], 1)
            self.assertEqual(info.frames[0]['source_seconds'], 0)
            job = baseline([str(first), str(second)], str(root / 'job'))
            report = json.loads((job / 'results/report.json').read_text())
            self.assertTrue(report['clips'][1]['has_audio'])
            self.assertFalse(probe(job / 'results/baseline.mp4', 'out').has_audio)
            rows = [r for r in report['mapping'] if r['clip_id'] == 'clip_01']
            self.assertEqual(rows[0]['source_frame'], 0)
            self.assertEqual(rows[-1]['source_frame'], len(info.frames)-1)
            for row in rows:
                self.assertEqual(row['source_seconds'], info.frames[row['source_frame']]['source_seconds'])
            # Padding leaves left/right black for portrait input in landscape output.
            out = probe(job / 'results/baseline.mp4', 'out')
            last = list(decode_frames(out, 160, 96))[-1]
            self.assertLess(max(last[(48*160+2)*3:(48*160+2)*3+3]), 10)
            self.assertGreater(last[(48*160+80)*3+2], 200)

    def test_malformed_media_is_not_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = root / 'not video.mp4'
            bad.write_text('not a video')
            with self.assertRaises(InputError):
                baseline([str(bad), str(bad)], str(root / 'job'))
            self.assertEqual(json.loads((root/'job/status.json').read_text())['status'], 'failed')
            self.assertFalse((root/'job/results').exists())


if __name__ == '__main__':
    unittest.main()
