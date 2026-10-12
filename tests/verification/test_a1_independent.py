"""Independent A1 verification: installed CLI and job lifecycle."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from video_manager.pipeline import job_directory

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / '.venv/bin/video-manager'

class IndependentA1(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='a1-verification-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.inputs = [self.base / '첫 클립.mp4', self.base / 'second.mp4']
        for index, path in enumerate(self.inputs):
            path.write_bytes(bytes([index + 1]) * 42)

    def cli(self, *args, env=None):
        return subprocess.run([str(CLI), *map(str, args)], capture_output=True, text=True, env=env)

    def test_installed_help_and_doctor(self):
        self.assertEqual(self.cli('--help').returncode, 0)
        result = self.cli('doctor')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['encoder'], 'libx264')

    def test_isolated_path_missing_tools(self):
        env = dict(os.environ, PATH=str(self.base))
        result = self.cli('doctor', env=env)
        self.assertEqual(result.returncode, 3)
        self.assertIn('ffmpeg', result.stderr)
        (self.base / 'ffmpeg').symlink_to('/usr/bin/ffmpeg')
        result = self.cli('doctor', env=env)
        self.assertEqual(result.returncode, 3)
        self.assertIn('ffprobe', result.stderr)

    def test_invalid_inputs_and_no_output(self):
        empty = self.base / 'empty'; empty.touch()
        for inputs in [[], [self.inputs[0]], [*self.inputs, empty], [*self.inputs, self.base], [*self.inputs, self.base/'absent']]:
            result = self.cli('prepare', *inputs, '--output', self.base/'out')
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertFalse((self.base/'out').exists())

    def test_prepare_order_unicode_source_preservation_and_reexecution(self):
        before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in self.inputs]
        output = self.base/'결과 폴더'
        result = self.cli('prepare', *reversed(self.inputs), '--output', output)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((output/'results/preparation.json').read_text())
        self.assertEqual(report['inputs'], list(map(str, reversed(self.inputs))))
        saved = {str(p.relative_to(output)): p.read_bytes() for p in output.rglob('*') if p.is_file()}
        self.assertEqual(self.cli('prepare', *self.inputs, '--output', output).returncode, 2)
        self.assertEqual(saved, {str(p.relative_to(output)): p.read_bytes() for p in output.rglob('*') if p.is_file()})
        self.assertEqual(before, [hashlib.sha256(p.read_bytes()).hexdigest() for p in self.inputs])

    def test_outputs_never_overwrite_input_directory_or_symlink(self):
        link = self.base/'dangling'; link.symlink_to(self.base/'missing')
        for output in [self.inputs[0], self.base, link]:
            self.assertEqual(self.cli('prepare', *self.inputs, '--output', output).returncode, 2)
        self.assertTrue(link.is_symlink())
        self.assertEqual(self.inputs[0].read_bytes(), bytes([1])*42)

    def test_process_failure_and_cancellation_diagnostics(self):
        for name, exception, code in [('failed', 'RuntimeError("failure injection")', 1), ('cancelled', 'KeyboardInterrupt()', 130)]:
            output = self.base/name
            script = ('from video_manager.pipeline import job_directory\n'
                      'from pathlib import Path\n'
                      'try:\n'
                      f' with job_directory({str(output)!r}, []) as job:\n'
                      '  (job.work / "diagnostic.txt").write_text("preserve me")\n'
                      f'  raise {exception}\n'
                      'except KeyboardInterrupt: raise SystemExit(130)\n')
            result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True)
            self.assertEqual(result.returncode, code)
            self.assertFalse((output/'results').exists())
            status = json.loads((output/'status.json').read_text())
            self.assertEqual(status['status'], name)
            self.assertEqual((Path(status['temporary_directory'])/'diagnostic.txt').read_text(), 'preserve me')

if __name__ == '__main__':
    unittest.main()
