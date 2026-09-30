# CLAUDE.md

## Structure and commands

This Git repository has a single-file Python CLI, `rock_gradation.py`, and
standard-library regression tests in `tests/`. No build step is needed.
Use the repository virtual environment from the repository root:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -B rock_gradation.py stockpile_picture/2026-09/09182026.jpg --roi 0,0.2,1,0.8 --out output/2026-09/new-run
```

Input/output/model paths are relative to the caller's current directory. There is
no wrapper script: invoke `rock_gradation.py` directly.

`monthly_report.py` builds the month's summary from the daily reports
(`/genreport`): `.\.venv\Scripts\python.exe -B monthly_report.py 2026-09`. It
writes English and Thai HTML and PDF plus a CSV into `output/<YYYY-MM>/report/`,
printing PDFs with headless Edge. Per-day judgements (confidence, plausible
range, notes, month highlights) live in `output/<YYYY-MM>/report/notes.json` and
are written by reviewing each day; the build refuses to run until every day is
reviewed. Its layout is the approved one: keep changes to it deliberate.

Monthly reports are opt-in: run only on `/genreport` or an explicit request to
build them, never automatically after photo analysis. `/genreport` is a lean,
single script invocation using existing notes; do not inspect images/PDFs or
write judgements during that command. Missing review notes are a blocking input,
not permission to start an AI review. Review only when separately requested.

## Operating target (user clarification, 2026-09-30)

- **Below 100 mm:** fines pass through the excavator's screening bucket.
- **100-400 mm:** target rock size range.
- **Above 400 mm:** acceptable material requiring a hydraulic breaker to reduce
  it to the target range. Oversize indicates additional breaker workload, not
  rejected material.

Boundary note: the user's operating description includes 400 mm in the target
range. The current calculation/export contract instead assigns exactly 400 mm
to breaker material (`>=400`), with target feed `100 <= size < 400`.
This clarification records operating intent; it does not change calculations.
Keep this distinction explicit when interpreting existing reports.

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
  red `>= --breaker`, then `OVERLAY_EDGES` (300, 100 mm) giving orange 300-400,
  green 100-300, blue below 100. `overlay_classes()` builds the colouring and
  the legend from one list so they cannot drift, and drops edges at or above
  `--breaker` so a custom threshold never yields an inverted band. The edges are
  independent of `--fit-min`. This is a deliberate operator preference and is
  asserted by tests; do not "correct" it to bypass/crusher/breaker destinations.
- The overlay container follows `--overlay-format` (`jpg`, `jpeg`, `png`);
  `output_paths()` takes the extension so staged and published names match.
  Kaspersky Endpoint Security on this machine blocks scripts from creating
  `*.jpg`, and because publication is all-or-nothing a blocked overlay write
  discards the entire report, so use `png` until that policy is changed.
- `--fit-min` defaults to **100 mm**: rock below it is reported from the
  Rosin-Rammler fit rather than measurement, so the threshold matches the
  overlay's blue class. It sets both the fit's lower bound and the chart's
  shaded region, so moving it changes D-values at the fine end (D10, D30)
  while leaving the coarse end and the breaker split essentially untouched.
- Plant split: **fines <100 mm, crusher 100-400 mm, breaker >=400 mm**.
  `--bypass` (default 100) is the fines cut-off and `--breaker` (400) the
  oversize limit; the crusher takes what lies between. The JSON key stays
  `split.bypass` for compatibility, but it is presented to users as "fines".
  100 mm is deliberately the same edge as `--fit-min` and the overlay's blue
  class, so "fines" means one thing throughout.
- Output schema version 2 changes fragment CSV identifiers, unavailable fit
  representation, quantile semantics, and dynamic retained bands.

## Validation and limits

Inspect every overlay. Pole/background exclusion and split/merged rocks still
require visual review. Read the photo before choosing ROI; do not guess scale.
Synthetic tests establish software behavior, not sieve-equivalent accuracy.
Accuracy is unvalidated: the old +/-25-30% statement was not evidence-backed.
Surface bias, perspective, fines estimation, and segmentation remain limitations.
Multiple photographs improve sampling but cannot establish accuracy by themselves.
Keep site photos, model weights, and generated reports out of Git. Photos live in
`stockpile_picture/<YYYY-MM>/`, daily reports in `output/<YYYY-MM>/<YYYY-MM-DD>/`, and
the month's summary (HTML, PDF, CSV) in `output/<YYYY-MM>/report/`. Only
`YYYY-MM-DD` folders are production days; anything reading a month must skip `report/`.
