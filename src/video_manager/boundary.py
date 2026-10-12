"""Boundary measurements and conservative, user-requested correction candidates."""
from bisect import bisect_left
from fractions import Fraction
import math

import cv2
import numpy as np

from .errors import InputError
from .render import decode_frames, frame_schedule

cv2.setNumThreads(1)


def validate_options(count, window, strength, disabled_clips, disabled_boundaries):
    if isinstance(window,bool) or not isinstance(window,(int,float)) or not math.isfinite(window) or not 0 < window <= 2:
        raise InputError('Boundary window must be > 0 and <= 2 seconds')
    if isinstance(strength,bool) or not isinstance(strength,(int,float)) or not math.isfinite(strength) or not 0 <= strength <= 1:
        raise InputError('Strength must be between 0 and 1')
    for label, values, upper in [('clip', disabled_clips, count), ('boundary', disabled_boundaries, count - 1)]:
        if any(isinstance(value,bool) or not isinstance(value,int) or value < 1 or value > upper for value in values):
            raise InputError(f'Disabled {label} indexes must be 1..{upper}')


def _selected_images(clip, window):
    times = [f['source_seconds'] for f in clip.frames]
    head = [i for i, t in enumerate(times) if t <= window]
    tail = [i for i, t in enumerate(times) if t >= times[-1] - window]
    # At most 16 samples per side, regardless of source FPS.
    select = lambda values: [values[i] for i in np.unique(np.linspace(0, len(values)-1, min(16, len(values))).astype(int))]
    head, tail = select(head), select(tail)
    wanted = set(head + tail)
    images = {}
    for i, raw in enumerate(decode_frames(clip, 160, 96)):
        if i in wanted:
            images[i] = np.frombuffer(raw, np.uint8).reshape(96, 160, 3).copy()
    return images, head, tail


def _motion(clip, images, indexes):
    vectors, speeds, similarities, active_fractions = [], [], [], []
    for left, right in zip(indexes, indexes[1:]):
        a = cv2.cvtColor(images[left], cv2.COLOR_RGB2GRAY)
        b = cv2.cvtColor(images[right], cv2.COLOR_RGB2GRAY)
        dt = clip.frames[right]['source_seconds'] - clip.frames[left]['source_seconds']
        flow = cv2.calcOpticalFlowFarneback(a, b, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        magnitude = np.linalg.norm(flow, axis=2)
        active = magnitude > 0.1
        similarities.append(float(np.mean(np.abs(a.astype(float)-b))))
        active_fractions.append(float(np.mean(active)))
        if np.any(active):
            vector = np.median(flow[active], axis=0) / dt
            vectors.append(vector)
            speeds.append(float(np.median(magnitude[active])) / dt)
        else:
            vectors.append(np.array([0.0, 0.0]))
            speeds.append(0.0)
    if not vectors:
        return dict(speed=0.0, direction=[0.0, 0.0], confidence=0.0, freeze_candidate=False, pair_mae=[])
    vector = np.median(vectors, axis=0)
    speed = float(np.median(speeds))
    # Direction consistency is a diagnostic, not a perceptual quality score.
    norms = [float(np.linalg.norm(v)) for v in vectors]
    coherence = float(np.linalg.norm(vector)) / (float(np.median(norms)) + 1e-6)
    texture = float(np.std(cv2.cvtColor(images[indexes[-1]], cv2.COLOR_RGB2GRAY)))
    confidence = min(1.0, float(np.median(active_fractions)) / 0.03) * min(1.0, texture / 10) * min(1.0, coherence)
    direction = vector / (np.linalg.norm(vector) + 1e-6)
    return dict(speed=speed, direction=[float(v) for v in direction], confidence=confidence,
                freeze_candidate=len(similarities) >= 2 and all(v < 0.5 for v in similarities[-2:]),
                pair_mae=similarities)


def analyze_boundaries(clips, window):
    cached = [_selected_images(clip, window) for clip in clips]
    measurements = []
    for index, (left, right) in enumerate(zip(clips, clips[1:])):
        li, _, tail = cached[index]
        ri, head, _ = cached[index+1]
        before = _motion(left, li, tail)
        after = _motion(right, ri, head)
        a, b = li[len(left.frames)-1], ri[0]
        mae = float(np.mean(np.abs(a.astype(float)-b)))
        rmse = float(np.sqrt(np.mean((a.astype(float)-b)**2)))
        cosine = float(np.dot(before['direction'], after['direction']))
        confident = min(before['confidence'], after['confidence']) >= 0.35
        conflict = confident and cosine < -0.25
        suitable = confident and not conflict and min(before['speed'], after['speed']) > 0.1
        reason = ('direction_conflict' if conflict else 'low_confidence_or_static' if not suitable else 'candidate_only')
        measurements.append(dict(boundary=index+1, from_clip=left.id, to_clip=right.id,
                                 endpoint_mae=mae, endpoint_rmse=rmse, endpoint_similarity=max(0.0, 1-mae/255),
                                 brightness_difference=float(np.mean(b)-np.mean(a)),
                                 duplicate_candidate=mae <= 3.0 and rmse <= 8.0,
                                 before=before, after=after, direction_cosine=cosine,
                                 suitable_for_speed_candidate=suitable, reason=reason))
    return measurements


def local_schedule(clip, fps, head=None, tail=None):
    """Compact cubic windows: derivative 1 at inner edge, 1+a at seam.

    head q(u)=u+a*u*(1-u)^2; tail q(u)=u+a*u^2*(u-1).
    |a|<=0.8 makes each derivative strictly positive. Nonoverlapping windows
    preserve both source endpoints. PTS selection then quantizes the mapping.
    """
    default = frame_schedule(clip, fps)
    times = [f['source_seconds'] for f in clip.frames]
    end = times[-1]
    result = []
    for output_index in range(len(default)):
        t = min(output_index / float(fps), end)
        if head and t < head[0]:
            width, alpha = head
            u = t / width
            t = width * (u + alpha * u * (1-u)**2)
        elif tail and t > end-tail[0]:
            width, alpha = tail
            u = (t-(end-width)) / width
            t = end-width + width * (u + alpha * u*u*(u-1))
        right = bisect_left(times, t)
        if right == 0:
            selected = 0
        elif right >= len(times):
            selected = len(times)-1
        else:
            selected = right-1 if t-times[right-1] <= times[right]-t else right
        result.append(selected)
    result[0], result[-1] = 0, len(times)-1
    if any(a > b for a, b in zip(result, result[1:])):
        raise InputError('Local frame mapping is not monotonic')
    return result


def correction_schedules(clips, measurements, *, window, strength, local_speed,
                         remove_duplicates, disabled_clips=(), disabled_boundaries=()):
    validate_options(len(clips), window, strength, disabled_clips, disabled_boundaries)
    heads, tails = {}, {}
    decisions = []
    for index, measurement in enumerate(measurements):
        boundary = index+1
        blocked = 'adjacent_clip_disabled' if (index+1 in disabled_clips or index+2 in disabled_clips) else (
                  'boundary_disabled' if boundary in disabled_boundaries else None)
        decision = dict(boundary=boundary, enabled=blocked is None,
                        exclusion_reason=blocked, speed_requested=local_speed,
                        duplicate_removal_requested=remove_duplicates,
                        speed_applied=False, duplicate_removed=False)
        if not blocked and local_speed and strength > 0 and measurement['suitable_for_speed_candidate']:
            before, after = measurement['before']['speed'], measurement['after']['speed']
            target = math.sqrt(before * after)
            left_a = strength * max(-0.8, min(0.8, target/before-1))
            right_a = strength * max(-0.8, min(0.8, target/after-1))
            left_w = min(window, clips[index].frames[-1]['source_seconds']/2)
            right_w = min(window, clips[index+1].frames[-1]['source_seconds']/2)
            if left_w > 0 and right_w > 0:
                tails[index], heads[index+1] = (left_w, left_a), (right_w, right_a)
                decision.update(speed_applied=True, left_alpha=left_a, right_alpha=right_a,
                                left_window_seconds=left_w, right_window_seconds=right_w,
                                speed_reason='candidate_requires_visual_review')
        if not decision['speed_applied']:
            decision['speed_reason'] = blocked or ('not_requested' if not local_speed else
                'zero_strength' if strength == 0 else measurement['reason'])
        decisions.append(decision)
    fps = clips[0].fps
    schedules = [local_schedule(clip, fps, heads.get(i), tails.get(i)) for i, clip in enumerate(clips)]
    for index, decision in enumerate(decisions):
        if decision['enabled'] and remove_duplicates and measurements[index]['duplicate_candidate']:
            right = schedules[index+1]
            # Remove the next source frame 0's CFR copies, never later static source frames.
            leading = next((i for i, frame in enumerate(right) if frame != 0), len(right))
            if 0 < leading < len(right):
                del right[:leading]
                decision.update(duplicate_removed=True, removed_source_frame=0,
                                retained_representative={'clip_id': clips[index].id,
                                                         'source_frame': len(clips[index].frames)-1},
                                removed_output_frames=leading)
        decision['duplicate_reason'] = decision['exclusion_reason'] or (
            'explicit_shared_endpoint_candidate' if decision['duplicate_removed'] else
            'not_requested' if not remove_duplicates else 'endpoint_not_similar_or_single_frame')
    return schedules, decisions


def analyze_rendered(path, report, window):
    """Measure the actual rendered candidate without assuming the schedule helped."""
    from .probe import probe
    clip = probe(path, 'rendered')
    ranges = []
    wanted = set()
    half = max(2, round(window * float(clip.fps)))
    for boundary in report['boundaries']:
        center = boundary['output_frame']
        sides = [list(range(max(0, center-half), center)),
                 list(range(center, min(len(clip.frames), center+half)))]
        sides = [[items[i] for i in np.unique(np.linspace(0, len(items)-1, min(16, len(items))).astype(int))]
                 for items in sides]
        ranges.append(sides)
        wanted.update(sides[0]+sides[1])
    images = {}
    for index, raw in enumerate(decode_frames(clip, 160, 96)):
        if index in wanted:
            images[index] = np.frombuffer(raw, np.uint8).reshape(96, 160, 3).copy()
    return [dict(boundary=i+1, before=_motion(clip, images, sides[0]),
                 after=_motion(clip, images, sides[1]),
                 seam_mae=float(np.mean(np.abs(images[sides[0][-1]].astype(float)-images[sides[1][0]]))))
            for i, sides in enumerate(ranges)]
