---
description: Build the monthly blast-fragmentation report (English + Thai PDF and HTML, summary CSV) from the month's daily gradation reports.
argument-hint: [YYYY-MM]
---

Build the monthly report for: **$ARGUMENTS** (if empty, use the latest `YYYY-MM` folder in `output/`).

Work from the repo root with `./.venv/Scripts/python.exe`. The layout is fixed in
`monthly_report.py`; do not restyle or reword it per month. Only the per-day judgements in
`notes.json` are written by you.

## 1. Check the daily reports exist

List `output/<YYYY-MM>/`. Every `YYYY-MM-DD` folder must hold `<MMDDYYYY>_result.json` and an
`_overlay.png` from `/gradation`. If a production day is missing or incomplete, stop and say which.
`report/` is the output folder, not a day.

## 2. Review each day into `notes.json`

`output/<YYYY-MM>/report/notes.json` holds what cannot be computed. If it does not exist, create a
stub with:

```powershell
.\.venv\Scripts\python.exe -B monthly_report.py <YYYY-MM> --init-notes
```

Fill in every entry whose `conf` is `REVIEW`. Keep existing reviewed entries unless the user
asks to change them. For each new day, read its `_overlay.png` and `_result.json`, and use what
is known from that day's `/gradation` run if it is in the conversation.

- **conf** — one of:
  - `good`: pole flat on the pile, shot square-on, clean delineation;
  - `fair`: usable, with a stated caveat (small sample area, a crop around a false object, low coverage);
  - `low`: oblique shot or a pole that splits big rocks, so oversize is likely over-measured;
  - `provisional`: no pole or an estimated scale. These days are shown but left out of the monthly figures.
- **range** `[lo, hi]` (optional): only when one judgement call moves the breaker figure. Give it
  in % of rock above 100 mm, the same basis as the report.
- **flag** (optional): a short label under the day on the oversize chart, e.g. "upper bound",
  "range 10-20%", "provisional". Give it in `en` and `th`.
- **notes**: one to three plain sentences per language saying what was excluded and what limits
  the result. Any breaker % quoted must be a share of rock above 100 mm.
- **highlights**: one or two month-level summary bullets per language, e.g. which days were
  coarse or fine.

The Thai text uses the site terms already in the report: เบรกเกอร์, เครื่องโม่, ไม้สเกล, and the
Buddhist-era year.

## 3. Build

```powershell
.\.venv\Scripts\python.exe -B monthly_report.py <YYYY-MM>
```

This writes `<YYYY-MM>_report.html` / `.pdf`, `<YYYY-MM>_report_th.html` / `.pdf` and
`<YYYY-MM>_summary.csv` into `output/<YYYY-MM>/report/`. The PDFs are printed by headless
Microsoft Edge.

## 4. Check the PDFs

Open each PDF with the Read tool. Confirm:
- page 1 shows the summary, the five headline boxes and the oversize chart;
- the daily table shows all 14 columns;
- no heading is stranded at the foot of a page;
- the Thai text renders.

## 5. Report

Give the user the file paths and the headline line the script prints: median breaker, its range,
and the mean share below 100 mm. Say which days are `low` or `provisional`, and why.

Split convention: 100 mm is the low cut point. The <100 mm share is of all material. Crusher
(100–400 mm) and breaker (≥400 mm) are shares of the rock above 100 mm, so they sum to 100%.
Monthly figures use only days that are not `provisional`. Accuracy is unvalidated.
