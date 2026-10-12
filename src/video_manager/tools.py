"""Bounded, shell-free external tool execution."""
import shutil
import subprocess

from .errors import ToolError


def run_tool(args: list[str], *, timeout: float = 30) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                                check=False, stdin=subprocess.DEVNULL)
    except FileNotFoundError as exc:
        raise ToolError(f"Required tool not found: {args[0]}") from exc
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ToolError(f"Tool could not complete: {args[0]}: {exc}") from exc
    if result.returncode:
        raise ToolError(f"{args[0]} failed ({result.returncode}): {result.stderr[-2000:].strip()}")
    return result


def diagnose() -> dict:
    report = {}
    for name in ("ffmpeg", "ffprobe"):
        path = shutil.which(name)
        if path is None:
            raise ToolError(f"Required tool not found: {name}; install FFmpeg and add it to PATH")
        result = run_tool([path, "-version"])
        report[name] = {"path": path, "version": result.stdout.splitlines()[0]}
    encoders = run_tool([report["ffmpeg"]["path"], "-hide_banner", "-encoders"]).stdout
    if not any(len(fields := line.split()) > 1 and fields[1] == "libx264"
               for line in encoders.splitlines()):
        raise ToolError("FFmpeg encoder libx264 is required but unavailable")
    report["encoder"] = "libx264"
    return report
