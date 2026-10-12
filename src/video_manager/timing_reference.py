"""Read production planning times without treating the plan as an executable job."""
import json
import math
from pathlib import Path
import re

from .errors import InputError


_CLIP_NAME = re.compile(r'^SC(\d{1,2})\s*[·._ -]+\s*(\d{1,2})[-_](\d{1,2})$', re.IGNORECASE)
_SHORT_NAME = re.compile(r'^(\d{1,2})[-_](\d{1,2})$')
_CUT = re.compile(r'^(\d{1,2})-(\d{1,2})$')


def clip_key(path):
    name = Path(path).stem
    match = _CLIP_NAME.fullmatch(name)
    if match:
        scene, scene_in_cut, shot = map(int, match.groups())
    elif match := _SHORT_NAME.fullmatch(name):
        scene_in_cut, shot = map(int, match.groups())
        scene = scene_in_cut
    else:
        raise InputError(f'Cannot match clip name to Master scene/cut: {name}')
    if scene != scene_in_cut:
        raise InputError(f'Scene and cut disagree in clip name: {name}')
    return f'SC{scene:02d}', f'{scene_in_cut:02d}-{shot:02d}'


def _finite(value, label, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise InputError(f'{label} must be a finite number')
    if positive and value <= 0:
        raise InputError(f'{label} must be positive')
    return float(value)


def load_master_timings(path, clip_paths):
    """Return targets in existing UI order; reject an incomplete or ambiguous match."""
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as exc:
        raise InputError(f'Cannot load Master JSON: {exc}') from exc
    if not isinstance(data, dict) or not isinstance(data.get('records'), list):
        raise InputError('Expected a Master JSON with a records array')
    records = data['records']
    if not records:
        raise InputError('Master JSON has no records')
    if 'shot_count' in data and (isinstance(data['shot_count'], bool) or data['shot_count'] != len(records)):
        raise InputError('Master shot_count does not match records')
    by_key = {}
    total = 0.0
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise InputError(f'Master record {index + 1} must be an object')
        scene = record.get('scene')
        cut = record.get('cut')
        if not isinstance(scene, str) or not re.fullmatch(r'SC\d{1,2}', scene, re.IGNORECASE):
            raise InputError(f'Master record {index + 1} has an invalid scene')
        if not isinstance(cut, str) or not (match := _CUT.fullmatch(cut)):
            raise InputError(f'Master record {index + 1} has an invalid cut')
        scene_number = int(scene[2:])
        if scene_number != int(match.group(1)):
            raise InputError(f'Master record {index + 1} has a scene/cut mismatch')
        key = f'SC{scene_number:02d}', f'{int(match.group(1)):02d}-{int(match.group(2)):02d}'
        if key in by_key:
            raise InputError(f'Duplicate scene/cut in Master: {key[0]} {key[1]}')
        start = _finite(record.get('start_s'), f'{key} start_s')
        end = _finite(record.get('end_s'), f'{key} end_s')
        target = _finite(record.get('edit_duration_s'), f'{key} edit_duration_s', positive=True)
        if start < 0 or end <= start or abs(end - start - target) > 1e-6:
            raise InputError(f'Master start/end/duration mismatch: {key[0]} {key[1]}')
        by_key[key] = target
        total += target
    if 'edit_duration_seconds' in data and abs(_finite(data['edit_duration_seconds'], 'edit_duration_seconds') - total) > 1e-6:
        raise InputError('Master total duration does not match records')
    if not clip_paths:
        raise InputError('Add local clips before loading Master timings; Master has no MP4 paths')
    keys = [clip_key(path) for path in clip_paths]
    if len(set(keys)) != len(keys):
        raise InputError('The clip list contains the same scene/cut more than once')
    missing = [f'{scene} {cut}' for scene, cut in keys if (scene, cut) not in by_key]
    if missing:
        raise InputError(f'No Master timing for: {", ".join(missing)}')
    return [by_key[key] for key in keys]
