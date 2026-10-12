import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'fixtures'))
from synthetic import make_motion_clip, make_sequence
from video_manager.boundary import analyze_boundaries, correction_schedules, local_schedule, validate_options
from video_manager.errors import InputError
from video_manager.pipeline import boundaries
from video_manager.probe import probe
from video_manager.render import decode_frames, frame_schedule
from video_manager.report import file_hash


class BoundaryTests(unittest.TestCase):
    def test_speed_mapping_changes_actual_frames_and_endpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = [make_motion_clip(root/'fast.mp4', 5, 85), make_motion_clip(root/'slow.mp4', 85, 110)]
            hashes = [file_hash(p) for p in paths]
            clips = [probe(p, f'clip_{i+1:02d}') for i,p in enumerate(paths)]
            measured = analyze_boundaries(clips, 1)
            self.assertTrue(measured[0]['suitable_for_speed_candidate'], measured)
            schedules, decisions = correction_schedules(clips, measured, window=1, strength=1,
                                                         local_speed=True, remove_duplicates=False)
            self.assertTrue(decisions[0]['speed_applied'])
            self.assertTrue(any(s != frame_schedule(c, c.fps) for s,c in zip(schedules,clips)))
            for schedule, clip in zip(schedules, clips):
                self.assertEqual((schedule[0], schedule[-1]), (0,len(clip.frames)-1))
                self.assertEqual(schedule, sorted(schedule))
            job = boundaries([str(p) for p in paths], str(root/'job'), window=1, strength=1, local_speed=True)
            report = json.loads((job/'results/report.json').read_text())
            self.assertEqual(report['baseline']['frame_count'], report['corrected']['frame_count'])
            clean = list(decode_frames(probe(job/'results/baseline.mp4','base'),160,96))
            candidate = list(decode_frames(probe(job/'results/corrected.mp4','candidate'),160,96))
            self.assertTrue(any(a != b for a,b in zip(clean,candidate)))
            self.assertEqual(hashes, [file_hash(p) for p in paths])
            # No-change controls remain unchanged when speed is disabled or strength is zero.
            for enabled, strength in [(False,1),(True,0)]:
                schedule,_ = correction_schedules(clips,measured,window=1,strength=strength,
                                                  local_speed=enabled,remove_duplicates=False)
                self.assertEqual(schedule,[frame_schedule(c,clips[0].fps) for c in clips])

    def test_direction_conflict_and_static_are_not_corrected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            paths=[make_motion_clip(root/'forward.mp4',5,85), make_motion_clip(root/'reverse.mp4',85,5)]
            clips=[probe(p,str(i)) for i,p in enumerate(paths)]
            measured=analyze_boundaries(clips,1)
            self.assertEqual(measured[0]['reason'],'direction_conflict',measured)
            _,decision=correction_schedules(clips,measured,window=1,strength=1,local_speed=True,remove_duplicates=False)
            self.assertFalse(decision[0]['speed_applied'])
            static=make_motion_clip(root/'static.mp4',85,85)
            measured=analyze_boundaries([clips[0],probe(static,'static')],1)
            self.assertFalse(measured[0]['suitable_for_speed_candidate'])
            self.assertTrue(measured[0]['after']['freeze_candidate'])

    def test_f3_exclusion_combinations_and_duplicate_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            paths=make_sequence(root/'inputs',3)
            clips=[probe(p,f'clip_{i+1:02d}') for i,p in enumerate(paths)]
            measured=analyze_boundaries(clips,.5)
            defaults=[frame_schedule(c,clips[0].fps) for c in clips]
            schedule, decisions=correction_schedules(clips,measured,window=.5,strength=1,local_speed=True,
                remove_duplicates=True,disabled_clips=[2])
            self.assertEqual(schedule,defaults)
            self.assertTrue(all(d['exclusion_reason']=='adjacent_clip_disabled' for d in decisions))
            schedule, decisions=correction_schedules(clips,measured,window=.5,strength=1,local_speed=False,
                remove_duplicates=True,disabled_boundaries=[1])
            self.assertEqual(schedule[:2],defaults[:2])
            self.assertEqual(schedule[2],defaults[2][1:])
            self.assertEqual(decisions[0]['exclusion_reason'],'boundary_disabled')
            self.assertEqual(decisions[1]['retained_representative'],{'clip_id':'clip_02','source_frame':9})
            self.assertEqual(schedule[2][-1],9)

    def test_f2_common_clock_outside_blank_and_duration_difference(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            paths=make_sequence(root/'inputs',3)
            job=boundaries([str(p) for p in paths],str(root/'job'),window=2,remove_duplicates=True)
            report=json.loads((job/'results/report.json').read_text())
            self.assertEqual(report['corrected']['frame_count'],28)
            self.assertEqual(report['baseline']['frame_count'],30)
            self.assertAlmostEqual(report['duration_change_seconds'],-.2)
            for comp in report['comparisons']:
                rows=comp['mapping']
                center=comp['boundary_frame_in_comparison']
                self.assertEqual(rows[center]['relative_seconds'],0)
                for name in ['baseline','corrected']:
                    boundary=report[name]['boundaries'][comp['boundary']-1]
                    for row in rows:
                        if row[name] is not None:
                            self.assertEqual(row[name]['output_frame'],boundary['output_frame']+row['relative_frame'])
                video=probe(job/'results'/comp['video'],'compare')
                self.assertEqual(len(video.frames),len(rows))
                pixels=list(decode_frames(video,320,120))
                outside=[i for i,r in enumerate(rows) if r['corrected'] is None]
                self.assertTrue(outside)
                # Far corner remains black, not a held video frame.
                raw=pixels[outside[0]]
                self.assertLess(max(raw[(110*320+310)*3:(110*320+310)*3+3]),10)

    def test_invalid_options(self):
        for window,strength in [(0,.3),(3,.3),(.5,float('nan')),(.5,2)]:
            with self.assertRaises(InputError):
                validate_options(3,window,strength,[],[])
        with self.assertRaises(InputError):
            validate_options(3,.5,.3,[4],[])
        with self.assertRaises(InputError):
            validate_options(3,.5,.3,[],[3])


if __name__=='__main__':
    unittest.main()
