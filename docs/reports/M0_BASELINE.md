# M0: frozen baseline and evaluation contract

Date: 2026-10-12 (Asia/Seoul). Status: synthetic baseline measured; real-world validation pending. Independent verification is required before phase sign-off.

## Reproduction and preserved state

Run from repository root:

```powershell
.venv/Scripts/python.exe tests/fixtures/motion_benchmark.py --output outputs/motion-m0
```

The command imports the preserved package in `outputs/motion-m0/baseline/video_manager`, never the evolving engine in `src`. `baseline_hashes.json` identifies every copied Python module. `fixtures_manifest.json` links encoded input SHA-256, seed, dimensions, FPS, split, semantic labels and per-frame known positions. `baseline_results.json` retains detected regions and complete before/after source-frame schedules. These schedules reproduce the old correction without having to infer its parameters from output pixels. Local `outputs` files are ignored by Git and must be retained with the handoff; the command deliberately fails if the frozen engine copy is missing. Baseline is motion-v1, default options.

The benchmark replaces only its generated fixture MP4s when rerun. It does not change production clips. Runtime numbers change on rerun; encoded hashes and analysis IDs should not change on the same FFmpeg build.

## Frozen engineering gates

`outputs/motion-m0/acceptance_gates.json` was written before M1–M3 implementation. These are acceptance requirements, not claims of achieved quality. Calibration seed is 1729; holdout seed is 81031. Cases add their fixed index to the seed. Calibration is 320×180, holdout 384×216, both 80 frames at 20 FPS. Holdout must not be used to tune thresholds; a failed gate stays a failed gate.

| Requirement | Gate |
| --- | --- |
| Corrections to normal labeled clips | 0 |
| Corrections spanning a cut | 0 |
| Synthetic repeated-frame/speed-jump detection recall | ≥75% |
| Median camera/object separation error | ≤1.5 source pixels/frame |
| Selected temporal candidate acceleration variance improvement | ≥10% |
| Movement extent retained | ≥95% |
| Additional repeated output frame fraction | ≤2 percentage points |
| Output duration error | ≤1 output frame |
| Endpoint/protection/monotonicity failures | 0 |
| CPU analysis wall time | ≤5 seconds per video second |
| Python peak resident memory | ≤1 GiB; child encoders excluded |

These small synthetic sets are regression and feasibility gates. They are not a statistically powered estimate of generalization. Precision/recall by semantic type is unavailable from v1, which only emits `repeat_or_hold` and `speed_change` suspicions. New versions must report subtype support/abstention honestly, rather than treating every suspicion as a correct defect classification.

## Fixture matrix and interpretation

Both splits include constant motion, intentional acceleration, intentional stop, camera shake, object-only movement, opposing objects, occlusion, repeated frames, exposure variation, scene cut, low texture, large motion, and a speed jump. Ground truth includes rendered object positions and continuous underlying positions separately, camera offsets and visibility. Repeated frames record the position of the actual copied frame.

Intentional stopping and repeated frames can be observationally indistinguishable. Their labels encode author intent for evaluating false correction risk; pixels alone do not establish that intent. A correct system may flag both for review and must not claim automatic intent recognition. No fixture is automatically selected in a user job. The benchmark deliberately tries all detected regions to expose unsafe candidates and records protection skips.

## Actual baseline measurements

26 clips / 104 video seconds: 29.05 seconds total fixture generation + probing + analysis + scheduling; analysis only 15.76 seconds. Python peak RSS 69,083,136 bytes. Windows 10 build 19045, Intel family 6 model 158, 6 logical CPUs, Python 3.11.4, OpenCV 4.11.0, NumPy 2.2.3, FFmpeg 8.1.2. CPU path only. Full tool paths and versions are in `environment.json`. CIM hardware inventory was access denied; physical RAM capacity and CPU marketing name were not collected. Peak RSS excludes FFmpeg children, and no GPU/VRAM use was measured.

22/26 clips produce review suspicions. Both camera-shake clips and both large-motion clips produce none. All four repeated-frame/speed-jump fixtures produce a suspicion, but this is not semantic discrimination: constant motion and intentional acceleration also produce suspicions. Trying every proposed region changes frames in only the two exposure-variation clips (8 and 16 changed frame selections); other candidates are skipped or select unchanged frames. This is a concrete unsafe proposal case for the next implementation to prevent, not proof of quality improvement.

Every saved schedule preserves endpoint selection, monotonicity and the first 0.5-second protected interval, with exactly 80 output frames. These are schedule-level checks; this run does not validate final rendered/decoded duration. No spatial camera estimate exists in v1, so separation error is unavailable. No full rendered synthetic candidate or human visual quality approval was produced in M0. Ground-truth acceleration variance is recorded per case; it is not used as a sole acceptance score and does not prove absence of visual artifacts.

## Real ship sample handoff and pending data

`real_ship_regions.json` selects five evenly spaced entries across the existing detector report, without selecting on measured improvement. The report path and SHA-256, source path/hash, complete region evidence and IDs are preserved. Original and proposal previews remain linked in the original `outputs/motion-review-63f72b9e/results/motion_report.json`.

| Clip | Source interval (seconds) |
| --- | --- |
| 01-02.mp4 | 9.10–9.958 |
| 03-01.mp4 | 1.40–2.20 |
| 03-03.mp4 | 5.00–6.80 |
| 03-04.mp4 | 4.20–5.40 |
| 04_02.mp4 | 0.00–0.80 |

These are unreviewed suspicions, not verified defects. Ship normal/problem labels (minimum two each), same-target-duration original/baseline/new renders and human assessment remain pending. Real person, landscape/camera movement, product/static structure and fast-action examples also remain pending, with minimum two normal and two problem regions per category. Synthetic clips do not replace these requirements. M0 establishes a reproducible engineering baseline; broad production-quality claims are blocked until this evidence exists.
