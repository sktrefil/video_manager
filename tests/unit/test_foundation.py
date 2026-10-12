import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from video_manager.cli import main
from video_manager.errors import InputError, ToolError
from video_manager.pipeline import job_directory, validate_inputs
from video_manager.tools import diagnose, run_tool


class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.clips = [self.base / '첫 번째.mp4', self.base / 'second.mp4']
        for index, path in enumerate(self.clips):
            path.write_bytes(bytes([index + 1]) * 32)

    def test_order_and_input_hash_preserved(self):
        before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in self.clips]
        inputs = validate_inputs(list(reversed(self.clips)))
        self.assertEqual(inputs, list(reversed(self.clips)))
        with job_directory(self.base / 'job', inputs) as job:
            (job.work / 'result.txt').write_text('new')
            self.assertFalse(job.results.exists())
        self.assertTrue((job.results / 'result.txt').is_file())
        self.assertFalse(job.work.exists())
        self.assertEqual(json.loads((job.root / 'status.json').read_text())['status'], 'success')
        self.assertEqual(before, [hashlib.sha256(p.read_bytes()).hexdigest() for p in self.clips])

    def test_existing_output_and_input_rejected(self):
        for output in [self.base, self.clips[0]]:
            with self.assertRaises(InputError), job_directory(output, self.clips):
                self.fail('Existing path was accepted')
        link = self.base / 'dangling'
        link.symlink_to(self.base / 'missing')
        with self.assertRaises(InputError), job_directory(link, self.clips):
            self.fail('Symlink was accepted')
        self.assertTrue(link.is_symlink())

    def test_missing_empty_directory_and_insufficient_inputs(self):
        empty = self.base / 'empty.mp4'
        empty.touch()
        for paths in [[self.clips[0]], [self.clips[0], empty],
                      [self.clips[0], self.base], [self.clips[0], self.base / 'missing']]:
            with self.assertRaises(InputError):
                validate_inputs(paths)

    def test_failure_and_cancel_keep_diagnostics(self):
        for name, error, expected in [('failed', RuntimeError('test failure'), 'failed'),
                                      ('cancelled', KeyboardInterrupt(), 'cancelled')]:
            with self.assertRaises(type(error)):
                with job_directory(self.base / name, self.clips) as job:
                    (job.work / 'log.txt').write_text('diagnostic')
                    raise error
            self.assertFalse(job.results.exists())
            self.assertTrue((job.work / 'log.txt').exists())
            self.assertEqual(json.loads((job.root / 'status.json').read_text())['status'], expected)

    def test_missing_tools_and_exit_codes(self):
        with patch('video_manager.tools.shutil.which', return_value=None):
            with self.assertRaisesRegex(ToolError, 'ffmpeg'):
                diagnose()
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(['doctor']), 3)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['prepare', str(self.base / 'absent'), '--output', str(self.base / 'job')]), 2)
        self.assertFalse((self.base / 'job').exists())

    def test_missing_encoder(self):
        from subprocess import CompletedProcess
        with patch('video_manager.tools.shutil.which', side_effect=lambda name: name), \
             patch('video_manager.tools.run_tool', return_value=CompletedProcess([], 0, 'version without encoder\n', '')):
            with self.assertRaisesRegex(ToolError, 'libx264'):
                diagnose()

    def test_process_timeout_and_failure(self):
        import sys
        with self.assertRaises(ToolError):
            run_tool([sys.executable, '-c', 'import time; time.sleep(5)'], timeout=0.05)
        with self.assertRaisesRegex(ToolError, 'failed'):
            run_tool([sys.executable, '-c', 'raise SystemExit(7)'])


if __name__ == '__main__':
    unittest.main()
