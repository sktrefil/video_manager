# Independent Clip Output Implementation Plan

> **For agentic workers:** Implement inline in the current workspace; preserve unrelated existing edits.

**Goal:** Let the desktop UI shorten one or more clips independently and save a separate output for each clip without building a joined video.

**Architecture:** Add an `independent_clips` job setting with a default of `false`. When enabled, the job runner processes each clip through the existing single-clip retiming pipeline, publishes each clip as a separate file in one result folder, and writes an aggregate report for the UI.

**Tech Stack:** Python 3.12, PySide6, existing job schema and retiming pipeline.

**Spec:** User request in this conversation, confirmed as option 2.

## Global Constraints

- Keep existing joined processing behavior when the checkbox is off.
- Support at least one clip when independent processing is on.
- Do not modify the user's separate launcher script.
- Do not add or run tests in this change.

## Review Focus

- One clip in independent mode must pass job validation.
- Multiple clips must produce separate files and no joined `corrected.mp4`.
- Existing jobs without the setting must keep joined mode.
- Audio mode and enhancement settings must carry through to each clip.
- Unsupported narration or motion selections must fail clearly rather than silently misapply.

## Files

- `src/video_manager/ui/app.py`: add and persist the independent-processing checkbox; list individual results for playback.
- `src/video_manager/job_schema.py`: normalize the setting, allow one clip in this mode, and run per-clip jobs under one aggregate output directory.
- `src/video_manager/retime.py`: permit a single clip for the per-file subjobs.
- `README.md`: document the mode and resulting files.

## Implementation

- Add an opt-in checkbox, default off, and include it in saved job JSON.
- Validate that independent jobs have at least one clip and reject incompatible narration or selected motion-region settings.
- Reserve one output directory, render each clip into an isolated child job, move each final file to the top-level `results` folder, and write an aggregate report.
- Make the UI result viewer open each independent output and show per-clip timings.
- Run syntax checks and inspect the final diff; do not run tests.
