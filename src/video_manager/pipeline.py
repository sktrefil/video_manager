"""Input protection and isolated job lifecycle shared by processing stages."""
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import json
import tempfile
import uuid

from .errors import InputError


def validate_inputs(paths: list[str | Path], minimum: int = 2) -> list[Path]:
    if len(paths) < minimum:
        raise InputError(f"At least {minimum} input clips are required in playback order")
    resolved = []
    for value in paths:
        path = Path(value).expanduser().resolve()
        if not path.is_file():
            raise InputError(f"Input is not a regular file: {path}")
        try:
            with path.open("rb") as stream:
                if not stream.read(1):
                    raise InputError(f"Input is empty: {path}")
        except OSError as exc:
            raise InputError(f"Cannot read input: {path}: {exc}") from exc
        resolved.append(path)
    return resolved


@dataclass(frozen=True)
class JobPaths:
    root: Path
    work: Path
    results: Path


@contextmanager
def job_directory(output: str | Path, inputs: list[Path]):
    """Reserve a new directory exclusively; publish results only after success.

    Failed jobs keep a status report and work files for diagnosis. Existing paths,
    including dangling symlinks, are never reused or removed.
    """
    raw = Path(output).expanduser().absolute()
    if raw.exists() or raw.is_symlink():
        raise InputError(f"Output already exists; choose a new directory: {raw}")
    root = raw.resolve()
    if any(root == source or root in source.parents for source in inputs):
        raise InputError("Output must not contain or replace an input file")
    try:
        root.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise InputError(f"Cannot create output directory: {root}: {exc}") from exc
    work = Path(tempfile.mkdtemp(prefix=".work-", dir=root))
    paths = JobPaths(root, work, root / "results")
    status = {"job_id": uuid.uuid4().hex, "inputs": [str(p) for p in inputs]}
    try:
        yield paths
        work.rename(paths.results)
        status["status"] = "success"
    except BaseException as exc:
        status.update(status="cancelled" if isinstance(exc, KeyboardInterrupt) else "failed",
                      error=str(exc), temporary_directory=str(work))
        raise
    finally:
        with (root / "status.json").open("x", encoding="utf-8") as stream:
            json.dump(status, stream, indent=2, ensure_ascii=False)


def baseline(paths: list[str], output: str) -> Path:
    from .probe import probe
    from .render import boundary_segments, render_clips
    from .report import file_hash, write_report
    from .tools import diagnose

    inputs = validate_inputs(paths)
    tools = diagnose()
    with job_directory(output, inputs) as job:
        hashes = [file_hash(path) for path in inputs]
        clips = [probe(path, f"clip_{index:02d}") for index, path in enumerate(inputs, 1)]
        result = render_clips(clips, job.work)
        boundary_segments(job.work, result)
        decoded = probe(job.work / 'baseline.mp4', 'output')
        if len(decoded.frames) != result['frame_count']:
            raise InputError('Rendered output frame count differs from schedule')
        diagnostic = probe(job.work / 'baseline_diagnostic.mp4', 'diagnostic')
        if len(diagnostic.frames) != result['frame_count']:
            raise InputError('Diagnostic output frame count differs from schedule')
        for boundary in result['boundaries']:
            segment = probe(job.work / boundary['segment'], 'boundary')
            if len(segment.frames) != boundary['segment_end_frame'] - boundary['segment_start_frame']:
                raise InputError('Boundary segment frame count differs from requested range')
        if any(file_hash(path) != before for path, before in zip(inputs, hashes)):
            raise InputError('An input changed during processing; result is not validated')
        result.update(stage='A2', audio_mode='mute', tools=tools,
                      policy={'fps': 'first clip average FPS; constant output rate',
                              'dimensions': 'first clip square-pixel display dimensions rounded to even',
                              'aspect_ratio': 'fit with black padding; no cropping or stretching',
                              'frame_selection': 'nearest normalized source PTS, ties choose previous; preserve first and last',
                              'duration': 'per-clip rounded to output frames; no time compression'},
                      clips=[dict(clip.metadata(), sha256=sha) for clip, sha in zip(clips, hashes)],
                      decoded_frame_count=len(decoded.frames), decoded_duration_seconds=decoded.duration)
        write_report(job.work / 'report.json', result)
    return job.root


def boundaries(paths: list[str], output: str, *, window=0.5, strength=0.3,
               local_speed=False, remove_duplicates=False,
               disabled_clips=(), disabled_boundaries=()) -> Path:
    from .boundary import analyze_boundaries, analyze_rendered, correction_schedules, validate_options
    from .comparison import compare_boundaries
    from .probe import probe
    from .render import boundary_segments, render_clips
    from .report import file_hash, write_report
    from .tools import diagnose

    inputs = validate_inputs(paths)
    validate_options(len(inputs), window, strength, disabled_clips, disabled_boundaries)
    tools = diagnose()
    with job_directory(output, inputs) as job:
        hashes = [file_hash(path) for path in inputs]
        clips = [probe(path, f'clip_{i:02d}') for i, path in enumerate(inputs, 1)]
        measurements = analyze_boundaries(clips, window)
        schedules, decisions = correction_schedules(clips, measurements, window=window, strength=strength,
            local_speed=local_speed, remove_duplicates=remove_duplicates,
            disabled_clips=disabled_clips, disabled_boundaries=disabled_boundaries)
        reference = render_clips(clips, job.work)
        candidate = render_clips(clips, job.work, schedules=schedules, prefix='corrected')
        boundary_segments(job.work, reference, window=window)
        boundary_segments(job.work, candidate, prefix='corrected', window=window)
        comparisons = compare_boundaries(job.work, reference, candidate, window)
        for prefix, result in [('baseline', reference), ('corrected', candidate)]:
            decoded = probe(job.work / f'{prefix}.mp4', prefix)
            if len(decoded.frames) != result['frame_count']:
                raise InputError(f'{prefix}: decoded output frame count differs from schedule')
            result['measured_boundaries'] = analyze_rendered(job.work / f'{prefix}.mp4', result, window)
            result['decoded_duration_seconds'] = decoded.duration
        if any(file_hash(path) != before for path, before in zip(inputs, hashes)):
            raise InputError('An input changed during processing')
        for index, decision in enumerate(decisions):
            decision['positional_schedule_changes'] = {}
            for ci in [index, index+1]:
                original = [r['source_frame'] for r in reference['mapping'] if r['clip_id'] == clips[ci].id]
                decision['positional_schedule_changes'][clips[ci].id] = sum(
                    a != b for a,b in zip(schedules[ci], original)) + abs(len(schedules[ci])-len(original))
        write_report(job.work / 'report.json', dict(stage='A3', tools=tools, audio_mode='mute',
            quality_status='candidate_only_real_visual_quality_unverified',
            settings=dict(window_seconds=window, strength=strength, local_speed=local_speed,
                          remove_duplicates=remove_duplicates, disabled_clips=list(disabled_clips),
                          disabled_boundaries=list(disabled_boundaries)),
            clips=[dict(clip.metadata(), sha256=sha, correction_enabled=(i+1 not in disabled_clips))
                   for i, (clip, sha) in enumerate(zip(clips, hashes))],
            source_measurements=measurements, decisions=decisions, baseline=reference, corrected=candidate,
            duration_change_seconds=candidate['duration_seconds']-reference['duration_seconds'],
            comparisons=comparisons))
    return job.root
