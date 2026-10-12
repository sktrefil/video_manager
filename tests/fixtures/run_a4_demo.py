"""Reproducible A4 synthetic review pack; never overwrites an existing directory.

Run with the project's virtualenv Python from any current working directory.
This verifies technical invariants, not subjective quality on generated footage.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

from synthetic import make_motion_clip
from video_manager.probe import probe
from video_manager.report import file_hash, write_report


def run_demo(root: Path):
    root = root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=False)
    manifest = {
        'stage': 'A4', 'status': 'running',
        'quality_status': 'synthetic_checks_only_actual_clip_user_review_pending',
        'scope': 'No claim of perceptual improvement; source frames and settings are synthetic.',
        'sequences': {}, 'runs': [],
    }
    try:
        cases = {
            'normal': [(5, 35), (35, 65), (65, 95), (95, 125)],
            'stress': [(5, 85), (85, 110), (110, 70), (72, 72)],
        }
        expectations = {
            'normal': ['shared endpoint and approximately equal speed'] * 3,
            'stress': ['shared endpoint; fast to slow motion',
                       'shared endpoint; direction reversal unsuitable for time-only repair',
                       '2-pixel endpoint mismatch; static hold unsuitable for speed repair'],
        }
        for name, spans in cases.items():
            folder = root / 'inputs' / name
            folder.mkdir(parents=True)
            paths = [make_motion_clip(folder / f'clip_{i+1:02d}.mp4', start, end)
                     for i, (start, end) in enumerate(spans)]
            manifest['sequences'][name] = {
                'inputs': [{'path': str(p), 'sha256': file_hash(p),
                            'source_motion_x': list(spans[i]), 'frames': 40, 'fps': 20}
                           for i, p in enumerate(paths)],
                'boundary_intents': expectations[name],
            }
        jobs = [
            ('normal_off', 'normal', []),
            ('normal_on', 'normal', ['--local-speed', '--remove-duplicates']),
            ('stress_off', 'stress', []),
            ('stress_on', 'stress', ['--local-speed', '--remove-duplicates']),
            ('normal_clip2_disabled', 'normal', ['--local-speed', '--remove-duplicates', '--disable-clip', '2']),
        ]
        for name, sequence, flags in jobs:
            output = root / name
            command = [sys.executable, '-m', 'video_manager', 'boundaries',
                       *[item['path'] for item in manifest['sequences'][sequence]['inputs']],
                       '--output', str(output), '--window', '1', '--strength', '1', *flags]
            print(f'Running {name}', flush=True)
            started = time.monotonic()
            result = subprocess.run(command, text=True, capture_output=True, check=False)
            run = {'name': name, 'sequence': sequence, 'command_argv': command,
                   'exit_code': result.returncode, 'elapsed_seconds': round(time.monotonic()-started, 3),
                   'stdout': result.stdout, 'stderr': result.stderr, 'output': str(output)}
            manifest['runs'].append(run)
            if result.returncode:
                raise RuntimeError(f'{name} failed: {result.stderr}')
            report_path = output / 'results' / 'report.json'
            report = json.loads(report_path.read_text())
            run.update(report=str(report_path), report_sha256=file_hash(report_path),
                       decisions=report['decisions'], duration_change_seconds=report['duration_change_seconds'],
                       decoded_videos=[])
            for video in sorted((output/'results').glob('*.mp4')):
                media = probe(video, video.stem)
                if not media.frames:
                    raise AssertionError(f'Empty video: {video}')
                run['decoded_videos'].append({'path': str(video), 'frames': len(media.frames),
                                              'duration_seconds': media.duration, 'sha256': file_hash(video)})
            for prefix in ['baseline', 'corrected']:
                info = next(v for v in run['decoded_videos'] if Path(v['path']).name == f'{prefix}.mp4')
                assert info['frames'] == report[prefix]['frame_count']
                assert abs(info['duration_seconds'] - report[prefix]['duration_seconds']) <= 1/20
            for comparison in report['comparisons']:
                info = next(v for v in run['decoded_videos'] if Path(v['path']).name == comparison['video'])
                assert info['frames'] == len(comparison['mapping'])
                center = comparison['boundary_frame_in_comparison']
                assert comparison['mapping'][center]['relative_seconds'] == 0
            if name.endswith('_off'):
                assert report['baseline']['mapping'] == report['corrected']['mapping']
            if name == 'stress_on':
                assert report['decisions'][0]['speed_applied']
                assert any(report['decisions'][0]['positional_schedule_changes'].values())
                assert report['source_measurements'][1]['reason'] == 'direction_conflict'
                assert not report['decisions'][1]['speed_applied']
                assert not report['decisions'][2]['speed_applied']
                assert not report['source_measurements'][2]['duplicate_candidate']
            if name == 'normal_clip2_disabled':
                assert all(d['exclusion_reason'] == 'adjacent_clip_disabled' for d in report['decisions'][:2])
                assert all(not d['duplicate_removed'] and not d['speed_applied'] for d in report['decisions'][:2])
        for sequence in manifest['sequences'].values():
            for source in sequence['inputs']:
                assert source['sha256'] == file_hash(Path(source['path']))
        manifest['status'] = 'synthetic_technical_checks_passed'
        manifest['checks'] = ['all output videos decoded', 'rendered frame counts match schedules',
                              'output timing matches declared CFR duration', 'F2 center equals relative time zero',
                              'options-off frame mappings unchanged', 'speed mismatch produces a changed schedule',
                              'direction conflict/static speed correction suppressed',
                              'mismatched endpoint not removed', 'disabled clip suppresses both adjacent boundaries',
                              'input SHA-256 unchanged']
    except BaseException as exc:
        manifest.update(status='failed', error=str(exc))
        raise
    finally:
        write_report(root/'manifest.json', manifest)
    (root/'REVIEW.md').write_text('# A4 합성 영상 검토\n\n' + '\n'.join([
        '이 패키지는 합성 기능 검증용입니다. 실제 생성 영상 품질 통과를 의미하지 않습니다.',
        '',
        '- `normal_on/results/comparison_boundary_01.mp4`: 동일 속도·공유 이미지의 중복 제거 후보.',
        '- `stress_on/results/comparison_boundary_01.mp4`: 빠른 동작에서 느린 동작으로 이어지는 국소 변속 후보.',
        '- `stress_on/results/comparison_boundary_02.mp4`: 방향 반전. 배속 보정 부적합으로 유지합니다.',
        '- `stress_on/results/comparison_boundary_03.mp4`: 끝 이미지 미세 차이와 정지. 무리한 보정을 적용하지 않습니다.',
        '- `normal_clip2_disabled/results/report.json`: 2번 클립의 인접 경계 보정 제외.',
        '',
        '`*_off`와 `*_on`은 같은 입력의 설정 비교이며 각 폴더에 기준본·후보·진단 영상이 있습니다.',
        '정상 속도로 비교하고 원본 프레임 번호·출력 시간·경계 상대 시간을 구분하세요.',
        '`manifest.json`에 명령 인수·입력 해시·출력 목록·검사 결과가 있습니다.',
        '실제 클립 3~4개와 사용자 품질 확인 전에는 작업 B로 진행하지 않습니다.',
    ])+'\n', encoding='utf-8')
    print(f'Review pack: {root}')
    return root


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='New output directory (must not exist)')
    args = parser.parse_args()
    run_demo(args.output)
