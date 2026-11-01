# M1–M3 independent technical verification

**Current verdict: v2.4 synthetic engineering acceptance passes.** Previous revision failures below are retained for traceability; the final section supersedes their snapshot verdicts. Real visual/generalization quality and Windows worker execution remain unverified.

Date: 2026-10-12. Separate verifier; no product edits. Frozen product SHA-256 identifiers and full measured rows: `outputs/motion-v2-independent/holdout.json`. The evaluator asserts that all eight product file hashes remain unchanged throughout its run.

## Direct executions

```powershell
.venv/Scripts/python.exe tests/verification/verify_motion_v2_holdout.py
.venv/Scripts/python.exe -m unittest tests.unit.test_motion_analysis tests.unit.test_motion_optimizer tests.unit.test_time_map tests.integration.test_internal_motion -v
.venv/Scripts/python.exe -m unittest tests.integration.test_motion_v2 -v
```

Both unittest runs passed: 14 existing/core tests and six v2 contract tests. This includes protected mapping, stretching/compression, monotonicity, composition bounds, endpoint selection, cut barriers, aspect ratio, stale/malformed profile rejection, source frame-grid binding, legacy reports, actual rendering and selection/exclusion regression. These are independent executions of implementation tests, supplemented by the independent holdout evaluator.

## Untouched holdout

Evaluated all 13 holdout clips from M0 (384×216, seed 81031 plus fixed case index) at target durations 4, 2.5 and 5 seconds, 0.5-second protection, 20 FPS. No thresholds were changed after results. Tried every proposed region to expose unsafe corrections.

- All 39 schedules preserve first/last source frames, protection, monotonicity, count and speed bound. No proposed region crosses a detected cut.
- Both repeated-frame and speed-jump fixtures produce suspicions: 2/2 detection recall. This is not proof of intent classification.
- All 39 schedules remain unchanged by v2: zero false corrections, but also zero demonstrated holdout correction benefit.
- Camera-shake median camera displacement error is 0.08934 source pixels/frame (gate 1.5). Object-only camera displacement error is 0.00003. Opposing-object analysis abstains on all 79 transitions; exposure has 12 illumination abstentions; scene cut is detected.
- Separate direct displacement checks (`object_errors.json`) give median object error 0.27672 pixels/frame for camera shake, 0.00200 for object-only, and 0.00373 for opposing objects. These support the 1.5-pixel synthetic separation gate; conflicting motion still abstains.
- Analysis wall time is 0.869–3.377 seconds per four-second clip on this concurrent run, below the frozen five seconds per video second gate. Whole-process peak memory for v2 was not measured in this independent run.

An additional direct holdout speed-jump trial at the calibration target of three seconds also makes no correction: `protected_interval_priority`. The detected merged region extends into the first 0.5 second, so protection safely blocks it. Decoding its rendered output confirms 60 frames / 3.0 seconds (`speed3.json` and `holdout_speed3.mp4`). This does not establish the 13.34% calibration improvement transfers to held-out footage. Do not report calibration proxy gain as independent ground-truth gain.

## Verdict and limits

M1 schema/compatibility and M2/M3 tested safety constraints pass. M2 synthetic camera separation is supported. M3 efficacy on the untouched holdout is **not demonstrated**, so the full improvement phase does not receive unconditional quality acceptance. The unchanged outputs are a safe fallback, not quality improvement. False suspicions on constant/intentional motion remain review overhead. Detection precision and unavailable subtype support must not be inferred from repeat recall.

The user confirms other-category real footage is unavailable. Real person, landscape/camera, product/static and fast-action generalization remains unavailable; synthetic tests do not satisfy it. Ship visual labels and paired quality review also remain distinct from technical checks. Windows QProcess worker execution is environment-blocked and was not passed here; UI data-level checks cannot replace it.

## v2.1 segmentation revision: returned for correction

Preserved independent evidence: `outputs/motion-v21-independent/holdout.json`, including frozen product hashes. Re-executed all 13 cases with the same gates at targets 4, 2.5, 5 and 3 seconds (52 schedules). Source protection, monotonicity, endpoints and speed constraints passed, but quality acceptance **failed**:

- Intended stop at three seconds produced six changed selections despite `do_not_correct` ground truth. A manually selected candidate is not evidence that the detector can distinguish intentional stops from defects.
- Repeated-frame target 2.5 seconds produced nine changed selections and only 5.568% independent whole-clip acceleration-variance reduction, below the frozen 10% gate. Its local tracking proxy acceptance must not be described as independent quality verification.
- Repeated-frame target three seconds improved analytic variance 17.028% with 19 changed selections, but this successful case does not override the failing gates.
- Speed-jump holdout remained blocked by the protected interval at all four targets; its efficacy remained unproven.

The combined regression rerun completed successfully: 22 tests in 89.836 seconds, including the selected-v2 full pipeline test (decoded 140-frame, seven-second combined output). Its Python modules were loaded for v2.1; this does not accept the next revision. The implementation owner was authorized to unfreeze after the holdout evidence had been saved; any subsequent state requires another check. Passing functional tests do not override the independent quality failures above.

## v2.3 final independent retest

Evidence and final product fingerprints: `outputs/motion-v23-independent/holdout.json`. Repeated the same 13 cases and four target durations with unchanged gates. Nine analysis/optimizer unit tests, five time-map tests and seven integration tests passed (21 total, 19.302 seconds), including actual full pipeline rendering and stale/tampered/legacy report checks.

All 52 schedules preserve protection, endpoints, monotonicity and speed bounds. Normal clips have zero changed selections. Repeated/ambiguous holds remain diagnostic-only even when submitted for correction, fixing the intentional-stop failure. Repeat/speed-jump review recall remains 2/2. No cut crossing occurs. Maximum measured analysis time was 2.212 seconds per four-second clip.

Speed-jump holdout at three seconds now changes nine source selections and reduces independently measured whole-clip acceleration variance **13.341%**, with full displacement retained and fewer repeats. A separate direct render of that exact holdout schedule decodes to 60 frames / 3.0 seconds (`speed3.mp4`, `decoded.json`). Thus there is a demonstrated synthetic holdout benefit.

However, at 2.5 seconds the accepted candidate changes seven selections and achieves **9.600%** independent reduction, below the frozen 10% gate. The optimizer's local proxy does not guarantee the independent whole-clip metric. This remains an explicit efficacy gate failure; the threshold was not relaxed and this candidate was not relabeled as passing. Other target lengths safely produce no change.

Final verdict for this snapshot: functional and safety checks pass; synthetic benefit demonstrated in the three-second example; **full M3 quality acceptance remains incomplete** due to the 2.5-second proxy discrepancy and unavailable real quality evidence. Review-only operation with no automatic application is material to this assessment.

## v2.4 final acceptance and remaining limits

Final frozen product identifiers and independent measurements: `outputs/motion-v24-independent/holdout.json`. The generic scoring repair supplies full-source interval-ending motion context, validates it against the source timeline, and scores the whole output rather than clamping motion outside the candidate region. The 10% gate was unchanged. Bounded candidate search accounts for discrete source-frame selection changes.

Directly reran all 13 holdout cases at four target durations: 52 schedules. No product hashes changed during the run. Normal cases remain unchanged, ambiguous holds are refused, cuts are not crossed, repeat/speed-jump detection recall is 2/2, and protection/endpoints/monotonicity/speed bounds all pass. Only the three-second speed-jump case is accepted: nine changed selections, **13.341% independently measured acceleration-variance reduction**, full movement extent preserved, repeat fraction reduced by 3.390 percentage points. The formerly failing 2.5-second case now returns no correction. All accepted candidates satisfy the unchanged independent quality gates on this set.

Independently rendered the exact accepted holdout schedule and decoded it: **60 frames, 3.0 seconds**, first/last source selections 0/79. Evidence: `speed3.mp4` and `decoded.json` in the final output directory. Maximum analysis time was 2.539 seconds per four-second clip. Camera/object separation algorithm is unchanged from the independently measured passing displacement cases.

Final command `.venv/Scripts/python.exe -m unittest tests.unit.test_motion_analysis tests.unit.test_motion_optimizer tests.unit.test_time_map tests.integration.test_motion_v2 -v` passes **23 tests in 25.264 seconds**, including full pipeline rendering, old-report compatibility, context/timeline tampering rejection, and protection. Earlier failed snapshots and their outputs were preserved.

Verdict: **tested synthetic M1–M3 functional, safety and accepted-candidate quality gates pass**. This means one demonstrated synthetic correction plus conservative rejection elsewhere; it is not a broad estimate of real quality. Whole-process v2 memory was not independently measured in this verifier run (refer to implementer environment evidence separately). Real ship human visual approval, other-category real generalization and Windows QProcess execution remain separate outstanding evidence. Repeated frames are flagged but intentionally not corrected because intent is unknown. No automatic correction is enabled.
