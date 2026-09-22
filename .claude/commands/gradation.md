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
| Cliff across top ~30%, blast product down to the frame bottom | `0,0.3,1,0.7` |

Keep the pole well inside the ROI — scale is only true near the pole's distance.

**Crop only what is not blast product** (sky, cliff, wall, haul road, water, vehicles).
Do not crop away valid rock merely because it sits closer to the camera than the pole.
Doing so trades a small scale bias for a much larger sampling bias: on 09222026 an
over-tight band kept only the boulder cluster and reported 53% oversize, where keeping
the whole muckpile gave ~35% from 183 fragments instead of 58. Handle the depth gradient with
`--persp-ref` instead (step 4), not by cropping.

## 3. Work out the output folder

Output goes in `output/<YYYY-MM-DD>/` — ISO, so folders sort chronologically.

Derive the date from the filename stem when it is `MMDDYYYY` (`09182026` → `2026-09-18`).
If the stem is not a date, ask the user for the production date rather than inventing one.

## 4. Run it

Run the maintained CLI directly. The compatibility wrapper delegates to it without
source patching. Unicode paths are supported. Do not rename extensions or bypass
write failures; a failed output write stops the run.

```powershell
.\.venv\Scripts\python.exe -B rock_gradation.py <photo> --roi <roi> --overlay-format png --out output/<YYYY-MM-DD>
```

`--overlay-format png` is required on this machine: Kaspersky Endpoint Security blocks
scripts from creating `*.jpg`, and a blocked overlay write aborts the whole report
(outputs are staged and published only if every file succeeds). Drop the flag once the
policy exclusion is in place. Do not rename extensions after the fact.

**Perspective.** Scale is only true at the pole's distance; a rock at half that
distance reads twice its size, and area weighting squares the error. If the shot
looks down a slope rather than square-on at the pile, say so in the report and
treat the oversize count as an upper bound. If the user has a second photo taken
from the same camera position with the pole at a different distance, calibrate:
run that photo, take its `mm/px` and pole row, and pass `--persp-ref ROW,MM_PER_PX`
(original-photo pixels). The script then fits `mm/px = coeff/(row - horizon)` and
prints the model. There is no automatic warning for this — row spread is not depth
spread — so judge it from the photo in step 1.

Each photo yields five checked files. Existing outputs require a new directory or
explicit `--overwrite`. Pass explicit image paths for combined runs. A batch uses
one ROI setting for all photos; process separately if their ROIs differ.

Flags worth knowing: `--breaker` (oversize limit, default 400 mm), `--bypass` (default 10 mm),
`--segment-length` (one pole segment, default 400 mm), `--persp` when the foreground is
markedly closer than the pole, `--model FastSAM-s.pt` for a faster pass. For several photos
of the *same* muckpile, add `--combine` to pool them into one gradation.

## 5. Check the overlay — mandatory

Read the generated `_overlay.png` (or `.jpg`) with the Read tool and confirm:

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

With several photos, compare them in one table. Check `schema_version`,
`rosin_rammler.status`, `warnings`, and requested/effective fines correction before
summarizing. Missing fit values are null, not zero. If the report fell back to
measured values, say so. State that accuracy is unvalidated; the older +/-25-30%
claim was not supported by validation data. Multiple photos improve sampling but
do not establish accuracy. Physical measurements are needed for validation.
