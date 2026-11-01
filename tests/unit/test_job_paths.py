import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from video_manager.job_schema import load_job, normalize_job, save_job


class JobPathTests(unittest.TestCase):
    def test_save_roundtrip_across_drives_and_same_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = normalize_job({
                'schema_version': 1,
                'output': {'directory': str(root / 'output')},
                'clips': [{'id': f'clip_{i}', 'path': str(root / f'{i}.mp4'),
                           'target_seconds': 4} for i in range(2)],
                'internal_motion': {'reports': [str(root / 'motion.json')]},
                'narration': {'audio_path': str(root / 'narration.mp3'),
                              'subtitle_srt': str(root / 'subtitles.srt')},
            }, root)
            cross = root / 'cross.json'
            with patch('video_manager.job_schema.os.path.relpath',
                       side_effect=ValueError("path is on mount 'D:', start on mount 'C:'")):
                save_job(config, cross)
            self.assertEqual(json.loads(cross.read_text(encoding='utf-8')), config)
            self.assertEqual(load_job(cross), config)
            same = root / 'same.json'
            save_job(config, same)
            data = json.loads(same.read_text(encoding='utf-8'))
            self.assertEqual(data['clips'][0]['path'], '0.mp4')
            self.assertEqual(data['output']['directory'], 'output')
            self.assertEqual(data['internal_motion']['reports'], ['motion.json'])
            self.assertEqual(data['narration']['audio_path'], 'narration.mp3')
            self.assertEqual(data['narration']['subtitle_srt'], 'subtitles.srt')
            self.assertEqual(load_job(same), config)
