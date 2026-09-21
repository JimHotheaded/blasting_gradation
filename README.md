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
the folder you run it from. After that it works offline. It runs on the CPU,
with no GPU needed, and takes about 30 s per photo.

## Run

```
python rock_gradation.py IMG_7350.jpeg --roi 0,0.2,1,0.8
```

`--roi 0,0.2,1,0.8` skips the top 20% of the photo (bench face and far-away
rock). Without it the whole photo is analysed.

Several photos of the same shot, merged into one gradation:

```
python rock_gradation.py shot12\*.jpg --roi 0,0.2,1,0.8 --combine --out shot12\result
```

## Outputs (per photo)

| File | What |
|---|---|
| `_overlay.jpg` | blocks coloured by size class; blocks over the breaker limit are labelled in mm. **Check this first.** |
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
| `--persp` | 1 (off) | scale at photo bottom ÷ scale at pole, e.g. 0.8 when the foreground is closer |
| `--scale` | auto | mm per pixel, when there is no pole |
| `--pole-px` | auto | x1,y1,x2,y2: ends of the **painted** segments (not the black tip) |
| `--drop-edge` | off | ignore blocks cut by the photo edge |
| `--weight` | area | `area` (visible area = volume, Delesse) or `volume` |
| `--model` | FastSAM-x.pt | `FastSAM-s.pt` is faster, with similar results |

## How it works

1. **Scale.** Finds the red segments, then measures their length and the
   red-to-red pitch (80 cm). The result is mm/px at the pole's distance.
2. **Segment.** FastSAM segments everything in the photo. The script then
   removes overlaps: a large mask that is really a group of rocks is
   dropped, and so is a small mask that is only one face of a block. It
   also removes the pole and anything outside the ROI.
3. **Size.** Each block's sieve size is the minor axis of its best-fit
   ellipse (≈ intermediate dimension).
4. **Grade.** Cumulative % passing weighted by visible area. By Delesse's
   principle, area fraction on the surface equals volume fraction.
5. **Fines correction.** The camera cannot see fines in voids. Below 50 mm
   the Rosin-Rammler curve is used, and the measured curve above that is
   rescaled to fill the rest. This is the same approach Split-Desktop uses.

## Accuracy — read before reporting

* A single photo is typically **±25–30 %**. The oversize % in one photo is
  often decided by 3–6 boulders, so shoot **5–10 photos per shot** and use
  `--combine`.
* Keep the pole in the middle distance, flat on the rock, square to the
  camera. Take the photo as square-on to the pile face as you can.
* Blocks much nearer or further than the pole are mis-scaled. Use `--roi`
  to keep the analysis near the pole's distance, or `--persp`.
* Only the surface is seen. The surface of a muckpile is coarser than its
  inside.
* **Always look at the overlay.** If one block is split into two, or two
  blocks are merged into one, the number is off.
