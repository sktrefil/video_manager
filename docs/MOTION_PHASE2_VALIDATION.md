# Phase 2 independent validation contract (M4 / M5)

Frozen 2026-10-12 before implementation evaluation. Owner: independent verifier, no product code edits. These gates may not be relaxed after evaluation. Synthetic acceptance is not real visual/generalization acceptance. Existing ship footage is the available real source; other categories remain unavailable.

## Fixtures and measurement

`tests/verification/verify_motion_phase2.py` creates analytically translated textured images from a larger image, known intermediate images, cut/occlusion pairs, and known camera trajectories. Calibration seed 251004; held-out seed 991027. Integer endpoint translation and analytically rendered fractional intermediates prevent comparison against the implementation's own flow. The texture combines seeded detail with thin high-contrast lines. Scoring excludes a fixed 12-pixel outer border, declared before measurement. Fixtures are 240×160; translations include horizontal, vertical and diagonal motion at fractions 0.25, 0.5 and 0.75.

Interpolation is compared with nearest source-frame selection, not frame blending. MAE measures misplaced detail/ghosting, while Laplacian variance bounds loss of sharpness and oversharpening. Independent inspection of representative images supplements these imperfect numerical proxies.

Stabilization is measured from the known trajectory and an independently estimated output translation relative to the static reference. The intentional trajectory is a linear pan or smooth zoom. Shake uses zero endpoint offsets and a high-frequency sinusoidal disturbance. Both translation and rendered images are checked; a declared transform alone is insufficient evidence of success.

## Frozen gates

| Gate | Requirement |
| --- | --- |
| Clean interpolation efficacy | At least 6 of 9 clean cases applied; each applied case MAE ≤75% of nearest baseline and ≤12 RGB levels |
| Interpolation sharpness | Laplacian variance ratio against analytic truth between 0.80 and 1.25 on scored interior |
| Ghosting/detail | Above MAE/edge gates plus saved truth/nearest/candidate image inspection; do not infer absence of ghosts from temporal smoothness |
| Cut / occlusion / low-confidence | All declared unsafe cases fall back; fallback pixels exactly equal the nearest source frame |
| Endpoint / protected samples | Pixel-identical source images before lossy encoding; no interpolation or spatial modification in protected samples |
| Stabilization efficacy | Translation shake RMS after stabilization ≤50% of uncorrected RMS on the interior 80% of frames; must actually apply on a clean shake fixture |
| Crop budget | At most 8% of width/height per edge; report actual bound and reject cases exceeding it; no uncovered/black regions |
| Intended pan | Fitted pan velocity within 10% of original; residual translation change ≤0.5 pixel/frame in constant-pan fixture |
| Intended zoom | Fitted scale trajectory within 1% absolute scale of source; no spatial correction required on smooth zoom |
| Spatial image quality | Sharpness ratio ≥0.80 relative to corresponding source/analytic view; no unexplained static-frame distortion |
| Disabled features | Exact source selection and pre-encode RGB equality with phase-1 path; no settings silently enabled by legacy JSON |
| Combined output | Each clip and entire decoded timeline within one output frame of target; first/last/protected source references traceable; interpolation bracket and fraction reported |
| Failure / cancellation | No successful result from incomplete output; predictable fallback recorded; no partial output replaces original |
| Resource claim | Record wall time and peak memory with scope; no fixed speed claim without measurement |

An implementation that rejects every case does not pass efficacy. A feature may remain experimental/unavailable when these gates fail; retain failed results rather than changing the thresholds. Full real quality approval is distinct from synthetic technical acceptance.

## Handoff and integration

Before tests, freeze product file SHA-256 values and configuration. The runner has an adapter boundary so calling conventions can follow the final implementation without changing fixture data or thresholds. Adapter output must expose applied/fallback state and actual RGB images. Integration additionally calls the real renderer and configuration parser for default/off equivalence, legacy roundtrip, time mapping, two-clip combined processing, errors and cancellation. Unit-level adapter results do not substitute for real rendering.

The initial runner without `--adapter` only writes fixtures and gates; it must be reported **not evaluated**, never passed. Independent evaluation begins after a fixed implementation handoff. Each revision uses a new output directory and retains prior failures.

Combined-render extension (declared before combined quality evaluation): use three encoded clips (shake, pan, zoom), each retimed to four seconds. Independently register decoded output to recover its affine pose, then render a one-pass analytic view of the known larger texture at that pose. The unchanged 0.80 spatial sharpness floor is measured against this corresponding analytic view; also report the nearest-source baseline ratio as context, since fractional sampling phases naturally change high-frequency energy. Shake RMS is compared to the same-output-timeline decoded uncorrected baseline on the interior 80%; pan velocity and zoom scale are compared to that baseline. `verify_motion_phase2_render.py` checks 240 decoded frames / 12 seconds, exact pre-encode protected endpoints and disabled-output equality. This supplements the isolated component gates; passing only frame counts is insufficient.

Reference correction after v1.2 diagnostic (threshold unchanged): unenhanced decoded shake itself has sharpness/analytic ratio 0.67783, proving the absolute analytic ratio includes inherited source sampling/encoding loss. The product is evaluated for **detail retention** using `(candidate sharpness / analytic at candidate pose) / (same-time baseline sharpness / analytic at baseline pose)` with the original floor **0.80**. Keep and report the absolute analytic and raw nearest ratios as well. Off-vs-off must evaluate to exactly 1.0. This corrects attribution of unavailable source detail; it does not lower the retention threshold or remove the failing previous extra-blur evidence. Isolated component gates are unchanged. The correction is documented before evaluating any subsequent product revision.

Final reference adjudication after stabilization-only diagnostic: pose normalization still assumes recovery of latent frequencies already lost by input sampling (0.45547 normalized versus 0.85355 actual pre-encode received-source retention). It therefore cannot attribute transform damage. Restore the original contract's **corresponding source** definition consistently: both pre-encode candidate/received decoded source and decoded candidate/decoded off must retain **≥0.80** sharpness. Keep analytic/normalized ratios as diagnostics only, including the original failing values and reference correction history. Motion efficacy still uses independent registration. No threshold is lowered; old v1.2 and single-pass results still fail direct-source gates, so this correction does not turn an observed failure into a pass. New runner outputs explicitly name this reference policy.

Encoding control clarification: the work order requires identical target length, FPS **and encoding conditions** for comparisons. After enhanced clean output switched to CRF 1, the legacy disabled CRF 18 output remained an exact-behavior regression reference, but could no longer be the optical/detail-quality denominator. The final runner additionally encodes the same source schedule without effects at the enhanced profile and requires candidate/control ≥0.80, alongside pre-encode candidate/received-source ≥0.80. Independent diagnostic showed CRF18 baseline/source energy 1.16070 at the formerly failing frame (ringing), while CRF1 post/pre energy was 1.01678. A lossless RGB control also failed against the mismatched CRF18 baseline, independently confirming this attribution error. Preserve both metrics; do not attribute codec changes to optical improvement. Final runner writes all evidence then exits unsuccessfully if any combined quality gate fails.
