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
