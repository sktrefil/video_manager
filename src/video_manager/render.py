"""CFR rendering with bounded frame memory and explicit source selection."""
from bisect import bisect_left
from fractions import Fraction
from pathlib import Path
import subprocess
import tempfile

from PIL import Image, ImageDraw

from .errors import ToolError
from .probe import Clip
from .tools import run_tool


def frame_schedule(clip: Clip, fps: Fraction) -> list[int]:
    count = max(1 if len(clip.frames) == 1 else 2, round(clip.duration * float(fps)))
    times = [f["source_seconds"] for f in clip.frames]
    selected = []
    for index in range(count):
        time = index / float(fps)
        right = bisect_left(times, time)
        if right == 0:
            chosen = 0
        elif right == len(times):
            chosen = len(times) - 1
        else:
            chosen = right - 1 if time - times[right - 1] <= times[right] - time else right
        selected.append(chosen)
    selected[0] = 0
    selected[-1] = len(times) - 1
    return selected


class Encoder:
    def __init__(self, output: Path, width: int, height: int, fps: Fraction):
        self.log = tempfile.TemporaryFile()
        self.process = subprocess.Popen([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
            "-r", str(fps), "-i", "pipe:0", "-an", "-c:v", "libx264", "-threads", "2",
            "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output)
        ], stdin=subprocess.PIPE, stderr=self.log, stdout=subprocess.DEVNULL)

    def write(self, data):
        try:
            self.process.stdin.write(data)
        except BrokenPipeError as exc:
            raise ToolError("FFmpeg encoder closed its input unexpectedly") from exc

    def close(self, failed=False):
        try:
            if failed:
                self.process.kill()
            else:
                self.process.stdin.close()
            code = self.process.wait(timeout=60)
            if code and not failed:
                self.log.seek(0)
                raise ToolError(f"FFmpeg encoder failed: {self.log.read().decode(errors='replace')[-2000:]}")
        finally:
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait()
            self.log.close()


def decode_frames(clip: Clip, width: int, height: int):
    # Convert sample aspect ratio to square pixels before fitting/padding.
    filtergraph = (f"scale=trunc(iw*sar/2)*2:ih,setsar=1,"
                   f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
                   f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,format=rgb24")
    with tempfile.TemporaryFile() as log:
        proc = subprocess.Popen(["ffmpeg", "-v", "error", "-nostdin", "-threads", "2", "-i", str(clip.path),
                                 "-map", "0:V:0", "-an", "-vf", filtergraph, "-filter_threads", "1",
                                 "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"],
                                stdout=subprocess.PIPE, stderr=log, stdin=subprocess.DEVNULL)
        try:
            size = width * height * 3
            while True:
                data = proc.stdout.read(size)
                if not data:
                    break
                if len(data) != size:
                    raise ToolError(f"Truncated decoded frame: {clip.path}")
                yield data
            if proc.wait(timeout=60):
                log.seek(0)
                raise ToolError(f"Decode failed: {log.read().decode(errors='replace')[-2000:]}")
        finally:
            proc.stdout.close()
            if proc.poll() is None:
                proc.kill()
                proc.wait()


def overlay(data: bytes, width: int, height: int, row: dict) -> bytes:
    image = Image.frombytes("RGB", (width, height), data)
    draw = ImageDraw.Draw(image)
    lines = [f"{row['clip_id']} src#{row['source_frame']}",
             f"src t={row['source_seconds']:.3f}s",
             f"out#{row['output_frame']} t={row['output_seconds']:.3f}s"]
    draw.rectangle((0, 0, width, 40), fill="black")
    draw.text((3, 1), '\n'.join(lines), fill="white")
    return image.tobytes()


def render_clips(clips: list[Clip], output: Path, schedules=None, prefix="baseline", output_fps=None) -> dict:
    first = clips[0]
    width = max(2, round(first.width * float(first.sample_aspect_ratio) / 2) * 2)
    height = max(2, round(first.height / 2) * 2)
    fps = Fraction(str(output_fps)) if output_fps is not None else first.fps
    mapping, boundaries, clip_ranges = [], [], []
    clean = Encoder(output / f"{prefix}.mp4", width, height, fps)
    diagnostic = None
    failed = True
    try:
        diagnostic = Encoder(output / f"{prefix}_diagnostic.mp4", width, height, fps)
        for ci, clip in enumerate(clips):
            schedule = schedules[ci] if schedules is not None else frame_schedule(clip, fps)
            start = len(mapping)
            cursor = 0
            for source_index, data in enumerate(decode_frames(clip, width, height)):
                while cursor < len(schedule) and schedule[cursor] == source_index:
                    frame = clip.frames[source_index]
                    row = {"output_frame": len(mapping), "output_seconds": len(mapping) / float(fps),
                           "clip_id": clip.id, "source_frame": source_index,
                           "source_seconds": frame["source_seconds"], "pts": frame["pts"],
                           "pts_seconds": frame["pts_seconds"], "time_base": str(clip.time_base)}
                    clean.write(data)
                    diagnostic.write(overlay(data, width, height, row))
                    mapping.append(row)
                    cursor += 1
            if cursor != len(schedule):
                raise ToolError(f"Decoded frame count does not satisfy schedule: {clip.path}")
            clip_ranges.append({"clip_id": clip.id, "start_frame": start, "end_frame": len(mapping)})
            if ci:
                boundaries.append({"from": clips[ci - 1].id, "to": clip.id, "output_frame": start,
                                   "output_seconds": start / float(fps)})
        failed = False
    finally:
        try:
            clean.close(failed)
        finally:
            if diagnostic:
                diagnostic.close(failed)
    return {"fps": str(fps), "width": width, "height": height, "frame_count": len(mapping),
            "duration_seconds": len(mapping) / float(fps), "mapping": mapping,
            "boundaries": boundaries, "clip_ranges": clip_ranges}


def boundary_segments(output: Path, report: dict, prefix="baseline", window=0.5, windows=None):
    fps = float(Fraction(report["fps"]))
    half = max(1, round(window * fps))
    for number, boundary in enumerate(report["boundaries"], 1):
        half = max(1, round((windows[number-1] if windows is not None else window) * fps))
        center = boundary["output_frame"]
        start, end = max(0, center - half), min(report["frame_count"], center + half)
        name = f"{prefix}_boundary_{number:02d}.mp4"
        run_tool(["ffmpeg", "-v", "error", "-nostdin", "-n", "-i", str(output / f"{prefix}_diagnostic.mp4"),
                  "-vf", f"trim=start_frame={start}:end_frame={end},setpts=PTS-STARTPTS", "-an",
                  "-r", report["fps"], "-fps_mode", "cfr", "-c:v", "libx264", "-threads", "2", "-pix_fmt", "yuv420p", str(output / name)], timeout=120)
        boundary.update(segment=name, segment_start_frame=start, segment_end_frame=end,
                        boundary_seconds_in_segment=(center - start) / fps)
