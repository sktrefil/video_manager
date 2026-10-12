"""Boundary-centered F2 comparison with one clock and no extra retiming."""
from fractions import Fraction
from pathlib import Path

from PIL import Image, ImageDraw

from .probe import probe
from .render import Encoder, decode_frames


def compare_boundaries(output: Path, baseline: dict, corrected: dict, window: float,
                       prefixes=None,output_prefix="comparison",labels=None,windows=None):
    fps = Fraction(baseline['fps'])
    width, height = baseline['width'], baseline['height']
    half = max(1, round(window * float(fps)))
    comparisons = []
    for index, (left_boundary, right_boundary) in enumerate(zip(baseline['boundaries'], corrected['boundaries']), 1):
        half = max(1, round((windows[index-1] if windows is not None else window) * float(fps)))
        centers = [left_boundary['output_frame'], right_boundary['output_frame']]
        reports = [baseline, corrected]
        prefixes = prefixes or ['baseline', 'corrected']
        labels = labels or ['baseline', 'corrected']
        generators = [decode_frames(probe(output / f'{prefix}_diagnostic.mp4', prefix), width, height) for prefix in prefixes]
        positions = [-1, -1]
        name = f'{output_prefix}_boundary_{index:02d}.mp4'
        encoder = Encoder(output / name, width*2, height+24, fps)
        rows = []
        failed = True
        try:
            for relative_frame in range(-half, half+1):
                canvas = Image.new('RGB', (width*2, height+24), 'black')
                draw = ImageDraw.Draw(canvas)
                row = {'relative_frame': relative_frame, 'relative_seconds': relative_frame/float(fps)}
                for side in range(2):
                    wanted = centers[side]+relative_frame
                    in_range = 0 <= wanted < reports[side]['frame_count']
                    if in_range:
                        raw = None
                        while positions[side] < wanted:
                            raw = next(generators[side])
                            positions[side] += 1
                        canvas.paste(Image.frombytes('RGB', (width, height), raw), (side*width, 24))
                        row[labels[side]] = reports[side]['mapping'][wanted]
                    else:
                        draw.text((side*width+3, 50), 'OUT OF RANGE', fill='white')
                        row[labels[side]] = None
                    draw.text((side*width+3, 2), f'{labels[side]} rel {relative_frame/float(fps):+.3f}s', fill='white')
                encoder.write(canvas.tobytes())
                rows.append(row)
            failed = False
        finally:
            for generator in generators:
                generator.close()
            encoder.close(failed)
        comparisons.append(dict(boundary=index, video=name, fps=str(fps),
                                boundary_frame_in_comparison=half, mapping=rows))
    return comparisons
