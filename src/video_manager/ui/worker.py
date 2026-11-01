"""Separate process/session for engine work and graceful Linux cancellation."""
import os
import sys


def main():
    from video_manager import progress
    progress.enabled=True
    progress.report('Preparing inputs')
    if os.name=='posix':
        os.setsid()
    from video_manager.cli import main as cli_main
    print('WORKER_READY',flush=True)
    return cli_main(sys.argv[1:])


if __name__=='__main__':
    raise SystemExit(main())
