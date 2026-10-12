import json
from pathlib import Path
import tempfile
import unittest

from video_manager.errors import InputError
from video_manager.timing_reference import load_master_timings


class MasterTimingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'Master.json'
        self.data = {
            'shot_count': 2,
            'edit_duration_seconds': 7,
            'records': [
                {'scene': 'SC01', 'cut': '01-02', 'start_s': 4, 'end_s': 7, 'edit_duration_s': 3},
                {'scene': 'SC01', 'cut': '01-03', 'start_s': 7, 'end_s': 11, 'edit_duration_s': 4},
            ],
        }

    def tearDown(self):
        self.temp.cleanup()

    def write(self):
        self.path.write_text(json.dumps(self.data), encoding='utf-8')

    def test_matches_existing_clip_order_without_media_paths_in_master(self):
        self.write()
        self.assertEqual(load_master_timings(self.path, [
            Path('SC01 · 01-03.mp4'), Path('SC01 · 01-02.mp4')]), [4, 3])

    def test_missing_or_ambiguous_records_fail_before_any_ui_change(self):
        self.write()
        with self.assertRaisesRegex(InputError, 'No Master timing'):
            load_master_timings(self.path, [Path('SC01 · 01-04.mp4')])
        self.data['records'][1]['cut'] = '01-02'
        self.write()
        with self.assertRaisesRegex(InputError, 'Duplicate scene/cut'):
            load_master_timings(self.path, [Path('SC01 · 01-02.mp4')])

    def test_rejects_inconsistent_planned_duration(self):
        self.data['records'][0]['edit_duration_s'] = 10
        self.write()
        with self.assertRaisesRegex(InputError, 'start/end/duration mismatch'):
            load_master_timings(self.path, [Path('SC01 · 01-02.mp4')])


if __name__ == '__main__':
    unittest.main()
