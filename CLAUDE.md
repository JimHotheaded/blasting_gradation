# CLAUDE.md

Read `FIX_REPORT_2026-09-21.md` for the audit-fix handoff and validation evidence.
`AUDIT_REPORT_2026-09-21.md` describes the old defects and remains historical.

## Structure and commands

This Git repository has a single-file Python CLI, `rock_gradation.py`, and
standard-library regression tests in `tests/`. No build step is needed.
Use the repository virtual environment from the repository root:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -B rock_gradation.py stockpile_picture/09182026.jpg --roi 0,0.2,1,0.8 --out output/new-run
```

`.claude/gradation_run.py` delegates to the same CLI. It does not patch source,
change working directories, change file extensions, or print rename workarounds.
Input/output/model paths are relative to the caller's current directory.

## Pipeline

`main()` validates arguments and output paths before `analyse()` processes each
image. Scale detection, mask resolution, measurement, and reporting retain the
numbered source sections. `report()` calls `report_distribution()` so passing
percentages, splits, D-values, and plots use one distribution definition.

- Mask group coverage is the union of child masks intersected with the parent.
- Original-photo pixels are used for `--scale`, `--pole-px`, and pixel ROIs.
  Measurement/exported fragment coordinates use working-image pixels. JSON
  source metadata records both dimensions and their scale factor.
- Minimum size is applied to the selected physical metric after perspective
  correction; 15 pixels is a separate resolution floor.
- `fit_rr()` returns a status dictionary, not a tuple. Unavailable fits contain
  null parameters and a reason. They never use invented fallback parameters.
- Requested RR correction falls back to measured values with warnings when
  unsupported. JSON separates requested and effective correction modes.
- Passing is strict `< size`; breaker includes `>= threshold`. D-values are
  empirical weighted thresholds, with analytic inversion in corrected fines.
- `report()` retains a private `_curve` tuple for chart rendering. Export omits
  private keys without mutating the report. Strict JSON rejects NaN/Infinity.
- Combined reports pool physically calibrated fragment weights. Photo identity
  and source labels are preserved; combined scale and coverage are null.
- Reports are staged before publication; JSON is published last. Multiple file
  renames are not a single transaction. Completed earlier photos can survive
  later batch failures. Existing reports require explicit `--overwrite`.
- Perspective: `--persp-ref ROW,MM_PER_PX` (repeatable, original-photo units)
  plus the photo's own pole fits `DepthModel`, `mm/px = coeff/(row - horizon)`,
  the actual projective relation for a ground plane. `measure(depth=...)` takes
  precedence over the legacy linear `--persp`; both are mutually exclusive.
  `fit_depth_model()` rejects single points, equal mm/px, and calibrations whose
  implied horizon falls inside the measured rows. There is deliberately **no**
  automatic "needs perspective correction" warning: row spread is not depth
  spread, so that test false-positives on square-on photos.
- Overlay fragments are coloured by **size class**, not crusher destination:
  red `>= --breaker`, orange 200-breaker, green `--fit-min`-200, blue below
  `--fit-min`. This is a deliberate operator preference and is asserted by
  tests; do not "correct" it to bypass/crusher/breaker destinations.
- The overlay container follows `--overlay-format` (`jpg`, `jpeg`, `png`);
  `output_paths()` takes the extension so staged and published names match.
  Kaspersky Endpoint Security on this machine blocks scripts from creating
  `*.jpg`, and because publication is all-or-nothing a blocked overlay write
  discards the entire report, so use `png` until that policy is changed.
- Output schema version 2 changes fragment CSV identifiers, unavailable fit
  representation, quantile semantics, and dynamic retained bands.

## Validation and limits

Inspect every overlay. Pole/background exclusion and split/merged rocks still
require visual review. Read the photo before choosing ROI; do not guess scale.
Synthetic tests establish software behavior, not sieve-equivalent accuracy.
Accuracy is unvalidated: the old +/-25-30% statement was not evidence-backed.
Surface bias, perspective, fines estimation, and segmentation remain limitations.
Multiple photographs improve sampling but cannot establish accuracy by themselves.
Keep site photos, model weights, and generated reports out of Git.
