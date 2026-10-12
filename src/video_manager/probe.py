"""Display-order frame identities and exact timestamps from ffprobe."""
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
import json

from .errors import InputError, ToolError
from .tools import run_tool


@dataclass
class Clip:
    id: str
    path: Path
    width: int
    height: int
    fps: Fraction
    time_base: Fraction
    frames: list[dict]
    duration: float
    has_audio: bool
    vfr: bool
    sample_aspect_ratio: Fraction

    def metadata(self):
        return {"id": self.id, "path": str(self.path), "width": self.width,
                "height": self.height, "fps": str(self.fps), "time_base": str(self.time_base),
                "duration_seconds": self.duration, "has_audio": self.has_audio,
                "vfr": self.vfr, "sample_aspect_ratio": str(self.sample_aspect_ratio),
                "first_pts": self.frames[0]["pts"], "frames": self.frames}


def probe(path: Path, clip_id: str) -> Clip:
    try:
        data = json.loads(run_tool(["ffprobe", "-v", "error", "-show_streams", "-show_frames",
                                    "-of", "json", str(path)], timeout=120).stdout)
    except (ToolError, json.JSONDecodeError) as exc:
        raise InputError(f"Cannot read media {path}: {exc}") from exc
    streams = data.get("streams", [])
    videos = [s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")]
    if not videos:
        raise InputError(f"No video stream: {path}")
    stream = videos[0]
    try:
        tb = Fraction(stream["time_base"])
        try:
            fps = Fraction(stream.get("avg_frame_rate", "0/1"))
        except (ValueError, ZeroDivisionError):
            fps = Fraction(0)
        if fps <= 0:
            fps = Fraction(stream["r_frame_rate"])
        if fps <= 0:
            raise ValueError("invalid frame rate")
        frames = []
        for frame in data.get("frames", []):
            if frame.get("stream_index") != stream["index"]:
                continue
            pts = int(frame.get("best_effort_timestamp", frame.get("pts")))
            absolute = Fraction(pts) * tb
            if frames and absolute <= Fraction(frames[-1]["pts"]) * tb:
                raise ValueError("non-increasing display timestamps")
            frames.append({"source_frame": len(frames), "pts": pts,
                           "pts_seconds": float(absolute),
                           "duration_seconds": float(frame.get("duration_time", frame.get("pkt_duration_time", 0)))})
        if not frames:
            raise ValueError("no decoded frames")
        first = Fraction(frames[0]["pts"]) * tb
        for frame in frames:
            frame["source_seconds"] = float(Fraction(frame["pts"]) * tb - first)
        tail = frames[-1]["duration_seconds"] or float(1 / fps)
        duration = frames[-1]["source_seconds"] + tail
        deltas = [frames[i]["pts"] - frames[i-1]["pts"] for i in range(1, len(frames))]
        sar = Fraction(stream.get("sample_aspect_ratio", "1:1").replace(":", "/"))
        if sar <= 0:
            sar = Fraction(1)
        return Clip(clip_id, path, int(stream["width"]), int(stream["height"]), fps,
                    tb, frames, duration, any(s.get("codec_type") == "audio" for s in streams),
                    bool(deltas and max(deltas) - min(deltas) > 1), sar)
    except (ValueError, KeyError, TypeError, ZeroDivisionError) as exc:
        raise InputError(f"Unsupported video timestamps/metadata: {path}: {exc}") from exc
