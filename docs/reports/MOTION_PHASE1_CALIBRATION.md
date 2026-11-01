# Phase 1 calibration: final motion-components-v2.4

## Current frozen result: v2.4, 2026-10-12

Final artifacts: `outputs/motion-phase1/20261012T082546616643Z/`. All earlier runs remain preserved. `summary.json` confirms unchanged code during execution and unchanged M0 gate hash. This calibration run reads no holdout footage. The independent verifier owns holdout findings.

V2.4 uses full-clip motion context with frame-interval speed integration, evaluates whole-output acceleration improvement, and checks local non-regression. It refuses ambiguous holds rather than inferring the creator's intent. Missing full context or forged interval durations are rejected when loading reports. These are structural corrections to the measurement and safety model; the M0 thresholds were not weakened.

| Module | Final SHA-256 |
| --- | --- |
| internal_motion.py | d27adbb8440c70ac3d71c428952195ff644acb92d6264a513696d578b0282082 |
| motion_analysis.py | 924fc95204c2961cba63ec63e27727213a24ec151877f80a34eeb32ee1b6b6ee |
| motion_optimizer.py | 574a0d0b66a56cc884bef562eea462280faaab3ef4bd265af23cd0d281fe5bc0 |
| time_map.py | 9e40a44971fbbcc2d11ef515b5d4f6d942972626145adb31c79d5e2e4e3aae84 |

Final calibration: v2 normal changed-selection rate **0/6**, v1 **1/6**; temporal-suspicion recall **2/2** for both; no schedule invariant failures. Intentional stop and repeated-frame cases remain review candidates with unchanged schedules. On speed_jump at a 3-second target and 0.5-second protection, v2 changes 9 selections and achieves **13.34% independent rendered-position acceleration-variance improvement**, 100% movement extent and zero added source-index repeats. Decoded output is 60 frames/3 seconds. The final video hash equals the earlier candidate, despite the corrected objective and stricter rejection rules. Normal-correction, suspicion-recall, schedule, cut-crossing and runtime gates pass on calibration; that is not a broad quality approval.

Final analysis runtime: v1 **7.54 s**, v2 **21.44 s**, for 52 seconds of calibration input. Total including renders/probes: **38.55 s**. Python peak RSS: **48,054,272 bytes** (children excluded). Other verification ran concurrently; treat runtime as an observation, not isolated throughput.

Final integration: **7 tests passed in 20.824 s**, including actual 140-frame/7-second two-clip `retime()` output with a selected candidate, exports, protection/endpoints, historical v1 loading, integrity/version rejection and missing/full-context interval tampering rejection. Exact commands and artifact layout below remain applicable.

No new real footage is requested as part of this handoff. Generalization to missing nonship categories and human visual approval remain unverified and must be reported as limitations. This calibration document does not supersede the independent verifier's final verdict.

## Preserved historical result: v2.1 (superseded)

Date: 2026-10-12 (Asia/Seoul). This is implementation-side calibration evidence, not independent holdout sign-off or human visual approval.

## Reproduction and exact state

```powershell
.venv/Scripts/python.exe tests/fixtures/run_motion_phase1.py --output outputs/motion-phase1
.venv/Scripts/python.exe -m unittest discover -s tests/integration -p test_motion_v2.py -v
```

Final artifacts: `outputs/motion-phase1/20261012T081550798144Z/`. Earlier timestamp directories remain intact. Report schema is `motion-v2`; analyzer identity is `motion-components-v2.1`. `summary.json` records every engine module hash and confirms `code_stable_during_run: true`. Frozen M0 gates SHA-256: `c578c3ad5553a627a9adcddbe0412b0a12fb4fc4a3deecbd11f98b34ca0623e9`.

| Module | SHA-256 |
| --- | --- |
| internal_motion.py | b0d55d69e53e0246c71fb1805257d9e552de6c769b868966d6aca8206b50d924 |
| motion_analysis.py | 6fa349aa39ab39ae88b57fa214cc15a19a39928cf78a5b715b819da91415bf2d |
| motion_optimizer.py | 770fc3b311de565c0cecc0932bdf2a598f90425b7ddeadc148451584c9a3b085 |
| time_map.py | 9e40a44971fbbcc2d11ef515b5d4f6d942972626145adb31c79d5e2e4e3aae84 |

Only the 13 calibration fixtures were read and run. Holdout execution belongs to the independent verifier. Input hashes are recorded per case; encoded fixtures are preserved under M0.

## Measured calibration results

| Measure | v1 | v2.1 |
| --- | --- | --- |
| Normal labeled clips with changed selections | 1/6 | 0/6 |
| Repeat/speed-jump cases with review suspicion | 2/2 | 2/2 |
| Endpoint/protection/monotonicity failures | 0 | 0 |
| Analysis time, 52 seconds of input | 14.53 s | 35.04 s |

V1's normal correction is the exposure-change fixture. V2 abstains on it. Suspicions are review candidates, not automatically applied edits or proof of author intent. The repeat and intentional-stop cases remain ambiguous.

For the speed-jump clip compressed to 3 seconds with 0.5 seconds protected, v2 selects a changed candidate with 9 altered source selections. The independent synthetic rendered-position ground truth gives acceleration variance **2.067776 → 1.791914 (13.34% reduction)**. Movement extent is 100%; added repeated source-index fraction is zero. The decoded result has 60 frames and duration 3.0 seconds. This meets the frozen ≥10% acceleration improvement, ≥95% extent, ≤2 percentage-point additional repeat and duration gates for this candidate. It is not the optimizer's own tracked-distance score.

The scene cut at 2.0 seconds is detected, and v2 emits no temporal region spanning it. Camera-shake displacement median error is approximately 0.085 source pixels/frame (gate ≤1.5); low-texture footage provides no valid background-camera estimate and remains unmeasured. These measurements do not establish all categories' camera/object separation accuracy.

V2 passes the evaluated calibration gates: zero normal corrections, ≥75% temporal-suspicion recall, no invariant failures, no cut-spanning region, and ≤5 analysis seconds per video second. The v1 cut-crossing counter is not informative because v1 has no cut diagnostics. This is not an all-gates/generalization pass.

Peak Python RSS: 48,123,904 bytes, below the 1 GiB engineering budget; FFmpeg children excluded. Total run: 76.75 seconds including rendering/probing. Integration checks ran concurrently, so these are observed contention timings, not isolated throughput benchmarks. Hardware/tool context is recorded in the M0 environment artifact.

## Render and pipeline evidence

The `repeated_frames`, `speed_jump`, `exposure_change` and `scene_cut` subdirectories contain same-target-length `original.mp4`, `motion-v1.mp4` and `motion-v2.mp4` plus diagnostic versions and analysis reports. `original` denotes the neutral target-duration reference; for speed_jump it is compressed to the same 3-second target. It is not the untouched source-speed clip. Render hashes/frame counts/durations are recorded in `results.json`.

Final integration suite: **7 tests passed in 37.347 seconds**. The full `retime()` test explicitly selects a v2 speed candidate, joins its 3-second result to a 4-second normal clip, and verifies actual decoded 140 frames/7 seconds, 60/80-frame clip exports, protected first 0.5 seconds, source endpoints, monotonic source selections and identity selection for the normal clip. Other tests cover historical real v1 report loading, v1/v2 selection/exclusion, hash/version/analyzer binding, malformed or forged source-grid rejection, cut boundaries, and no-improvement fallback.

## Limits and remaining approval

`real_ship_inventory_pending_review.json` carries five representative real ship regions and source/report hashes. This calibration run does not re-render or visually approve those regions. Real ship normal/problem labeling and nonship person, landscape, product/static and fast-action validation remain pending. No human visual pass or deformation-repair capability is claimed. Frame interpolation, spatial stabilization and flicker correction are later phases. The independent verifier must separately report holdout results and defects; this document cannot substitute for that review.
