# Repository audit — 2026-09-30

## Scope and result

Read-only audit of the repository, following `CLAUDE.md`. No implementation changes were made. All 30 existing regression tests passed.

The main weaknesses are monthly-report correctness and calibration validation.

## Findings and recommendations

| Priority | Finding | Recommendation |
|---|---|---|
| **High** | **Additional depth references are silently ignored when fitting.** Only the first and last points determine the model. A synthetic reference of 100 mm/px at row 200 was accepted despite the model predicting 2.67 mm/px there. See `rock_gradation.py:122`. | Fit all supplied references or reject inconsistent extra points. Report calibration residuals. |
| **High** | **Provisional days influence the monthly median curve.** When there are more than six days, the curve and comparison statistics include provisional results, although headline figures exclude them. See `monthly_report.py:276`. | Apply the same eligibility filter to all monthly aggregates; retain provisional days as individually marked observations. |
| **Medium** | **A failed PDF export can be reported as successful.** The code ignores Edge's return code and checks only whether the PDF exists. An old PDF therefore masks a failed rebuild; reproduced with mocks. See `monthly_report.py:615`. | Generate a temporary PDF, verify successful completion and a valid new file, then replace the published PDF. |
| **Medium** | **Monthly method descriptions can contradict the actual analysis.** They always claim minor-axis sizing, area weighting, RR fines and no perspective calibration, despite configurable settings and measured fallback. See `monthly_report.py:74`. | Derive descriptions from daily metadata and explicitly identify mixed methods or unsupported settings. |
| **Medium** | **An all-fines day produces misleading conditional percentages.** With 100% below 100 mm, the monthly conversion reports crusher 0% and breaker 0%, although those shares have no denominator. Reproduced in memory. See `monthly_report.py:185`. | Report these conditional shares as unavailable and exclude them from the corresponding monthly statistics. |

## Recommended order

1. Address calibration validation and monthly aggregation.
2. Improve PDF export verification and report semantics.
3. Add monthly-report regression tests. The current 30 tests cover the analysis CLI but do not exercise these monthly-report cases.
4. For reproducibility, pin a tested dependency set and record the model-weight checksum.

## Validation and limitations

The regression suite was run with:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

Result: **30 tests passed**.

Additional checks used synthetic inputs and mocks. This audit did not run real-photo inference or generate monthly reports. Real-world measurement accuracy remains unvalidated.

The following pre-existing modified files were left untouched:

- `.claude/commands/genreport.md`
- `.claude/commands/gradation.md`
- `CLAUDE.md`

This report was saved separately at the user's request; no fixes were applied.

## Resolution — 2026-09-30

Findings 1–5 are fixed, with regression tests for each. The suite now has **43 tests**: 30 existing,
2 added in `test_rock_gradation.py` and 11 in the new `tests/test_monthly_report.py`. Regenerating
September 2026 reproduces the reviewed English and Thai pages and the summary CSV exactly, because
none of its days trigger the new paths. A real Edge export succeeded through the new staging step.

| # | Fix |
|---|---|
| 1 | `fit_depth_model()` fits **every** reference by least squares on `1/mm_per_px` against the row, which is linear for a ground plane, instead of using only the outer pair. A point that the fit misses by more than `DEPTH_TOLERANCE` (10%) is rejected with the offending row named. The audit's 100 mm/px at row 200 case now fails. Two points are still fitted exactly. `depth_model.max_residual_pct` is recorded in the JSON. |
| 2 | One eligibility rule, `eligible()`, covers every monthly aggregate. Provisional days no longer shape the monthly median curve or the min/median/max table. They are still drawn individually as dashed lines. |
| 3 | `print_pdf()` prints to a staged file beside the target, then checks Edge's return code, the file size, and the `%PDF-` header and `%%EOF` trailer before replacing the published PDF. On failure the old PDF is untouched, the failure is printed, and the run exits 1. |
| 4 | `method_facts()` derives the method wording from each day's recorded metric, weighting, perspective correction, effective fines correction and `fit_min`. Mixed settings are named with their days. The short-axis slab caveat appears only when every day used the short axis, and the chart's fines label says "measured" when no day used the fit. |
| 5 | `conditional_split()` returns `None` for crusher and breaker when less than 0.05% of material lies above 100 mm. Such a day shows "n/a" and is left out of the breaker and crusher statistics. It still counts towards the below-100 mm figures. |

Not addressed: recommendation 4 (pin a tested dependency set and record the model-weight checksum)
is still open.
