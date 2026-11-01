"""Optional worker progress; ordinary CLI output stays unchanged."""
import json
import time

enabled = False
_last = ('', 0.0)


def report(stage, done=0, total=0, *, completed_video=None):
    global _last
    if not enabled:
        return
    now = time.monotonic()
    if completed_video is None and stage == _last[0] and done not in (0, total) and now - _last[1] < .5:
        return
    _last = (stage, now)
    event=dict(stage=stage, done=done, total=total)
    if completed_video is not None:event['completed_video']=str(completed_video)
    print('VM_PROGRESS ' + json.dumps(event), flush=True)
