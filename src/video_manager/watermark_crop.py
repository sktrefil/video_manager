"""One stable, aspect-preserving crop avoiding all configured logo rectangles.

Regions are explicit presets or user annotations, not automatic logo detections.
The crop is chosen once for the entire clip, including stabilization movement.
"""
from itertools import combinations
import math

import cv2
import numpy as np

from .errors import InputError


DEFAULT_REGIONS = (
    (.87875, 5 / 6 - .05, .055, .10),  # existing Gemini location
    (.75, .905, .24, .065),            # Hailuo / MINIMAX wordmark
)


def validate_regions(regions):
    if not isinstance(regions, (list, tuple)) or len(regions) > 8:
        raise InputError('워터마크 영역은 최대 8개까지 지정할 수 있습니다.')
    result = []
    for region in regions:
        if not isinstance(region, (list, tuple)) or len(region) != 4:
            raise InputError('워터마크 영역은 [x, y, 너비, 높이] 형식이어야 합니다.')
        if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in region):
            raise InputError('워터마크 영역 좌표는 유한한 숫자여야 합니다.')
        x, y, w, h = region
        if min(x, y) < 0 or min(w, h) <= 0 or x + w > 1 + 1e-9 or y + h > 1 + 1e-9:
            raise InputError('워터마크 영역은 화면 안에 있어야 합니다.')
        result.append([float(v) for v in region])
    return result


def plan_crop(width, height, regions=None, *, transforms=None, clip=None):
    """Find the largest target-aspect rectangle disjoint from all logo bounds."""
    regions = validate_regions(DEFAULT_REGIONS if regions is None else regions)
    fitted_w, fitted_h = float(width), float(height)
    if clip is not None:
        display_w = clip.width * float(clip.sample_aspect_ratio)
        scale = min(width / display_w, height / clip.height)
        fitted_w, fitted_h = display_w * scale, clip.height * scale
    left, top = (width - fitted_w) / 2, (height - fitted_h) / 2
    margin = max(2, math.ceil(max(width, height) * .003))
    matrices = np.asarray(transforms, dtype=float) if transforms is not None else None
    boxes = []
    for x, y, w, h in regions:
        x0, y0 = left + x * fitted_w, top + y * fitted_h
        x1, y1 = x0 + w * fitted_w, y0 + h * fitted_h
        corners = np.array([[x0, y0, 1], [x1, y0, 1], [x0, y1, 1], [x1, y1, 1]])
        points = corners[:, :2]
        if matrices is not None and matrices.size:
            moved = np.einsum('nij,kj->nki', matrices, corners).reshape(-1, 2)
            points = np.concatenate([points, moved])
        x0 = max(0, math.floor(float(points[:, 0].min())) - margin)
        y0 = max(0, math.floor(float(points[:, 1].min())) - margin)
        x1 = min(width, math.ceil(float(points[:, 0].max())) + margin)
        y1 = min(height, math.ceil(float(points[:, 1].max())) + margin)
        if x0 < x1 and y0 < y1:
            boxes.append((x0, y0, x1, y1))
    xs = sorted({0, width, *(edge for b in boxes for edge in (b[0], b[2]))})
    ys = sorted({0, height, *(edge for b in boxes for edge in (b[1], b[3]))})
    best = None
    for x0, x1 in combinations(xs, 2):
        for y0, y1 in combinations(ys, 2):
            if any(x0 < bx1 and x1 > bx0 and y0 < by1 and y1 > by0 for bx0, by0, bx1, by1 in boxes):
                continue
            scale = min((x1 - x0) / width, (y1 - y0) / height)
            cw, ch = math.floor(width * scale + 1e-8), math.floor(height * scale + 1e-8)
            if min(cw, ch) < 2:
                continue
            # Center the retained view as far as the excluded logos allow.
            cx = max(x0, min(x1 - cw, round((width - cw) / 2)))
            cy = max(y0, min(y1 - ch, round((height - ch) / 2)))
            distance = ((cx + cw / 2 - width / 2) / width) ** 2 + ((cy + ch / 2 - height / 2) / height) ** 2
            score = (cw * ch, -distance)
            if best is None or score > best[0]:
                best = (score, [cx, cy, cw, ch])
    if best is None:
        raise InputError('지정한 워터마크 영역을 피할 수 없습니다. 영역을 더 작게 지정하세요.')
    rect = best[1]
    return dict(rect=rect, excluded_boxes=[list(b) for b in boxes], regions=regions,
                retained_area_fraction=rect[2] * rect[3] / (width * height),
                zoom=max(width / rect[2], height / rect[3]), margin_pixels=margin,
                method='largest_aspect_crop', selection='configured_regions',
                stabilization_envelope=matrices is not None)


def apply_crop(frame, plan):
    x, y, w, h = plan['rect']
    height, width = frame.shape[:2]
    if (x, y, w, h) == (0, 0, width, height):
        return frame
    return cv2.resize(frame[y:y + h, x:x + w], (width, height), interpolation=cv2.INTER_LANCZOS4)
