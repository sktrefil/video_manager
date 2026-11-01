# M4 / M5 independent verification

**Current result: tested synthetic component and combined technical gates pass on the final frozen snapshot, using the work order's matched encoding comparison. The four-real-clip 640-pixel preview artifact audit also passes.** See [final acceptance](#final-same-codec-control-independent-acceptance) and [real artifact audit](#four-real-clip-preview-artifact-audit). Historical failing snapshots and evaluator-reference corrections below are retained. Real-domain visual quality, user approval and the Windows GUI worker path remain unverified.

Date: 2026-10-12. Separate verifier; no product edits. Acceptance contract: `docs/MOTION_PHASE2_VALIDATION.md`; fixture generation was frozen before product evaluation. Prior outputs are retained across fixes.

## Initial frozen snapshot: M4 passes, M5 returned

Direct commands:

```powershell
.venv/Scripts/python.exe tests/verification/verify_motion_phase2.py --output outputs/motion-phase2-independent-v1 --adapter phase2_product_adapter
.venv/Scripts/python.exe -m unittest tests.unit.test_interpolation tests.unit.test_stabilization tests.integration.test_enhancements -v
```

All 12 implementation unit/integration tests passed in 26.590 seconds. Independent adapter results and product SHA-256 values are in `outputs/motion-phase2-independent-v1/results.json`, which confirms files remained unchanged during evaluation.

M4 independent synthetic acceptance passes: six of nine clean cases actually interpolate, meeting the predeclared minimum of six. Horizontal/vertical translations have MAE below 0.001 RGB level against analytic intermediate truth and sharpness ratios effectively 1.0. The three diagonal translations are conservatively rejected as scene cuts; their exact nearest-frame fallback is preserved, but this is an efficacy limitation. Cut, occlusion and low-confidence guards fall back exactly. Low-confidence/cut metadata is passed through the real product `interpolation_guard`; occlusion is evaluated by the real backend. The representative `interpolation_comparison.png` was visually inspected: thin grid lines remain sharp, with no visible doubling in the accepted midpoint image. This simple synthetic inspection is not real-world ghosting validation.

M5 fails the frozen efficacy criterion: the known camera-shake fixture is entirely rejected as `scene_cut`; applied=false and output/input shake RMS ratio is 1.00353 (required ≤0.5 with actual application). Preserving every frame cannot count as stabilization efficacy. Pan velocity and zoom preservation pass, endpoint pixels remain exact, and no crop or uncovered border occurs because the feature abstains.

A separate actual two-clip render uses encoded shake and pan fixtures, each retimed to four seconds with both enhancements on. Decoding confirms 160 frames / eight seconds. Explicitly disabled enhancement output exactly matches the legacy mapping and decoded pixels. The enabled shake clip interpolates 21 frames but stabilizes zero, so this is not successful combined-feature efficacy. Full audit and videos: `outputs/motion-phase2-integration-independent-v1/`.

The implementation owner received the false scene-cut finding and was authorized to unfreeze only after measurements were saved. A separately identified EOF/decoder-exit validation fix also requires integration retest. No acceptance threshold was relaxed.

## v1.1 retest: stabilization effective, detail gate still fails

Same fixtures and unchanged gates, new outputs `outputs/motion-phase2-independent-v11/` and `outputs/motion-phase2-integration-independent-v11/`. Both runs record product hashes; no product files changed during verification. Actual combined rendering is reproducible with:

```powershell
.venv/Scripts/python.exe tests/verification/verify_motion_phase2_render.py outputs/motion-phase2-integration-independent-v11
```

M4 retains its passing six-of-nine applied result and exact unsafe fallback. M5 now applies on the shake fixture: output shake RMS is **0.31792** of input (68.2% reduction), actual crop **2.6417%** within the configured 5%, inverse-transform coverage valid, endpoints exact, no black borders. Intentional pan and zoom remain unchanged.

However, the minimum output/source Laplacian sharpness ratio is **0.77321**, below the frozen **0.80** floor. Therefore M5 overall acceptance still **fails**, despite passing motion reduction. Ordinary Lanczos resampling does not automatically establish acceptable detail preservation. The gate was not relaxed and the result is not marked passed based only on smoothness.

All 13 implementation tests passed in 38.352 seconds. Independent combined rendering decodes to 160 frames / eight seconds; disabled output exactly matches legacy decoded pixels and mappings; pre-encode first/last/protected bytes are exact. On the shake clip 76 frames are spatially transformed and 18 interpolated; pan remains spatially unchanged with 76 interpolated frames. This verifies both effects genuinely execute together, while the separate detail-quality failure remains open.

## v1.2 isolated pass, combined quality failure

Unchanged component fixtures/gates were rerun against a frozen snapshot. `outputs/motion-phase2-independent-v12/results.json` records file hashes and unchanged state. M4 passes six-of-nine efficacy and unsafe fallback. M5 now passes its component gate: shake RMS ratio **0.31796**, minimum source-relative sharpness **0.84632**, crop **2.6417%**, exact endpoints and unchanged intentional pan/zoom. All 14 implementation tests passed in 43.431 seconds.

The stronger real-render composition test, declared before its first quality evaluation, then encoded three clips (shake/pan/zoom), retimed each to four seconds and independently registered decoded images against the analytic scene. `outputs/motion-phase2-integration-independent-v12/audit.json` preserves exact hashes and all output mappings. All 240 decoded frames / 12 seconds, disabled equality and protected endpoints pass. However, **combined quality fails**:

| Clip | Motion result | Minimum sharpness vs analytic corresponding view | Minimum vs same-timeline nearest baseline |
| --- | --- | --- | --- |
| Shake | RMS ratio 0.31566; passes | **0.43627; fails 0.80** | 0.55446 |
| Pan | Velocity relative error 0.00072; passes | **0.69411; fails 0.80** | 0.69152 |
| Zoom | Scale error 0.00021; passes | 0.88908; passes | 0.94419 |

Shake has 76 spatially transformed and 17 interpolated frames; pan/zoom each have 76 interpolated frames. This is a real composition/detail loss, not merely no-op fallback. The analytic reference accounts for output affine pose and fractional sampling, and the nearest-baseline comparison also shows substantial degradation. Isolated tests cannot certify combined processing. No threshold was changed, and full phase-2 quality acceptance remains withheld pending remediation/retest. Product files were unchanged during both independent runs.

### Attribution diagnostic on retained v1.2 artifacts

The unenhanced source itself has minimum decoded/analytic sharpness 0.67783 for shake, 0.85408 for pan and 0.92587 for zoom. Thus the absolute analytic comparison includes inherited source sampling/encoding loss. Per the documented evaluator correction, pose-normalized detail retention divides candidate/analytic by same-time baseline/analytic, without changing the 0.80 floor. Off/self is exactly 1.0. On the retained old combined outputs this still fails: shake 0.41870, pan 0.75105, zoom 0.94540. Diagnostic data: `detail_diagnostic.json` and `detail_normalized_diagnostic.json` beside the retained renders.

A stabilization-only render further isolates effects: minimum pre-encode transformed/received-source sharpness is **0.85355**, while decoded stabilization-only/decoded-off is **0.78062**. Pose-normalized stabilization-only is 0.45547. This discrepancy shows analytic pose normalization can still attribute unrecoverable phase-dependent source detail to the transform; the diagnostic must not be described as proof that the spatial reconstructor itself removes 55% of received detail. The direct source-relative measurement passes, while the encoded and composition checks remain explicit. All numbers and earlier verdicts are retained; no hidden threshold change or post-hoc unconditional pass is made.

## Single-pass composition snapshot: direct-source quality still fails

Product frozen for all runs; component outputs in `outputs/motion-phase2-independent-singlepass/`, combined outputs in `outputs/motion-phase2-integration-independent-singlepass/`. Both isolated components pass. All 16 implementation tests pass in 52.310 seconds. Combined decode remains 240 frames / 12 seconds with exact disabled mapping/pixels and protected endpoints.

The analytic-reference issue above was adjudicated explicitly: use the original contract's corresponding **received source** floor 0.80 both before encoding and after decoding versus the disabled output. Analytic values remain diagnostics, not attributable loss. The original audit is preserved; the corrected source-reference verdict is saved separately in `source_reference_verdict.json` with pre-encode values in `preencode_source_detail.json`.

| Clip | Pre-encode / received source | Decoded / decoded off | Motion | Verdict |
| --- | --- | --- | --- | --- |
| Shake | **0.64040** | **0.68320** | RMS ratio 0.31603, passes | Fails detail |
| Pan | 0.84194 | **0.74788** | Relative velocity error 0.00010, passes | Fails encoded detail |
| Zoom | 0.96971 | 0.96367 | Scale error 0.00018, passes | Passes |

The shake failure occurs before encoding, so codec fidelity alone cannot resolve it. Pan pre-encode retention passes but encoded retention fails. The new single-pass path improves the previous result but still does not meet full composition acceptance. No product edits were made by this verifier and no quality threshold was relaxed.

## CPU-flow v1.2 plus enhanced CRF 1 snapshot

Fresh outputs: `outputs/motion-phase2-independent-final/` and `outputs/motion-phase2-integration-independent-final/`. Names reflect the intended candidate, not an acceptance claim. Component gates pass and all 19 implementation tests pass in 51.127 seconds. Product hash checks confirm the tested files did not change during evaluation.

Received-source detail retention improves: shake pre-encode **0.80972** passes, pan **0.97603** and zoom **0.99882** pass. Decoded pan **0.96837** and zoom **0.94224** also pass. However, decoded shake is **0.76403**, still below 0.80. Thus full acceptance remains **failed at the encoding/output stage**. Shake RMS ratio 0.31584, pan velocity error 0.00058 and zoom scale error 0.00056 pass. Output remains 240 frames / 12 seconds with exact disabled and protected-frame behavior.

Representative decoded images at output frames 24, 111 and 208 were inspected (`independent_samples.png`): no obvious double grid lines or uncovered borders. That inspection does not override the measured failing detail floor. Clean enhanced encoding uses CRF 1 while legacy/off uses CRF 18; clarity changes due to encoding must not be claimed as optical-motion algorithm improvements. No thresholds changed.

## Final same-codec control: independent acceptance

The work order explicitly requires matching encoding conditions. A direct diagnostic of the formerly failing output frame 40 found pre-encode/source sharpness **0.87217**, decoded/pre-encode **1.01678**, and legacy CRF18 baseline/source **1.16070**. The old 0.76403 ratio therefore used a ringing-inflated, different-codec denominator. The independent peer replay also found byte-exact lossless RGB output fails against that same CRF18 denominator (0.75142), confirming this is not missing codec fidelity. Peer evidence: `outputs/motion-phase2-codec-peer-review.json`.

Encoded a separate unprocessed control at the **same CRF1 profile and source schedule** as the frozen candidate; no product files changed and every product hash matches the recorded final audit. All three clips now satisfy the unchanged **0.80** pre-encode and matched-codec retention gates:

| Clip | Pre-encode / received source | Decoded / matched-codec control | Motion preservation/reduction |
| --- | --- | --- | --- |
| Shake | 0.80972 | **0.80677** | RMS ratio 0.31584; passes |
| Pan | 0.97603 | **0.96672** | Velocity error 0.00058; passes |
| Zoom | 0.99882 | **0.99627** | Scale error 0.00056; passes |

Final verdict evidence: `outputs/motion-phase2-integration-independent-final/matched_codec_verdict.json` and `matched_codec_off.mp4`. The original mismatched-codec audit and all failed revisions are preserved. The reproducible runner now automatically creates the matched control, retains legacy-off exact-equivalence checks, saves both metrics, and raises on quality failure. This is reference attribution repair required by the work order, not a threshold relaxation or claim of recovering detail absent from the source.

Verified final behavior: 240 decoded frames / 12 seconds, exact pre-encode first/last/protected frames, disabled decoded-pixel and mapping equivalence, source provenance, nonzero stabilization plus interpolation on the shake clip, and 19 passing implementation tests. Synthetic visual samples show no obvious doubling or uncovered borders. The comparison set is small; diagonal interpolation still conservatively falls back. CPU reconstruction is expensive and enhanced CRF1 files are larger. Real ship visual quality, other-domain generalization and Windows QProcess worker execution remain separate unverified items; UI configuration tests do not substitute for a functioning worker. No product code was edited by the verifier.

## Four-real-clip preview artifact audit

Direct execution:

```powershell
.venv/Scripts/python.exe tests/verification/verify_real_motion_phase2.py outputs/motion-phase2-real/20261012T093216428064Z
```

Passed. Independent results are saved as `independent_verification.json` in that directory. Current product hashes match the producer's before/after hashes; original source, every video, mapping, matched-codec control and comparison montage hashes match. Independently probed all four variants per clip and their montages; checked source endpoints, monotone mapping, protected intervals and adjacent-frame interpolation provenance. All previews are **640 pixels wide**, not native-resolution output validation.

| Original | Output frames / target | Interpolated source-output frames | Spatially stabilized frames |
| --- | --- | --- | --- |
| 01-02.mp4 | 72 / 3 seconds | 7 | 0 |
| 03-01.mp4 | 72 / 3 seconds | 0 | 0 |
| 03-03.mp4 | 120 / 5 seconds | 16 | 0 |
| 03-04.mp4 | 72 / 3 seconds | 0 | 0 |

The interpolation and combined variants have the same applied counts. These counts were cross-checked against frame metadata and the producer's pre-encoding hash attribution; the independent verifier did not rerender all real effects. Independent decoding against matched controls finds 55 and 71 changed decoded frames for the two affected clips, because inter-frame coding propagates pixel differences. Those values must not be described as 55/71 interpolated frames. Unchanged variants decode identically to their controls.

Stabilization declined all real examples (unknown/intentional zoom for the first, unreliable camera model for the others); no real stabilization improvement is claimed. Independent inspection of representative comparison stills for 01-02 and 03-03 found no obvious newly doubled structures or borders, but stills cannot establish temporal naturalness. Actual visual quality remains pending user review. Synthetic efficacy is demonstrated separately, and there is no universal real-domain or native-resolution acceptance claim.
