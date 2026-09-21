# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-file Python CLI (`rock_gradation.py`, ~690 lines) that turns a photo of a
blasted-rock muckpile into a size-gradation report. The whole program is that one
file plus `requirements.txt` and `README.md`. There is no package, no test suite,
no build step, and no git repository.

## Commands

```bash
pip install -r requirements.txt                              # once; FastSAM-x.pt (~140 MB) downloads on first run
python rock_gradation.py IMG_7350.jpeg --roi 0,0.2,1,0.8     # single photo
python rock_gradation.py shot12/*.jpg --roi 0,0.2,1,0.8 --combine --out shot12/result
```

Smoke test after a change (no automated tests exist): run the command above on a real
photo and check the printed tables plus `*_overlay.jpg`. Use `--model FastSAM-s.pt`
and `--imgsz 640` for a fast iteration loop; CPU-only runs take ~30 s/photo at defaults.

## Pipeline

`main()` → `analyse()` per image → `report()` → `save_outputs()`. Five numbered
sections in the source match the five stages:

1. **Scale** (`detect_pole`) — HSV-threshold the red pole segments, group the
   collinear ones, then derive mm/px from both the segment length and the red-to-red
   pitch (pitch counts double in the median). Returns `ScaleResult`, whose
   `pole_mask` is fed into the exclusion zone so the pole is never measured as rock.
   Overridden by `--scale` or `--pole-px`.
2. **Segment** (`run_fastsam` → `resolve_masks`) — FastSAM "segment everything"
   produces heavily overlapping masks; `resolve_masks` flattens them to one int32
   label image using containment logic: a big mask tiled by ≥2 smaller masks
   covering >50% of it is a *group of rocks* and is dropped; a lone small mask
   inside a big one is a *facet* and is dropped. This heuristic is the main lever
   on accuracy — tune it here, not downstream.
3. **Measure** (`measure`) — per label, covariance eigenvalues give the best-fit
   ellipse, which is then rescaled so its area equals the pixel area. Sieve size is
   the minor axis by default (`--metric`).
4. **Grade** (`curve`, `fit_rr`) — cumulative % passing weighted by visible area
   (Delesse: surface area fraction = volume fraction). Rosin-Rammler is fit on a
   *log-spaced* size grid so the coarse tail is not drowned out by many fines.
5. **Report** (`report`, `save_outputs`) — prints tables and writes
   `_overlay.jpg`, `_curve.png`, `_gradation.csv`, `_fragments.csv`, `_result.json`.

## Invariants worth knowing before editing

- **Three curves, always.** Every output carries `measured` (what was seen),
  `rr_fit` (pure Rosin-Rammler) and `report` (the deliverable). `report` is the
  measured curve with a fines correction: below `--fit-min` (50 mm) it uses RR,
  above it the measured curve is rescaled to `F + (100-F)·(m(x)-m0)/(100-m0)`.
  D-values invert that same piecewise mapping (`report()`), so changing the
  correction means changing the inversion too.
- **Two pixel spaces.** `analyse()` downscales the photo by `k = work_width/width`
  and works in downscaled pixels. `--scale` and `--pole-px` are given in *original*
  photo pixels and are converted by `k` on entry; `meta["mmpp"]` is converted back
  (`mmpp * k`) for reporting. Anything new that touches pixels must pick a side
  deliberately.
- **`report()` returns a private `_curve` key** that `save_outputs()` pops. Calling
  `report()` without `save_outputs()` leaks a numpy tuple into the JSON dict.
- **`--combine` pools `Fragment` objects, not photos.** Fragments already carry mm
  sizes from their own photo's pole, so pooling is valid across scales. The combined
  `meta["mmpp"]` is NaN on purpose and `report()` branches on the `x == x` NaN check.
- **Model is a module-level global** (`_MODEL`), loaded once and reused across all
  images in a run.
- **`resolve_masks` is O(n²)** in kept masks via pairwise `_inter`; `--max-det`
  (1500) is what keeps it tractable.
- `--keep-edge` defaults to **on**; `--drop-edge` is the off switch for the same dest.

## Domain constraints

A single photo is ±25–30%; oversize % is typically decided by 3–6 boulders. Scale is
only true near the pole's distance (`--persp` applies a linear correction from the
pole row to the photo bottom). Only the surface is seen and it is coarser than the
pile interior. Do not present a single-photo number as a defensible result, and do
not remove the accuracy caveats printed by `report()`.
