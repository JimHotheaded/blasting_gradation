# Repository Guidelines

## Project Structure & Module Organization

`rock_gradation.py` contains the complete CLI: scale detection, FastSAM segmentation, fragment measurement, gradation calculations, and report export. Dependencies are in `requirements.txt`; usage is documented in `README.md`. `CLAUDE.md` provides pipeline details and current calculation contracts.

`example/` holds tracked sample overlays, curves, and CSV reports. `stockpile_picture/` contains local input photos; `output/` holds generated reports. Both are ignored, along with `.venv/` and model weights (`*.pt`). `tests/` contains standard-library unittest regressions; `.claude/` contains a compatibility CLI and analysis instructions. There is no package directory or build step.

## Build, Test, and Development Commands

Run these PowerShell commands from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe rock_gradation.py --help
.\.venv\Scripts\python.exe rock_gradation.py stockpile_picture/09182026.jpg --roi 0,0.2,1,0.8 --out output
```

These create the environment, install dependencies, show options, and analyze a local photo. Substitute an available photo when needed. Model weights download on first use if absent. For combined analysis, pass explicit image paths followed by `--combine`; the CLI does not expand wildcard paths itself.

## Coding Style & Naming Conventions

Use four-space indentation, `snake_case` functions and variables, `PascalCase` dataclasses, and uppercase constants. Preserve the numbered pipeline sections and existing NumPy/OpenCV conventions. Use descriptive unit suffixes such as `_mm` and `_px`. No formatter or linter is configured; keep edits consistent with surrounding code.

## Testing Guidelines

Run `.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v`. No coverage threshold is configured. After behavioral changes, run a real-photo smoke test and inspect the printed tables, `*_overlay.jpg`, `*_curve.png`, CSV files, and JSON output. Check missed, merged, or split rocks and compare results using identical inputs and options. Record the command and observations in the PR.

## Calculation Constraints

Keep original-image and downscaled pixel coordinates distinct. Preserve `measured`, `rr_fit`, and `report` curves; changes to fines correction must also update D-value inversion. Retain reporting accuracy caveats and inspect overlays before interpreting results.

## Commit & Pull Request Guidelines

The sole existing commit uses an imperative subject: `Add photo-based rock fragmentation gradation tool`. Follow that concise style. PRs should explain the change, validation, and numerical effects; include before/after overlays for segmentation changes and link relevant issues. Keep private site photos, generated reports, environments, and model weights out of commits.
