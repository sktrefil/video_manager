"""Command line entry point; processing commands are added stage by stage."""
import argparse
import json
import sys

from . import __version__
from .errors import VideoManagerError
from .pipeline import baseline, boundaries, job_directory, validate_inputs
from .tools import diagnose


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Inspect shared-frame video clips without modifying originals.")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Check FFmpeg, ffprobe and libx264")
    prepare = commands.add_parser("prepare", help="Validate paths and reserve an isolated job (no video processing yet)")
    prepare.add_argument("clips", nargs="+", help="Input files in playback order")
    prepare.add_argument("--output", required=True, help="New job directory; existing paths are rejected")
    base = commands.add_parser("baseline", help="Render clean baseline, frame diagnostics and boundary segments")
    base.add_argument("clips", nargs="+", help="Input clips in playback order (at least two)")
    base.add_argument("--output", required=True, help="New job directory")
    boundary = commands.add_parser("boundaries", help="Analyze boundaries and render explicit correction candidates")
    boundary.add_argument("clips", nargs="+")
    boundary.add_argument("--output", required=True)
    boundary.add_argument("--window", type=float, default=0.5, help="Boundary window seconds: (0, 2]")
    boundary.add_argument("--strength", type=float, default=0.3, help="Local speed strength: [0, 1]")
    boundary.add_argument("--local-speed", action="store_true", help="Request conservative local time mapping candidates")
    boundary.add_argument("--remove-duplicates", action="store_true", help="Explicitly remove the next repeated source endpoint and its CFR copies")
    boundary.add_argument("--disable-clip", type=int, action="append", default=[], help="1-based clip index; repeatable")
    boundary.add_argument("--disable-boundary", type=int, action="append", default=[], help="1-based boundary index; repeatable")
    retiming = commands.add_parser("retime", help="Protect initial action and smoothly compress the remainder to target durations")
    retiming.add_argument("clips", nargs="+")
    retiming.add_argument("--output", required=True)
    retiming.add_argument("--targets", type=float, nargs="+", required=True)
    retiming.add_argument("--protect", type=float, nargs="+", default=[1.0], help="Initial protected seconds; default 1 per clip")
    retiming.add_argument("--max-speed", type=float, nargs="+", default=[12.0])
    retiming.add_argument("--ramp", type=float, nargs="+", default=[0.5], help="Smooth acceleration transition seconds")
    retiming.add_argument("--window", type=float, default=0.5)
    retiming.add_argument("--strength", type=float, default=0.3)
    retiming.add_argument("--local-speed", action="store_true")
    retiming.add_argument("--remove-duplicates", action="store_true")
    retiming.add_argument("--disable-clip", type=int, action="append", default=[])
    retiming.add_argument("--disable-boundary", type=int, action="append", default=[])
    retiming.add_argument("--audio-mode", choices=["mute"], default="mute")
    retiming.add_argument("--motion-report", action="append", default=[])
    retiming.add_argument("--select-region", action="append", default=[])
    retiming.add_argument("--exclude-region", action="append", default=[])
    inspection=commands.add_parser("inspect-motion",help="Find internal motion suspicions and render unselected proposal previews")
    inspection.add_argument("clips",nargs="+")
    inspection.add_argument("--output",required=True)
    inspection.add_argument("--freeze-seconds",type=float,default=.2)
    inspection.add_argument("--change-ratio",type=float,default=2.5)
    inspection.add_argument("--window",type=float,default=.4)
    runjob=commands.add_parser("run-job",help="Validate and execute a version-1 JSON job")
    runjob.add_argument("job")
    runjob.add_argument("--output",help="Override output with a new directory")
    validatejob=commands.add_parser("validate-job",help="Read-only JSON, media, timing, and provenance checks")
    validatejob.add_argument("job")
    validatejob.add_argument("--output")
    commands.add_parser("gui",help="Launch optional PySide6 desktop interface")
    args = parser.parse_args(argv)
    try:
        if args.command == "gui":
            try:
                from .ui.app import main as gui_main
            except ModuleNotFoundError as exc:
                raise VideoManagerError("Install optional UI dependencies: pip install -r requirements-ui.txt") from exc
            return gui_main()
        elif args.command == "doctor":
            print(json.dumps(diagnose(), indent=2))
        elif args.command in ["run-job","validate-job"]:
            from .job_schema import load_job,run_job,validate_job
            if args.command=="run-job":
                print(f"JSON job: {run_job(args.job,args.output)}")
            else:
                _,validation=validate_job(load_job(args.job),args.output)
                print(json.dumps(validation,indent=2))
        elif args.command == "inspect-motion":
            from .internal_motion import inspect_motion
            result=inspect_motion(args.clips,args.output,dict(freeze_seconds=args.freeze_seconds,
                change_ratio=args.change_ratio,window_seconds=args.window))
            print(f"Internal motion review: {result}")
        elif args.command == "retime":
            from .retime import retime
            result = retime(args.clips,args.output,targets=args.targets,protect=args.protect,
                max_speed=args.max_speed,ramp=args.ramp,window=args.window,strength=args.strength,
                local_speed=args.local_speed,remove_duplicates=args.remove_duplicates,
                disabled_clips=args.disable_clip,disabled_boundaries=args.disable_boundary,audio_mode=args.audio_mode,
                motion_reports=args.motion_report,selected_regions=args.select_region,excluded_regions=args.exclude_region)
            print(f"Retimed job: {result}")
        elif args.command == "boundaries":
            result = boundaries(args.clips, args.output, window=args.window, strength=args.strength,
                local_speed=args.local_speed, remove_duplicates=args.remove_duplicates,
                disabled_clips=args.disable_clip, disabled_boundaries=args.disable_boundary)
            print(f"Boundary candidate job: {result}")
        elif args.command == "baseline":
            print(f"Baseline job: {baseline(args.clips, args.output)}")
        elif args.command == "prepare":
            inputs = validate_inputs(args.clips)
            tools = diagnose()
            with job_directory(args.output, inputs) as job:
                (job.work / "preparation.json").write_text(json.dumps(
                    {"inputs": [str(p) for p in inputs], "tools": tools,
                     "scope": "Path validation only; media decoding and rendering are not implemented in A1"},
                    indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"Prepared job: {job.root}")
        return 0
    except VideoManagerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
    except OSError as exc:
        print(f"error: I/O failure: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("error: Cancelled", file=sys.stderr)
        return 130
