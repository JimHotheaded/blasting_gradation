# rock_gradation.py — blast fragmentation from a photo

Reads a muckpile/stockpile photo with the red-white scale pole, outlines every
visible block with the FastSAM AI model, and prints the gradation:
cumulative % passing, % retained per band, bypass / crusher / breaker split,
D10–D95, Cu and a Rosin-Rammler fit.

## Setup (once)

```
pip install -r requirements.txt
```

The first run downloads the model weights (FastSAM-x.pt, about 140 MB) into
the folder you run it from. After that it works offline. A GPU is not required. Runtime and device selection depend on the local environment.

## Run

```
python rock_gradation.py muckpile.jpg --roi 0,0.2,1,0.8
```

`--roi 0,0.2,1,0.8` skips the top 20% of the photo (bench face and far-away
rock). Without it the whole photo is analysed.

Several photos of the same shot, merged into one gradation:

```
python rock_gradation.py shot12/photo1.jpg shot12/photo2.jpg --roi 0,0.2,1,0.8 --combine --out shot12/result
```

## Outputs (per photo)

| File | What |
|---|---|
| `_overlay.jpg` | blocks coloured by size class — red `>=` breaker (400 mm), orange 300-400, green 100-300, blue below 100; blocks over the breaker limit are labelled in mm. **Check this first.** Extension follows `--overlay-format`. |
| `_curve.png` | measured curve, Rosin-Rammler fit, fines-corrected report curve |
| `_gradation.csv` | % passing, % retained by band, D-values, split |
| `_fragments.csv` | every block: size, axes, position |
| `_result.json` | everything, for the dashboard / SQL |

## Options you will use

| Option | Default | |
|---|---|---|
| `--breaker` | 400 | oversize limit to hydraulic breaker, mm |
| `--bypass` | 10 | size that bypasses the crusher, mm |
| `--segment-length` | 400 | one red or white pole segment, mm |
| `--roi` | whole photo | x,y,w,h in pixels or fractions |
| `--persp-ref` | off | `ROW,MM_PER_PX` depth calibration from a second photo (see below). Fits the true `1/(row-horizon)` curve. Repeatable |
| `--persp` | 1 (off) | crude straight-line fallback: scale at photo bottom ÷ scale at pole. Prefer `--persp-ref` |
| `--scale` | auto | mm per pixel, when there is no pole |
| `--pole-px` | auto | x1,y1,x2,y2: ends of the **painted** segments (not the black tip) |
| `--drop-edge` | off | ignore blocks cut by the photo edge |
| `--weight` | area | `area` (visible area = volume, Delesse) or `volume` |
| `--fit-min` | 100 | rock below this size is treated as fines and taken from the Rosin-Rammler fit; matches the overlay's blue class |
| `--model` | FastSAM-x.pt | `FastSAM-s.pt` is faster, with similar results |
| `--overlay-format` | jpg | overlay container: `jpg`, `jpeg` or `png`. Use `png` where endpoint-security policy forbids scripts from creating `*.jpg` |

## How it works

1. **Scale.** Finds the red segments, then measures their length and the
   red-to-red pitch (80 cm). The result is mm/px at the pole's distance.
2. **Segment.** FastSAM segments everything in the photo. The script then
   removes overlaps: a large mask that is really a group of rocks is
   dropped, and so is a small mask that is only one face of a block. It
   also removes the pole and anything outside the ROI.
3. **Size.** Each block's sieve size is the minor axis of its best-fit
   ellipse (≈ intermediate dimension).
4. **Grade.** Cumulative % passing weighted by calibrated visible area.
   This is an approximation; a photographed pile surface is not a random
   section and does not establish bulk volume fractions.
5. **Fines correction.** The camera cannot see fines in voids. Below 100 mm
   the Rosin-Rammler curve is used, and the measured curve above that is
   rescaled to fill the rest. If fitting is unsupported or fails, the report
   uses measured values and explicitly records a warning. This correction
   has not been calibrated against physical sieve measurements.

## Perspective: why nearer rock reads too large

Scale is only true at the pole's distance. A rock at half that distance reads
**twice** its real size, and because gradation weights by area the mass error is
**four times** — so uncorrected foreground rock inflates the oversize fraction.

By default nothing corrects this: every fragment uses the pole's mm/px.

**The reliable fix is to shoot square-on**, so all visible rock sits at roughly
one distance. Then no correction is needed.

When you must shoot down a slope, calibrate the depth instead of guessing:

1. From one camera position, photograph the pole lying at the **far** end of the
   muckpile, then again at the **near** end. Do not move the camera.
2. Run the script on the near photo and note two numbers it prints: the scale
   (`mm/px`) and the pole's image row (from `_result.json` → `sources[0]`, or
   the magenta pole line in the overlay).
3. Analyse the far photo, passing the near photo's numbers:

```
python rock_gradation.py far.jpg --roi 0,0.3,1,0.7 --persp-ref 1633,2.198
```

The photo's own pole supplies the second point, so the script solves the horizon
and applies `mm/px = coeff / (row - horizon)` per fragment. It prints the fitted
model and records it in `_result.json` under `depth_model`.

Rows and mm/px are in **original photo pixels**. The nearer reference must have
the smaller mm/px; the script rejects calibrations that imply otherwise rather
than producing a silently wrong curve.

On a test shot this moved the oversize count from 8 blocks to 3, while the
boulder at the pole's own distance barely changed — the near-field rocks were
the ones being over-measured.

## Accuracy — read before reporting

* **Accuracy has not been validated.** The earlier ±25–30% estimate is not
  supported by validation data in this repository. Several representative
  photos improve sampling but do not establish accuracy. Compare outputs
  against physical measurements before using them for production decisions.
* Keep the pole in the middle distance, flat on the rock, square to the
  camera. Take the photo as square-on to the pile face as you can.
* Blocks much nearer or further than the pole are mis-scaled. Use `--roi`
  to keep the analysis near the pole's distance, or `--persp`.
* Only the surface is seen. The surface of a muckpile is coarser than its
  inside.
* **Always look at the overlay.** If one block is split into two, or two
  blocks are merged into one, the number is off.


## Correctness and export behavior (schema version 2)

- `--fines none` uses the measured distribution throughout. Failed RR fits
  have `status: unavailable`, null fit values, and an explicit measured fallback.
- Passing means size **strictly less than** a sieve opening. Breaker material
  includes sizes equal to the threshold. Bands are lower-inclusive and
  upper-exclusive; operational thresholds split bands automatically.
- D-values are weighted empirical thresholds, not linear interpolation between
  fragments. Corrected fines use the analytic RR inverse; the coarse tail uses
  the empirical threshold. D-values can differ from older exports.
- `--min-size` applies to the selected physical size metric after perspective
  correction. A separate 15-pixel floor excludes unresolved masks.
- Existing outputs are refused unless `--overwrite` is explicit. Duplicate
  output stems, including `combined`, are rejected before inference.
- Writes are staged per report and checked before publishing. Filesystem errors
  stop the run; earlier completed photos in a batch may remain. Publishing a
  report involves multiple renames, not one atomic transaction.
- JSON uses `null` for unavailable values and records requested/effective fines
  modes, warnings, settings, package versions, source calibration, and accuracy
  status. Consumers must support `schema_version: 2`.
- Fragment CSV IDs are unique within the export; `source_image` and
  `source_label` identify the original image and segmentation label. Pixel
  coordinates refer to that image's downscaled working resolution.
- Unicode paths are supported directly; no rename workaround is needed.

## Regression tests

From the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

These tests use synthetic fragments/masks, failure injection, and temporary
exports. They do not download a model or measure real-world accuracy.
