# Audit Fix Handoff for Claude

Date: 2026-09-22

## Outcome

Implemented fixes for all ten findings in `AUDIT_REPORT_2026-09-22.md`, added
18 passing regression tests, and updated usage and agent instructions. Changes
are local and uncommitted. The original audit is preserved as historical evidence.

**Outstanding validation:** Real-photo inference and reporting ran, but writing
the required JPG overlay was denied by the environment, including on the
permission-escalated retry. Full real-photo export and new-overlay visual review
are therefore incomplete. Do not interpret this handoff as an accuracy certificate
or a fully passed real-photo acceptance test.

## Files Changed

| File | Purpose |
|---|---|
| `rock_gradation.py` | Calculation fixes, argument checks, reliable exports, provenance |
| `tests/test_rock_gradation.py` | New standard-library unittest regression suite |
| `.claude/gradation_run.py` | Replaced source-string patching with ordinary CLI delegation |
| `.claude/commands/gradation.md` | Updated workflow, removed extension/rename workaround, added fit-status checks |
| `README.md` | Current usage, schema changes, limitations, test command |
| `CLAUDE.md` | Current architecture and contracts for subsequent work |
| `AGENTS.md` | Updated structure and test instructions; already existed as an untracked file |
| `FIX_REPORT_2026-09-22.md` | This handoff |

No source photos, historical analysis outputs, example assets, model weights,
or dependency declarations were intentionally changed. No packages were installed.

## Fixes Mapped to the Audit

| Audit finding | Implementation and evidence |
|---|---|
| 1. Invented oversize below fit threshold | Unsupported RR fitting now yields an explicit measured fallback. The 30–48 mm synthetic sample reports 100% passing at 1,200 mm and 0% breaker material, instead of 7.93%. |
| 2. `--fines none` still corrected values | A shared `report_distribution()` supplies passing and quantiles. Disabled correction preserves the measured curve, splits, bands, and empirical quantiles. The old 20.91% passing at 10 mm becomes the measured 0%. |
| 3. Child mask double counting | Parent coverage uses the union of intersecting child pixels; exact duplicate masks are excluded from group counting. Both 30%-area and 60%-area duplicate-child cases retain the parent. Distinct children still replace a genuinely covered group. |
| 4. Invalid combined JSON and ambiguous IDs | Strict JSON uses null for combined scale/coverage and unavailable fit values. CSV export IDs are unique; source photo, original label, and weight are retained. Combined CLI behavior is covered using mocked analysis and real report exports. |
| 5. Output overwrites | Preflight rejects colliding stems, including the reserved combined output prefix. Existing outputs require explicit `--overwrite`. Checks occur before inference. |
| 6. Ignored write failures | Encoding failures and filesystem errors raise errors. Reports are staged and checked before publication; success is printed only after publication. Injected encoding and permission failures leave no published partial report. The real environment write failure was also surfaced. |
| 7. Invalid numeric arguments | Finite positive scales/lengths, confidence, dimensions, threshold ordering, ROI coordinates, and distinct pole endpoints are checked. Image-dependent bounds are checked before inference. |
| 8. Incorrect custom-band destinations | Bypass and breaker thresholds are inserted into band boundaries; a 350 mm breaker threshold splits 300–400 into crusher 300–350 and breaker 350–400. |
| 9. Minimum size used area alone | The chosen physical metric is checked after perspective correction. A separate 15-pixel floor remains for resolution. The 11.26 mm elongated fragment is rejected under a 30 mm minor-axis minimum. |
| 10. Silent assumed RR fit | `fit_rr()` returns status, reason, nullable parameters, and fit residual RMSE. Insufficient data, optimizer errors, and invalid covariance no longer fabricate parameters. Measured fallback is explicit in console, JSON, CSV, and chart labels. |

## Important Behavior and Compatibility Changes

- JSON now has `schema_version: 2`. Consumers must tolerate null RR parameters
  and passing-fit values. `fines_requested` is separate from effective
  `fines_correction`; inspect `warnings` and `rosin_rammler.status`.
- Passing remains strictly `size < sieve`; breaker includes equality. Retained
  bands are lower-inclusive and upper-exclusive. Threshold-dependent bands mean
  consumers should not assume a fixed row count or fixed band strings.
- D-values now use weighted empirical thresholds rather than interpolation
  between observed sizes. Corrected fines retain the analytical RR inverse.
  For equal-weight 100 and 500 mm fragments, D60 is now 500 mm, not 180 mm.
  Passing at the exact threshold can be below the percentile because passing is
  strict; immediately above that threshold it reaches or exceeds it.
- The unrounded quantiles calculate Cu, avoiding division by a rounded zero.
- Fragment CSV `id` now means export row identity. Use `source_label` to match
  the segmentation label and `source_image` to locate its image. Pixel coordinates
  use that image's working resolution; JSON supplies working/original dimensions.
- JSON includes settings, package/Python versions, calibration details, source
  paths and input SHA-256 hashes, oversize count, and `accuracy_validated: false`.
  It records the requested model name/path, but does not hash model weights.
- Unicode image reading uses byte loading plus OpenCV decoding. Writing uses
  checked encoding and ordinary filesystem writes to the actual JPG target.
  The wrapper no longer patches source, changes cwd, or bypasses JPG failures.
- Overlay colors now follow bypass/crusher/breaker destinations, including custom
  thresholds. Old example overlays are historical and use the older legend.
- Writes are staged per report, with JSON published last. Multiple renames are
  **not a single atomic transaction**. A publish-time failure can leave some
  files updated, and earlier completed photos can remain after a later batch
  failure. Concurrent writers to the same destination are not supported.

## Validation Performed

Final regression command:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

**Result: 18 tests passed.** Tests cover the listed numerical regressions,
distribution bounds/monotonicity, percentile boundaries, split/band totals,
mask overlap/deduplication, metric/perspective filtering, invalid options,
collisions, existing outputs, combined metadata, strict JSON, fragment identity,
actual CSV/JSON/PNG chart exports in temporary folders, and injected write failures.
Synthetic/mocked cases do not load FastSAM or prove physical accuracy.

`git diff --check` passed with only Git's line-ending notices. The compatibility
wrapper's `--help` command passed. No build step or external test framework is required.

### Real-photo smoke test: partial, blocked at JPG write

Inspected `stockpile_picture/09182026.jpg`: pole visible; upper bench background
motivated the existing 20% top exclusion. Ran:

```powershell
.\.venv\Scripts\python.exe -B rock_gradation.py stockpile_picture/09182026.jpg --roi 0,0.2,1,0.8 --out output/audit-fixes-2026-09-22
```

Inference and console reporting completed on two attempts. The intermediate
implementation reported 424 fragments, about 3.131 mm/pixel, a fitted RR curve,
about 29.2% breaker material, and five oversize fragments. These are execution
observations only, not accepted production measurements or final-version visual
validation. The final duplicate-mask guard and source-hash addition were made
after these runs started; the final regression suite includes those changes.

Both attempts failed with `PermissionError` while creating the staged
`09182026_overlay.jpg`, including the escalated retry. No extension substitution
or rename workaround was attempted. Staging cleanup left the dedicated smoke
output directory empty, preserving old outputs. New overlays and real-photo
chart/table agreement could not be visually verified.

### Tested environment

Python 3.14.3; NumPy 2.5.3; SciPy 1.18.1; OpenCV package 5.0.0.93;
Ultralytics 8.4.157; Matplotlib 3.11.2; PyTorch 2.14.0.

These are installed environment observations, not newly pinned dependencies.

## Next Steps for Claude

1. Read `AGENTS.md` and the updated `CLAUDE.md`, then review the diff and run the
   18 tests. Keep the historical audit and original assets intact.
2. Resolve JPG-write permission through the normal environment/administrator
   route. Do not restore the old extension/rename workaround.
3. Rerun the smoke command with the final code in a fresh output directory.
   Inspect every overlay for pole exclusion, background leakage, missing rocks,
   split rocks, and merged rocks; inspect the chart and exported tables too.
4. Before production adoption, compare representative photos with physical
   measurements from the same material. The repository does not substantiate an
   accuracy percentage. The previous +/-25–30% statement is now identified as
   unvalidated rather than presented as an established error bound.
5. If downstream tools consume old CSV/JSON formats, update them for schema 2
   before replacing reports. A dependency lock and model checksum remain useful
   follow-up work once the deployment environment is agreed.

The fixes establish better software consistency. Surface sampling, perspective,
segmentation heuristics, RR fines estimation, and pooled-photo weighting still
need domain validation; multiple photos alone do not establish accuracy.
