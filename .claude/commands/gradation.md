---
description: Blast-fragmentation gradation from a muckpile photo — picks the ROI, runs rock_gradation.py, writes date-grouped output and reports the crusher/breaker split.
argument-hint: <picture.jpg> [more.jpg ...]
---

Run a rock-fragmentation gradation analysis on: **$ARGUMENTS**

Work from the repo root and always use `./.venv/Scripts/python.exe` — never bare `python`,
which does not have the dependencies.

Follow these steps in order. Do not skip step 1 or step 5.

## 1. Look at the photo first

Read the image with the Read tool before choosing any flags. Confirm:

- **The red/white pole is in frame.** No pole means no scale — stop and ask the user for
  `--scale <mm/px>` or `--pole-px x1,y1,x2,y2 --pole-length <mm>`. Never guess a scale.
- **What is not muckpile.** Bench face, quarry wall, haul road, sky, parked vehicles and
  bare dust/ground all corrupt the result and must be excluded by ROI.
- Roughly what fraction of the frame height the rock actually occupies.

## 2. Choose the ROI

`--roi x,y,w,h` as fractions of the frame (`0,0.2,1,0.8` = skip the top 20%). Tailor it per
photo; do not reuse a previous photo's ROI blindly. Calibration points from earlier runs:

| Scene | ROI |
|---|---|
| Bench face across top ~20%, rock down to the bottom | `0,0.2,1,0.8` |
| Wall + haul road to ~30%, bare dust across bottom ~15% | `0,0.3,1,0.55` |

Keep the pole well inside the ROI — scale is only true near the pole's distance.

## 3. Work out the output folder

Output goes in `output/<YYYY-MM-DD>/` — ISO, so folders sort chronologically.

Derive the date from the filename stem when it is `MMDDYYYY` (`09182026` → `2026-09-18`).
If the stem is not a date, ask the user for the production date rather than inventing one.

## 4. Run it

Two steps, both from the shell. `.claude/gradation_run.py` wraps `rock_gradation.py` to work
around two machine quirks (scripts cannot create `*.jpg`; OpenCV cannot open the non-ASCII
repo path) without modifying `rock_gradation.py` itself — read its docstring for detail.

```bash
# analyse — repeat per photo, each with its own ROI
./.venv/Scripts/python.exe .claude/gradation_run.py <photo> --roi <roi> --out output/<YYYY-MM-DD>

# rename the overlay .jpeg -> .jpg (must be a -c run straight from the shell, not from a script)
./.venv/Scripts/python.exe -c "
import shutil, os, glob
for j in glob.glob('output/<YYYY-MM-DD>/*_overlay.jpeg'):
    shutil.copyfile(j, j[:-5]+'.jpg'); os.remove(j); print('overlay ->', j[:-5]+'.jpg')
"
```

Expect ~30 s per photo on CPU. Each photo yields 5 files: `_overlay.jpg`, `_curve.png`,
`_gradation.csv`, `_fragments.csv`, `_result.json`.

Flags worth knowing: `--breaker` (oversize limit, default 400 mm), `--bypass` (default 10 mm),
`--segment-length` (one pole segment, default 400 mm), `--persp` when the foreground is
markedly closer than the pole, `--model FastSAM-s.pt` for a faster pass. For several photos
of the *same* muckpile, add `--combine` to pool them into one gradation.

## 5. Check the overlay — mandatory

Read the generated `_overlay.jpg` with the Read tool and confirm:

- blocks are outlined individually, not merged into blobs or split into facets
- the pole is masked out (drawn magenta) and not counted as rock
- the yellow ROI box excludes everything identified in step 1
- the labelled oversize boulders genuinely look oversize

If delineation is visibly wrong, the numbers are wrong. Say so and adjust the ROI or flags
instead of reporting the figures.

## 6. Report

Take the headline numbers from `_result.json` and give the user a table:

scale mm/px · fragments · area delineated % · D50 · D80 · top size · Cu · RR xc and n ·
bypass % · crusher % · **breaker % and the oversize block count**.

With several photos, compare them in one table. Then state the accuracy caveat plainly: a
single photo is ±25–30%, only the pile surface is visible and it is coarser than the interior,
and the oversize figure usually rests on a handful of boulders — 5–10 photos per shot with
`--combine` is what makes a number defensible. If the oversize % rests on fewer than ~5
blocks, say so explicitly.
