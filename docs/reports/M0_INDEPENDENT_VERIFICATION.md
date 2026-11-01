# M0 independent verification

Date: 2026-10-12. Verifier: separate verification agent; no product code edits.

Verdict: reproducible synthetic baseline passes. Full M0 real-world evidence remains **verification pending**, not a quality pass. Product M1–M3 was not part of this frozen verification.

Copied the frozen baseline package into `outputs/motion-m0-independent/baseline`, then directly ran:

```powershell
.venv/Scripts/python.exe tests/fixtures/motion_benchmark.py --output outputs/motion-m0-independent
```

Independent generation and analysis completed successfully for all 26 fixtures. A separate comparison command asserted identical encoded input SHA-256 values, region records, original/candidate schedules, changed-frame counts, endpoint/protected-frame/monotonicity results, acceptance gates and baseline module hashes. All assertions passed. Analysis IDs include absolute paths, so IDs between distinct output directories were intentionally not equated. Independent Python peak RSS: 69,292,032 bytes; child processes excluded.

Verification found and returned a fixture defect before handoff: repeated-frame truth used frame 30's position while injected images copied frame 29. Implementer corrected this and distinguished rendered positions from continuous trajectories; independent assertions confirm injected frame positions now match frame 29. Final script/gate/snapshot hash-file identifiers are recorded in `outputs/motion-m0-independent/verified_state.json`.

The evaluation split, predeclared engineering gates and fixed engine snapshot exist. Both calibration and holdout have the 13 required synthetic categories, encoded source hashes and per-frame analytic truth. Observationally identical intended stops and repeated frames cannot establish intent; detection recall must be treated as review suspicion recall, not permission for automatic correction.

Outstanding required evidence: decoded full candidate rendering, equal-target comparison videos and human labels for ship normal/problem samples; person, landscape/camera, product/static and fast-action real categories. The manifest/report explicitly identify these as pending. Synthetic reproduction does not replace them. Baseline gates describe future requirements; this v1 baseline is not claimed to satisfy them. UI QProcess startup/integration was not verified here.
