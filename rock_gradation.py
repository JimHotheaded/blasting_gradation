#!/usr/bin/env python3
"""
rock_gradation.py - Blasted-rock fragmentation (gradation) from a photo.

Give it a photo of a muckpile / stockpile with a red-white scale pole in it.
It finds the pole, delineates every visible fragment with an AI segmentation
model (FastSAM), and prints the gradation: cumulative % passing, % retained
per band, crusher/breaker split, D-values, Cu and the Rosin-Rammler fit.

Outputs (next to the photo, or in --out):
  <name>_overlay.jpg     fragments outlined, oversize labelled in mm
                         (container set by --overlay-format: jpg, jpeg or png)
  <name>_curve.png       gradation curve with breaker line
  <name>_gradation.csv   the tables
  <name>_fragments.csv   every fragment (size, axes, position)
  <name>_result.json     everything, machine-readable

Quick start
  pip install ultralytics opencv-python numpy scipy matplotlib
  python rock_gradation.py IMG_7350.jpeg --roi 0,0.2,1,0.8

  First run downloads the FastSAM-x weights (~140 MB) automatically.

More
  --breaker 400          oversize limit to hydraulic breaker (mm)
  --segment-length 400   one red/white pole segment (mm)
  --scale 3.13           manual mm per pixel (skip pole detection)
  --pole-px 405,605,1045,645 --pole-length 2000   painted pole ends by hand
  --persp 0.8            foreground closer than pole: scale at bottom = 0.8x
  --roi x,y,w,h          analyse only this box (leave out bench face / sky);
                         pixels or fractions, e.g. 0,0.2,1,0.8
  --combine a.jpg b.jpg  explicit photos of one shot -> one gradation

Accuracy is unvalidated; the earlier +/-25-30% estimate was not verified.
Only the surface is seen, fines hide in voids, and scale is only true near
the pole distance. Inspect overlays and compare against physical measurements.
Several photos improve sampling but do not establish accuracy.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import warnings
import tempfile
import hashlib
from importlib.metadata import version, PackageNotFoundError
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from scipy.optimize import curve_fit, OptimizeWarning

STD_SIZES_MM = [10, 25, 50, 75, 100, 150, 200, 250, 300, 400, 500, 600,
                700, 800, 900, 1000, 1200]
BANDS_MM = [0, 10, 25, 50, 100, 200, 300, 400, 600, 800, 1000, None]
D_VALUES = [10, 20, 30, 40, 50, 60, 70, 80, 90, 95]
# Overlay container. Some endpoint-security policies forbid scripts from creating
# *.jpg; "png" is a supported alternative rather than a rename workaround.
OVERLAY_FORMATS = ["jpg", "jpeg", "png"]
OVERLAY_DEFAULT = "jpg"
# Overlay size-class edges below --breaker, coarsest first, in mm. Independent
# of --fit-min: these are what an operator reads off the picture, not the fines
# threshold. Colours are BGR, and are asserted by tests.
OVERLAY_EDGES = (300.0, 100.0)
OVERLAY_COLOURS = ((40, 40, 230), (30, 170, 240), (80, 200, 80), (220, 170, 60))


def overlay_classes(breaker):
    """(lower_edge, colour, legend label) per size class, coarsest first.

    Edges at or above --breaker are dropped, so a custom breaker threshold can
    never produce an inverted band such as "300-250".
    """
    red, orange, green, blue = OVERLAY_COLOURS
    classes = [(float(breaker), red, f">={breaker:g} mm breaker")]
    upper = float(breaker)
    for edge, colour in zip((e for e in OVERLAY_EDGES if e < breaker), (orange, green)):
        classes.append((edge, colour, f"{edge:g}-{upper:g}"))
        upper = edge
    classes.append((0.0, blue, f"<{upper:g}"))
    return classes


@dataclass
class ScaleResult:
    mm_per_px: float
    method: str
    pole_mask: np.ndarray | None = None
    pole_line: tuple | None = None
    detail: dict = field(default_factory=dict)


@dataclass
class DepthModel:
    """mm/px as a function of image row, for rock lying on one ground plane.

    A pinhole camera viewing a plane sees depth - and therefore mm/px - vary as
    ``coeff / (row - horizon)``, not linearly with the row: a rock at half the
    pole's distance reads twice its true size. Two calibration points at
    different depths determine both constants exactly, so this replaces the
    straight-line ``--persp`` ramp with the actual projective relationship.

    Rows and scales are working-image pixels. Values are clamped to a band
    around the calibration points so extrapolation beyond them stays bounded.
    """
    coeff: float
    horizon: float
    refs: tuple
    lo: float
    hi: float

    def __call__(self, row):
        value = self.coeff / max(float(row) - self.horizon, 1e-6)
        return min(max(value, self.lo), self.hi)


def fit_depth_model(refs):
    """Solve coeff/(row - horizon) through (row, mm_per_px) calibration points."""
    points = sorted({(float(row), float(mmpp)) for row, mmpp in refs})
    if len(points) < 2:
        raise ValueError("need two calibration points at different image rows")
    (y1, m1), (y2, m2) = points[0], points[-1]
    if abs(m1 - m2) < 1e-9:
        raise ValueError("calibration points share the same mm/px, so they carry no depth "
                         "information; they must sit at genuinely different distances")
    horizon = (m1 * y1 - m2 * y2) / (m1 - m2)
    if horizon >= y1:
        raise ValueError("the implied horizon falls inside the measured rows; the nearer "
                         "point must have the smaller mm/px - check which row is which")
    coeff = m1 * (y1 - horizon)
    if not math.isfinite(coeff) or coeff <= 0:
        raise ValueError("calibration implies a non-physical scale")
    scales = [m for _, m in points]
    return DepthModel(coeff, horizon, tuple(points), min(scales) * 0.2, max(scales) * 5.0)


@dataclass
class Fragment:
    label: int
    area_px: int
    size_mm: float      # sieve-equivalent size (see --metric)
    major_mm: float
    minor_mm: float
    ecd_mm: float
    weight: float       # relative weight (area or volume)
    cx: float
    cy: float
    edge: bool          # cut by ROI / image edge
    source_image: str = ""


# ============================================================================
# 1. Scale from the red/white pole
# ============================================================================
def red_mask(bgr):
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    m = (((h < 9) | (h > 168)) & (s > 110) & (v > 60)).astype(np.uint8)
    return cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))


def detect_pole(bgr, seg_len_mm) -> ScaleResult | None:
    """mm/px from the red segments: their length along the pole axis and the
    red-to-red pitch (= 2 segments)."""
    m = red_mask(bgr)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    H, W = m.shape
    min_area = max(150, int(H * W * 2e-4))
    cands = []
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < min_area:
            continue
        ys, xs = np.nonzero(lab == i)
        pts = np.column_stack([xs, ys]).astype(float)
        mu = pts.mean(0)
        _, _, vt = np.linalg.svd(pts - mu, full_matrices=False)
        proj, perp = (pts - mu) @ vt[0], (pts - mu) @ vt[1]
        length = np.ptp(np.percentile(proj, [1, 99]))
        width = np.ptp(np.percentile(perp, [3, 97]))
        if width <= 0 or length / max(width, 1) < 3:
            continue
        cands.append(dict(idx=i, mu=mu, axis=vt[0], width=width,
                          area=stats[i, cv2.CC_STAT_AREA]))
    if not cands:
        return None

    best = []                                   # largest collinear group
    for c in cands:
        grp = [c] + [d for d in cands if d is not c
                     and abs(np.dot(c["axis"], d["axis"])) > 0.97
                     and abs(c["axis"][0] * (d["mu"] - c["mu"])[1]
                             - c["axis"][1] * (d["mu"] - c["mu"])[0])
                     < 2.5 * max(c["width"], d["width"])]
        if sum(g["area"] for g in grp) > sum(g["area"] for g in best):
            best = grp

    ys, xs = np.nonzero(np.isin(lab, [g["idx"] for g in best]))
    pts = np.column_stack([xs, ys]).astype(float)
    mu = pts.mean(0)
    axis = np.linalg.svd(pts - mu, full_matrices=False)[2][0]
    seg_px, centres = [], []
    for g in best:
        ys, xs = np.nonzero(lab == g["idx"])
        p = (np.column_stack([xs, ys]) - mu) @ axis
        seg_px.append(np.ptp(np.percentile(p, [0.5, 99.5])))
        centres.append(np.median(p))
    seg_px, centres = np.array(seg_px), np.sort(centres)

    est = [seg_len_mm / L for L in seg_px]
    method = f"auto pole, {len(best)} red segment(s)"
    if len(centres) >= 2:
        period = np.median(np.diff(centres))
        k = max(1, round(period / np.median(seg_px) / 2))
        est += [2 * k * seg_len_mm / period] * 2          # pitch weighted x2
        method += " + pitch"
    mmpp = float(np.median(est))

    half = 0.5 * np.ptp(centres) + 1.7 * np.median(seg_px)
    c0 = mu + axis * centres.mean()
    p1, p2 = c0 - axis * half, c0 + axis * half
    band = np.zeros_like(m)
    thick = int(max(np.median([g["width"] for g in best]) * 3, 14))
    cv2.line(band, tuple(map(int, p1)), tuple(map(int, p2)), 1, thick)
    return ScaleResult(mmpp, method, band, (*p1, *p2),
                       dict(segment_px=[round(float(x), 1) for x in seg_px],
                            estimates=[round(float(e), 3) for e in est]))


# ============================================================================
# 2. Segmentation (FastSAM "segment everything")
# ============================================================================
_MODEL = None


def run_fastsam(bgr, model_path, imgsz, conf, iou, max_det):
    global _MODEL
    try:
        from ultralytics import FastSAM
    except ImportError:
        raise SystemExit("Needs ultralytics:  pip install ultralytics")
    if _MODEL is None:
        _MODEL = FastSAM(model_path)
    r = _MODEL(bgr, imgsz=imgsz, conf=conf, iou=iou, max_det=max_det,
               retina_masks=True, verbose=False)[0]
    if r.masks is None:
        return []
    data = r.masks.data.cpu().numpy() > 0.5
    H, W = bgr.shape[:2]
    out = []
    for m in data:
        if m.shape != (H, W):
            m = cv2.resize(m.astype(np.uint8), (W, H), cv2.INTER_NEAREST) > 0
        ys, xs = np.nonzero(m)
        if len(xs) == 0:
            continue
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        out.append(dict(box=(y0, y1, x0, x1), m=m[y0:y1, x0:x1].copy(),
                        area=len(xs)))
    return out


def _inter(a, b):
    """Pixel intersection of two cropped masks."""
    y0, y1 = max(a["box"][0], b["box"][0]), min(a["box"][1], b["box"][1])
    x0, x1 = max(a["box"][2], b["box"][2]), min(a["box"][3], b["box"][3])
    if y0 >= y1 or x0 >= x1:
        return 0
    sa = a["m"][y0 - a["box"][0]:y1 - a["box"][0], x0 - a["box"][2]:x1 - a["box"][2]]
    sb = b["m"][y0 - b["box"][0]:y1 - b["box"][0], x0 - b["box"][2]:x1 - b["box"][2]]
    return int((sa & sb).sum())


def resolve_masks(masks, shape, excl, min_px, max_frac=0.35):
    """Turn overlapping SAM masks into one label image.

    * masks mostly in the excluded zone (pole, outside ROI) are dropped
    * masks larger than max_frac of the frame are background, dropped
    * a big mask that is mostly tiled by 2+ smaller masks is a GROUP of
      rocks -> dropped, the small ones kept
    * a small mask sitting inside one big mask is a FACET -> dropped
    """
    H, W = shape
    keep = []
    for mk in masks:
        y0, y1, x0, x1 = mk["box"]
        inside = mk["m"] & (excl[y0:y1, x0:x1] == 0)
        a = int(inside.sum())
        if a < min_px or a < 0.5 * mk["area"] or a > max_frac * H * W:
            continue
        mk["m"], mk["area"] = inside, a
        keep.append(mk)
    keep.sort(key=lambda d: -d["area"])

    n = len(keep)
    contained = [[] for _ in range(n)]      # j (smaller) contained in i
    duplicates = set()
    for i in range(n):
        if i in duplicates:
            continue
        for j in range(i + 1, n):
            if j in duplicates:
                continue
            it = _inter(keep[i], keep[j])
            if it == keep[i]["area"] == keep[j]["area"]:
                duplicates.add(j)
                continue
            if it > 0.8 * keep[j]["area"]:
                contained[i].append(j)

    dropped = set(duplicates)
    for i in range(n):
        if i in dropped:
            continue
        kids = [j for j in contained[i] if j not in dropped]
        if not kids:
            continue
        parent = keep[i]
        union = np.zeros_like(parent["m"], dtype=bool)
        py0, py1, px0, px1 = parent["box"]
        for j in kids:
            child = keep[j]
            cy0, cy1, cx0, cx1 = child["box"]
            y0, y1 = max(py0, cy0), min(py1, cy1)
            x0, x1 = max(px0, cx0), min(px1, cx1)
            if y0 < y1 and x0 < x1:
                union[y0-py0:y1-py0, x0-px0:x1-px0] |= child["m"][
                    y0-cy0:y1-cy0, x0-cx0:x1-cx0]
        cover = np.count_nonzero(union & parent["m"]) / parent["area"]
        if len(kids) >= 2 and cover > 0.5:
            dropped.add(i)                  # group of rocks
        else:
            dropped.update(kids)            # facets of one rock

    labels = np.zeros((H, W), np.int32)
    lid = 0
    for i, mk in enumerate(keep):           # large first, small overwrite
        if i in dropped:
            continue
        lid += 1
        y0, y1, x0, x1 = mk["box"]
        labels[y0:y1, x0:x1][mk["m"]] = lid
    return labels


# ============================================================================
# 3. Measurement
# ============================================================================
def measure(labels, mmpp, min_px, edge_zone, metric, weight="area",
            persp=1.0, pole_y=None, min_size=0.0, depth=None):
    """depth: DepthModel giving mm/px per image row; takes precedence when set.

    persp: legacy straight-line fallback - mm/px at the photo's bottom edge /
    mm/px at the pole row (<1 when the foreground is closer than the pole)."""
    frags = []
    Himg = labels.shape[0]
    n = labels.max()
    for lid in range(1, n + 1):
        ys, xs = np.nonzero(labels == lid)
        if len(xs) < min_px:
            continue
        m = np.zeros((ys.max() - ys.min() + 1, xs.max() - xs.min() + 1), np.uint8)
        m[ys - ys.min(), xs - xs.min()] = 1
        k, cc, st, _ = cv2.connectedComponentsWithStats(m, 8)
        if k > 2:                           # keep main piece only
            big = 1 + np.argmax(st[1:, cv2.CC_STAT_AREA])
            sel = cc[ys - ys.min(), xs - xs.min()] == big
            ys, xs = ys[sel], xs[sel]
            if len(xs) < min_px:
                continue
        area = len(xs)
        cy = float(ys.mean())
        sc = mmpp
        if depth is not None:
            sc = depth(cy)
        elif persp != 1.0 and pole_y is not None and Himg - pole_y > 1:
            sc = mmpp * max(0.2, 1 + (persp - 1) * (cy - pole_y) / (Himg - pole_y))
        ev = np.sort(np.linalg.eigvalsh(np.cov(np.vstack([xs, ys]))))[::-1]
        major = 4 * math.sqrt(max(ev[0], 1e-6))
        minor = 4 * math.sqrt(max(ev[1], 1e-6))
        # rescale ellipse so its area equals the region's area
        f = math.sqrt(area / (math.pi / 4 * major * minor))
        major, minor = major * f, minor * f
        ecd = 2 * math.sqrt(area / math.pi)
        size = {"minor": minor, "ecd": ecd, "mean": (major + minor) / 2}[metric]
        if size * sc < min_size:
            continue
        # area weight: visible area fraction = volume fraction (Delesse);
        # volume weight: per-block ellipsoid, over-weights big blocks
        w = (area * sc * sc if weight == "area"
             else (major * sc) * (minor * sc) ** 2)
        frags.append(Fragment(lid, area, size * sc, major * sc, minor * sc,
                              ecd * sc, w, float(xs.mean()), cy,
                              bool(edge_zone[ys, xs].any())))
    return frags


# ============================================================================
# 4. Gradation
# ============================================================================
def rr_cdf(x, xc, n):
    return 1.0 - np.exp(-(np.asarray(x, float) / xc) ** n)


def curve(frags):
    s = np.array([f.size_mm for f in frags])
    w = np.array([f.weight for f in frags])
    if not len(s) or not np.isfinite(s).all() or not np.isfinite(w).all() or (s <= 0).any() or (w <= 0).any():
        raise ValueError("Fragments must have finite positive sizes and weights")
    o = np.argsort(s, kind="stable")
    cumulative = np.cumsum(w[o] / w.max())
    return s[o], cumulative / cumulative[-1] * 100


def pct_at(s, cum, x):
    # passing at x = mass of fragments strictly smaller than x
    i = np.searchsorted(s, x, side="left")
    return 0.0 if i == 0 else float(cum[i - 1])


def d_at(s, cum, p):
    """Weighted empirical quantile (threshold of the step, not interpolation)."""
    return float(s[min(int(np.searchsorted(cum, p, side="left")), len(s) - 1)])


def fit_rr(s, cum, lo):
    """Least squares on a log-spaced size grid (lo .. top size), so the
    coarse tail counts as much as the many small fragments do."""
    failed = dict(status="unavailable", xc_mm=None, n=None, rmse_pct=None)
    if lo >= s.max() or len(np.unique(s)) < 3:
        return dict(failed, reason="Insufficient size variation above the fit threshold")
    x50 = d_at(s, cum, 50)
    xg = np.logspace(math.log10(max(lo, s.min())), math.log10(s.max()), 25)
    yg = np.array([pct_at(s, cum, x) for x in xg]) / 100
    sel = (yg > 0.01) & (yg < 0.995)
    if sel.sum() < 3 or len(np.unique(yg[sel])) < 3:
        return dict(failed, reason="Insufficient independent cumulative levels for fitting")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", OptimizeWarning)
            (xc, n), covariance = curve_fit(
                rr_cdf, xg[sel], yg[sel],
                p0=[float(np.clip(x50 / 0.693 ** (1 / 1.2), 1.01, 99999)), 1.2],
                bounds=([1, 0.3], [1e5, 5]), maxfev=20000)
        if not np.isfinite(covariance).all() or not np.isfinite([xc, n]).all():
            raise ValueError("Non-finite fit parameters or covariance")
    except (RuntimeError, ValueError, FloatingPointError, OptimizeWarning) as exc:
        return dict(failed, reason=str(exc))
    rmse = float(np.sqrt(np.mean((rr_cdf(xg[sel], xc, n) - yg[sel]) ** 2)) * 100)
    return dict(status="fitted", xc_mm=float(xc), n=float(n), rmse_pct=rmse, reason=None)


def report_distribution(s, cum, fit, fit_min, fines):
    """One distribution and inverse shared by tables, splits, and charts."""
    m0 = pct_at(s, cum, fit_min)
    corrected = fines == "rr" and fit["status"] == "fitted" and m0 < 100
    if not corrected:
        return (lambda x: pct_at(s, cum, x)), (lambda p: d_at(s, cum, p)), "none"
    xc, n = fit["xc_mm"], fit["n"]
    F = float(rr_cdf(fit_min, xc, n) * 100)
    if F >= 100:
        return (lambda x: pct_at(s, cum, x)), (lambda p: d_at(s, cum, p)), "none"

    def passing(x):
        if x < fit_min:
            return float(rr_cdf(max(0, x), xc, n) * 100)
        return float(np.clip(F + (100-F) * (pct_at(s, cum, x)-m0) / (100-m0), 0, 100))

    def quantile(p):
        if p <= F:
            return xc * (-math.log1p(-p / 100)) ** (1 / n)
        return d_at(s, cum, m0 + (p-F) * (100-m0) / (100-F))

    return passing, quantile, "rr"


def rounded(value, digits):
    return round(value, digits) if value is not None and math.isfinite(value) else None


def display(value, digits=1):
    return f"{value:.{digits}f}" if value is not None else "N/A"


# ============================================================================
# 5. Report
# ============================================================================
def table(rows, head):
    w = [max(len(str(h)), *(len(str(r[i])) for r in rows)) for i, h in enumerate(head)]
    out = ["  " + "  ".join(str(h).rjust(x) for h, x in zip(head, w)),
           "  " + "  ".join("-" * x for x in w)]
    out += ["  " + "  ".join(str(c).rjust(x) for c, x in zip(r, w)) for r in rows]
    return "\n".join(out)


def report(frags, meta, args):
    s, cum = curve(frags)
    fit = fit_rr(s, cum, args.fit_min)
    xc, n = fit["xc_mm"], fit["n"]
    rr = lambda x: float(rr_cdf(x, xc, n) * 100) if xc is not None else None
    # Fines correction (Split-style): the camera can't see fines in voids, so
    # below fit_min take the RR curve, and rescale the measured curve above
    # it to fill the rest:  P = F + (100-F) * (m(x)-m0) / (100-m0)
    fm = args.fit_min
    use, quantile, effective = report_distribution(s, cum, fit, fm, args.fines)
    notices = list(meta.get("notices") or [])
    if fit["status"] != "fitted":
        notices.append("Rosin-Rammler fit unavailable: " + fit["reason"])
    if args.fines == "rr" and effective == "none":
        notices.append("Requested fines correction unavailable; report uses measured values.")
    for notice in notices:
        print("WARNING: " + notice, file=sys.stderr)
    bt, bp = args.breaker, args.bypass
    R = dict(schema_version=2, image=meta["name"], mm_per_px=rounded(meta["mmpp"], 4),
             scale_method=meta["method"], fragments=len(frags),
             weighting=args.weight, perspective=args.persp,
             depth_model=meta.get("depth_model"),
             fines_correction=effective, fines_requested=args.fines,
             warnings=notices, accuracy_validated=False,
             delineated_pct=rounded(meta["coverage"], 1),
             rosin_rammler=fit,
             sources=meta.get("sources", []),
             settings={k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()
                       if k not in {"images"}},
             quantile_method="weighted empirical threshold; passing uses size < sieve",
             fragment_coordinate_space="downscaled working image")
    R["runtime"] = dict(python=sys.version.split()[0])
    for package in ("numpy", "scipy", "opencv-python", "ultralytics", "matplotlib"):
        try:
            R["runtime"][package] = version(package)
        except PackageNotFoundError:
            R["runtime"][package] = None

    print("\n" + "=" * 62)
    print(f"  ROCK FRAGMENTATION  -  {meta['name']}")
    print("=" * 62)
    if R["mm_per_px"] is not None:
        print(f"  Scale        : {meta['mmpp']:.3f} mm/px  ({meta['method']})")
        print(f"  Fragments    : {len(frags)}   delineated {meta['coverage']:.0f}% of area")
    else:
        print(f"  Fragments    : {len(frags)}   (pooled, each photo scaled by its own pole)")
    print(f"  Rosin-Rammler: {fit['status']}, xc = {display(xc, 0)} mm, n = {display(n, 2)}")
    print(f"  Fines corr.  : {effective} (requested {args.fines}) below {fm:.0f} mm")
    print(f"  Weighting    : {args.weight}"
          + (f",  perspective {args.persp:g}" if args.persp != 1 else ""))
    model = meta.get("depth_model")
    if model:
        refs = ", ".join(f"row {row:g} = {mmpp:g} mm/px" for row, mmpp in model["references"])
        print(f"  Depth model  : mm/px varies as 1/(row - {model['horizon_row']:g})  [{refs}]")

    rows, R["passing"] = [], []
    for x in STD_SIZES_MM:
        m_, f_, u_ = pct_at(s, cum, x), rr(x), use(x)
        rows.append([x, display(m_), display(f_), display(u_)])
        R["passing"].append(dict(size_mm=x, measured=round(m_, 2),
                                 rr_fit=rounded(f_, 2), report=round(u_, 2)))
    print("\n  CUMULATIVE % PASSING")
    print(table(rows, ["Size mm", "Measured", "RR fit", "Report"]))

    rows, R["bands"] = [], []
    boundaries = sorted(set(BANDS_MM[:-1]) | {bp, bt}) + [None]
    for lo, hi in zip(boundaries[:-1], boundaries[1:]):
        ret = (use(hi) if hi else 100.0) - (use(lo) if lo else 0.0)
        name = f"{lo:g}-{hi:g}" if hi is not None else f">={lo:g}"
        dest = ("bypass" if hi and hi <= bp else
                "BREAKER" if lo >= bt else "crusher")
        rows.append([name, f"{ret:.1f}", dest])
        R["bands"].append(dict(band_mm=name, retained_pct=round(ret, 2),
                               destination=dest))
    print("\n  % RETAINED BY BAND")
    print(table(rows, ["Band mm", "% ret", "Destination"]))

    split = dict(bypass=use(bp), crusher=use(bt) - use(bp), breaker=100 - use(bt))
    R["split"] = {k: round(v, 2) for k, v in split.items()}
    print("\n  SUMMARY SPLIT")
    print(f"    Bypass   (<{bp:.0f} mm)      : {split['bypass']:5.1f} %")
    print(f"    Crusher  ({bp:.0f}-{bt:.0f} mm)    : {split['crusher']:5.1f} %")
    print(f"    BREAKER  (>={bt:.0f} mm)    : {split['breaker']:5.1f} %")
    n_over = sum(f.size_mm >= bt for f in frags)
    R["oversize_blocks"] = n_over
    print(f"    Oversize blocks counted  : {n_over}")

    rows, R["d_values"] = [], {}
    for p in D_VALUES:
        dm = d_at(s, cum, p)
        df = xc * (-math.log(1 - p / 100)) ** (1 / n) if xc is not None else None
        dv = quantile(p)
        R["d_values"][f"D{p}"] = round(dv, 1)
        rows.append([f"D{p}", display(dm, 0), display(df, 0), display(dv, 0)])
    print("\n  CHARACTERISTIC SIZES (mm)")
    print(table(rows, ["", "Measured", "RR fit", "Report"]))
    R["top_size_mm"] = round(float(s.max()), 1)
    R["Cu"] = round(quantile(60) / quantile(10), 2)
    print(f"    Top size (largest block) : {s.max():.0f} mm")
    print(f"    Cu = D60/D10             : {R['Cu']:.1f}")
    print("\n  Accuracy is unvalidated; the earlier +/-25-30% estimate was not verified."
          "\n  Surface only: inspect overlays and compare with physical measurements."
          "\n  Several photos improve sampling but do not establish accuracy.")
    R["_curve"] = (s, cum, xc, n)
    return R


def output_paths(stem, overlay=True, overlay_ext=OVERLAY_DEFAULT):
    suffixes = ["_gradation.csv", "_fragments.csv", "_curve.png", "_result.json"]
    if overlay:
        suffixes.insert(0, f"_overlay.{overlay_ext}")
    return [Path(str(stem) + suffix) for suffix in suffixes]


def save_outputs(R, frags, a, stem, args):
    """Stage a complete report before publishing; JSON is published last."""
    ext = getattr(args, "overlay_format", OVERLAY_DEFAULT)
    paths = output_paths(stem, a is not None, ext)
    if not getattr(args, "overwrite", False) and any(p.exists() for p in paths):
        raise FileExistsError(f"Output exists for {stem}; choose another --out or use --overwrite")
    parent = Path(stem).parent
    with tempfile.TemporaryDirectory(prefix=".gradation-", dir=parent) as folder:
        staged = Path(folder) / Path(stem).name
        _save_outputs(R, frags, a, str(staged), args)
        for src, dst in zip(output_paths(staged, a is not None, ext), paths):
            if not src.is_file() or src.stat().st_size == 0:
                raise OSError(f"Missing or empty output: {src.name}")
        for src, dst in zip(output_paths(staged, a is not None, ext), paths):
            src.replace(dst)
    print("Saved: " + ", ".join(str(p) for p in paths))


def _save_outputs(R, frags, a, stem, args):
    s, cum, xc, n = R["_curve"]
    # ---- CSVs
    with open(f"{stem}_gradation.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["size_mm", "measured_%passing", "RR_fit_%passing", "report_%passing"])
        for r in R["passing"]:
            w.writerow([r["size_mm"], r["measured"], r["rr_fit"], r["report"]])
        w.writerow([])
        w.writerow(["band_mm", "%retained", "destination"])
        for b in R["bands"]:
            w.writerow([b["band_mm"], b["retained_pct"], b["destination"]])
        w.writerow([])
        for k, v in R["d_values"].items():
            w.writerow([k + "_mm", v])
        for k, v in [("top_size_mm", R["top_size_mm"]), ("Cu", R["Cu"]),
                     ("RR_xc_mm", R["rosin_rammler"]["xc_mm"]),
                     ("RR_n", R["rosin_rammler"]["n"]),
                     ("mm_per_px", R["mm_per_px"]), ("fragments", R["fragments"])]:
            w.writerow([k, v])
        for k, v in R["split"].items():
            w.writerow([f"split_{k}_%", v])
        w.writerow(["fit_status", R["rosin_rammler"]["status"]])
        w.writerow(["fines_requested", R["fines_requested"]])
        w.writerow(["fines_effective", R["fines_correction"]])
        for notice in R["warnings"]:
            w.writerow(["warning", notice])
    with open(f"{stem}_fragments.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "size_mm", "major_mm", "minor_mm", "ecd_mm",
                    "area_px", "x_px", "y_px", "cut_by_edge", "source_image", "source_label", "weight"])
        for export_id, f in enumerate(sorted(frags, key=lambda f: -f.size_mm), 1):
            w.writerow([export_id, round(f.size_mm, 3), round(f.major_mm, 3), round(f.minor_mm, 3),
                        round(f.ecd_mm, 3), f.area_px, round(f.cx, 3), round(f.cy, 3), f.edge,
                        f.source_image, f.label, f.weight])
    with open(f"{stem}_result.json", "w", encoding="utf-8") as fh:
        json.dump({k: v for k, v in R.items() if not k.startswith("_")}, fh,
                  indent=2, ensure_ascii=False, allow_nan=False)

    # ---- overlay
    if a is not None:
        bgr, labels = a["bgr"], a["labels"]
        vis = bgr.copy()
        classes = overlay_classes(args.breaker)
        lut = np.zeros((labels.max() + 1, 3), np.uint8)
        for f in frags:
            # Size classes, not crusher destinations: the band just under the
            # breaker limit is the one an operator reads first.
            for lower, colour, _ in classes:
                if f.size_mm >= lower:
                    lut[f.label] = colour
                    break
        col = lut[labels]
        msk = col.any(-1)
        vis[msk] = (0.55 * vis[msk] + 0.45 * col[msk]).astype(np.uint8)
        edge = cv2.morphologyEx(labels.astype(np.uint16), cv2.MORPH_GRADIENT,
                                np.ones((3, 3), np.uint8)) > 0
        vis[edge & msk] = (25, 25, 25)
        fs = max(0.45, bgr.shape[1] / 2600)
        for f in frags:
            if f.size_mm >= args.breaker:
                t = f"{f.size_mm:.0f}"
                org = (int(f.cx) - 18, int(f.cy) + 6)
                cv2.putText(vis, t, org, cv2.FONT_HERSHEY_SIMPLEX, fs, (255, 255, 255), 4, cv2.LINE_AA)
                cv2.putText(vis, t, org, cv2.FONT_HERSHEY_SIMPLEX, fs, (0, 0, 180), 2, cv2.LINE_AA)
        cnts, _ = cv2.findContours(a["roi"], cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(vis, cnts, -1, (0, 255, 255), 2)
        if a["scale"].pole_line is not None:
            x1, y1, x2, y2 = map(int, a["scale"].pole_line)
            cv2.line(vis, (x1, y1), (x2, y2), (255, 0, 255), 2)
            cv2.putText(vis, f"{R['mm_per_px']:.2f} mm/px", (x1, y1 - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, fs * 1.2, (255, 0, 255), 2, cv2.LINE_AA)
        # legend
        items = [(colour, label) for _, colour, label in classes]
        y = 30
        cv2.rectangle(vis, (10, 8), (260, 18 + 28 * len(items)), (255, 255, 255), -1)
        for c, t in items:
            cv2.rectangle(vis, (20, y - 14), (40, y + 2), c, -1)
            cv2.putText(vis, t, (50, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1, cv2.LINE_AA)
            y += 28
        ext = getattr(args, "overlay_format", OVERLAY_DEFAULT)
        params = [cv2.IMWRITE_JPEG_QUALITY, 90] if ext in ("jpg", "jpeg") else []
        ok, encoded = cv2.imencode(f".{ext}", vis, params)
        if not ok:
            raise OSError(f"Failed to encode overlay image as .{ext}")
        Path(f"{stem}_overlay.{ext}").write_bytes(encoded.tobytes())

    # ---- curve
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    xs = np.logspace(0.5, math.log10(max(2000, s.max() * 1.3)), 300)
    fig, ax = plt.subplots(figsize=(8.5, 5.2), dpi=130)
    ax.step(np.r_[s, s.max() * 1.02], np.r_[cum, 100], where="post", color="#666",
            lw=1.3, label=f"Measured ({len(frags)} fragments)")
    if xc is not None:
        ax.plot(xs, rr_cdf(xs, xc, n) * 100, color="#c0392b", lw=2.2,
                label=f"Rosin-Rammler  xc = {xc:.0f} mm, n = {n:.2f}")
    use, _, effective = report_distribution(s, cum, R["rosin_rammler"], args.fit_min, R["fines_correction"])
    plot_x = np.unique(np.r_[xs, s, np.nextafter(s, np.inf), args.fit_min])
    ax.plot(plot_x, [use(x) for x in plot_x], color="#1f5fa8", lw=1.8,
            label="Report (fines-corrected)" if effective == "rr" else "Report (measured)")
    ax.axvline(args.breaker, color="#2c3e50", ls="--", lw=1.2)
    over = R["split"]["breaker"]
    ax.text(args.breaker * 1.04, 8, f"breaker {args.breaker:.0f} mm\n{over:.0f}% oversize",
            color="#2c3e50", fontsize=9)
    if effective == "rr":
        ax.axvspan(1, args.fit_min, color="#999", alpha=0.12)
        ax.text(args.fit_min * 0.95, 55, "fines:\nRR-corrected\n(not visible)", ha="right",
                fontsize=8, color="#666")
    ax.set_xscale("log")
    ax.set_xlim(5, xs.max())
    ax.set_ylim(0, 100)
    ax.set_xlabel("Size (mm)")
    ax.set_ylabel("Cumulative % passing")
    ax.set_title(f"Fragmentation - {R['image']}\nAccuracy unvalidated; fit: {R['rosin_rammler']['status']}")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(loc="upper left")
    fig.tight_layout()
    try:
        fig.savefig(f"{stem}_curve.png")
    finally:
        plt.close(fig)


# ============================================================================
# Driver
# ============================================================================
def box(txt):
    v = [float(t) for t in txt.split(",")]
    if len(v) != 4:
        raise argparse.ArgumentTypeError("need 4 comma-separated numbers")
    return v


def depth_ref(txt):
    """ROW,MM_PER_PX depth calibration point, in original-photo units."""
    parts = txt.split(",")
    if len(parts) != 2:
        raise argparse.ArgumentTypeError("need ROW,MM_PER_PX")
    try:
        row, mmpp = float(parts[0]), float(parts[1])
    except ValueError:
        raise argparse.ArgumentTypeError("ROW and MM_PER_PX must be numbers")
    if not math.isfinite(row) or not math.isfinite(mmpp) or mmpp <= 0:
        raise argparse.ArgumentTypeError("ROW must be finite and MM_PER_PX finite and positive")
    return (row, mmpp)


def validate_args(args, parser):
    for name in ("segment_length", "pole_length", "breaker", "min_size", "fit_min", "persp"):
        value = getattr(args, name)
        if not math.isfinite(value) or value <= 0:
            parser.error(f"--{name.replace('_', '-')} must be finite and positive")
    if args.scale is not None and (not math.isfinite(args.scale) or args.scale <= 0):
        parser.error("--scale must be finite and positive")
    if not math.isfinite(args.bypass) or not 0 <= args.bypass < args.breaker:
        parser.error("Require 0 <= --bypass < --breaker")
    if not math.isfinite(args.conf) or not 0 < args.conf <= 1:
        parser.error("--conf must be in (0, 1]")
    for name in ("work_width", "imgsz", "max_det"):
        if getattr(args, name) <= 0:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    if args.scale is not None and args.pole_px is not None:
        parser.error("Choose either --scale or --pole-px")
    if args.persp_ref and args.persp != 1.0:
        parser.error("--persp-ref fits the depth curve from measurements and replaces the "
                     "--persp straight line; use one or the other")
    if args.persp_ref and len({row for row, _ in args.persp_ref}) != len(args.persp_ref):
        parser.error("--persp-ref rows must differ; each point needs its own distance")
    for name in ("roi", "pole_px"):
        coords = getattr(args, name)
        if coords is not None and any(not math.isfinite(c) or c < 0 for c in coords):
            parser.error(f"--{name.replace('_', '-')} requires finite nonnegative coordinates")
    if args.pole_px is not None and args.pole_px[:2] == args.pole_px[2:]:
        parser.error("--pole-px endpoints must differ")
    if args.roi is not None:
        x, y, w, h = args.roi
        if w <= 0 or h <= 0:
            parser.error("ROI width and height must be positive")
        if all(c <= 1 for c in args.roi) and (x+w > 1 or y+h > 1):
            parser.error("Fractional ROI must remain within the image")


def preflight_outputs(args, parser):
    stems = [(args.out or img.parent) / img.stem for img in args.images]
    if args.combine and len(args.images) > 1:
        stems.append((args.out or args.images[0].parent) / "combined")
    names = [str(stem.resolve()).casefold() for stem in stems]
    if len(names) != len(set(names)):
        parser.error("Input stems collide in output paths; rename inputs or use separate runs")
    for img in args.images:
        if not img.is_file():
            parser.error(f"Input is not a file: {img}. Pass explicit paths, not wildcard strings.")
    for index, stem in enumerate(stems):
        for path in output_paths(stem, index < len(args.images), args.overlay_format):
            if path.is_dir() or (path.exists() and not args.overwrite):
                parser.error(f"Output already exists: {path}; choose another --out or use --overwrite")


def analyse(path: Path, args):
    data = np.fromfile(path, dtype=np.uint8)
    bgr0 = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None
    if bgr0 is None:
        raise SystemExit(f"Cannot read {path}")
    k = min(1.0, args.work_width / bgr0.shape[1])
    bgr = cv2.resize(bgr0, None, fx=k, fy=k, interpolation=cv2.INTER_AREA) if k < 1 else bgr0
    H, W = bgr.shape[:2]
    if args.pole_px is not None:
        x1, y1, x2, y2 = args.pole_px
        if not (0 <= x1 < bgr0.shape[1] and 0 <= x2 < bgr0.shape[1]
                and 0 <= y1 < bgr0.shape[0] and 0 <= y2 < bgr0.shape[0]):
            raise SystemExit("--pole-px endpoints must lie within the original image")

    auto = detect_pole(bgr, args.segment_length)
    if args.scale is not None:
        scale = ScaleResult(args.scale / k, "manual --scale")
    elif args.pole_px:
        x1, y1, x2, y2 = [c * k for c in args.pole_px]
        scale = ScaleResult(args.pole_length / math.hypot(x2 - x1, y2 - y1),
                            "manual --pole-px", pole_line=(x1, y1, x2, y2))
        band = np.zeros((H, W), np.uint8)
        cv2.line(band, (int(x1), int(y1)), (int(x2), int(y2)), 1, 20)
        scale.pole_mask = band
    elif auto:
        scale = auto
    else:
        raise SystemExit("Pole not found - use --scale or --pole-px/--pole-length")
    if scale.pole_mask is None and auto:
        scale.pole_mask, scale.pole_line = auto.pole_mask, auto.pole_line
    mmpp = scale.mm_per_px
    if not math.isfinite(mmpp) or mmpp <= 0:
        raise SystemExit("Calibration did not produce a finite positive scale")

    roi = np.zeros((H, W), np.uint8)
    if args.roi:
        r_ = args.roi
        if all(0 <= c <= 1 for c in r_):          # fractions of the photo
            r_ = [r_[0] * W / k, r_[1] * H / k, r_[2] * W / k, r_[3] * H / k]
        x, y, w, h = [int(round(c * k)) for c in r_]
        if w <= 0 or h <= 0 or x < 0 or y < 0 or x+w > W or y+h > H:
            raise SystemExit("ROI must be nonempty and inside the image at working resolution")
        roi[max(0, y):min(H, y + h), max(0, x):min(W, x + w)] = 1
    else:
        roi[:] = 1
    excl = (roi == 0).astype(np.uint8)
    if scale.pole_mask is not None:
        excl |= scale.pole_mask
    edge_zone = cv2.dilate(excl, np.ones((5, 5), np.uint8)).astype(bool)
    edge_zone[:3, :] = edge_zone[-3:, :] = True
    edge_zone[:, :3] = edge_zone[:, -3:] = True

    # Resolution floor only; enforce the chosen physical metric after measurement.
    min_px = 15
    print(f"[{path.name}] segmenting ...", file=sys.stderr)
    masks = run_fastsam(bgr, args.model, args.imgsz, args.conf, 0.6, args.max_det)
    labels = resolve_masks(masks, (H, W), excl, min_px)
    pole_y = (0.5 * (scale.pole_line[1] + scale.pole_line[3])
              if scale.pole_line is not None else H / 2)
    depth, refs = None, []
    if scale.pole_line is not None:
        refs.append((pole_y, mmpp))
    for row, ref_mmpp in (args.persp_ref or []):
        refs.append((row * k, ref_mmpp / k))     # caller gives original-photo units
    if args.persp_ref:
        if len(refs) < 2:
            raise SystemExit(
                "--persp-ref needs a second depth reference. Either pass two --persp-ref "
                "points, or use a photo whose pole is detected so it supplies the first.")
        try:
            depth = fit_depth_model(refs)
        except ValueError as exc:
            raise SystemExit(f"Perspective calibration failed: {exc}")
    frags = measure(labels, mmpp, min_px, edge_zone, args.metric,
                    args.weight, args.persp, pole_y, min_size=args.min_size, depth=depth)
    for fragment in frags:
        fragment.source_image = str(path.resolve())
    if not args.keep_edge:
        frags = [f for f in frags if not f.edge]
    if len(frags) < 10:
        raise SystemExit(f"Only {len(frags)} fragments found - check photo/ROI.")
    roi_px = int((excl == 0).sum())
    cov = 100 * sum(f.area_px for f in frags) / max(roi_px, 1)
    a = dict(bgr=bgr, labels=labels, roi=roi, scale=scale)
    source = dict(path=str(path.resolve()), mm_per_px=mmpp*k, work_scale=k,
                  original_size=[bgr0.shape[1], bgr0.shape[0]], work_size=[W, H],
                  scale_method=scale.method, scale_detail=scale.detail,
                  sha256=hashlib.sha256(data.tobytes()).hexdigest())
    model = None
    if depth is not None:
        model = dict(kind="inverse-row", horizon_row=rounded(depth.horizon / k, 1),
                     references=[[rounded(row / k, 1), rounded(ref * k, 4)]
                                 for row, ref in depth.refs])
    # No automatic "you need perspective correction" warning: the only signal
    # available from one photo is how far fragments sit from the pole row, and
    # row spread is not depth spread. A square-on shot spans many rows at nearly
    # constant depth, so that test fires on good photos too. Whether a depth
    # model was applied is recorded factually in depth_model / perspective.
    meta = dict(name=path.name, mmpp=mmpp * k, method=scale.method, coverage=cov,
                sources=[source], depth_model=model, notices=[])
    return frags, a, meta


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("images", nargs="+", type=Path)
    ap.add_argument("--segment-length", type=float, default=400,
                    help="one red/white pole segment, mm (400)")
    ap.add_argument("--scale", type=float, help="manual mm per pixel of the original photo")
    ap.add_argument("--pole-px", type=box,
                    help="pole ends x1,y1,x2,y2 in pixels - ends of the painted "
                         "segments, not the tip")
    ap.add_argument("--pole-length", type=float, default=2000, help="for --pole-px, mm")
    ap.add_argument("--roi", type=box,
                    help="analyse box x,y,w,h in pixels, or as fractions "
                         "e.g. 0,0.2,1,0.8 = skip the top 20%% of the photo")
    ap.add_argument("--breaker", type=float, default=400, help="oversize limit, mm (400)")
    ap.add_argument("--bypass", type=float, default=10, help="crusher bypass size, mm (10)")
    ap.add_argument("--min-size", type=float, default=30, help="smallest fragment kept, mm (30)")
    ap.add_argument("--fit-min", type=float, default=50,
                    help="fines correction below this size, mm (50)")
    ap.add_argument("--fines", choices=["rr", "none"], default="rr",
                    help="fines correction below --fit-min (rr = Rosin-Rammler, default)")
    ap.add_argument("--metric", choices=["minor", "mean", "ecd"], default="minor",
                    help="sieve size = ellipse minor axis (default)")
    ap.add_argument("--weight", choices=["area", "volume"], default="area",
                    help="area = visible-area fraction (Delesse, default); "
                         "volume = per-block ellipsoid")
    ap.add_argument("--persp-ref", action="append", type=depth_ref, metavar="ROW,MM_PER_PX",
                    help="depth calibration point in ORIGINAL photo pixels: the pole's image "
                         "row and its mm/px, taken from another photo shot from the same "
                         "camera position with the pole at a different distance. Repeatable. "
                         "Together with this photo's own pole it fits the true "
                         "1/(row-horizon) depth curve instead of the --persp straight line")
    ap.add_argument("--persp", type=float, default=1.0,
                    help="perspective: scale at photo bottom / scale at pole row, "
                         "e.g. 0.7 if foreground is ~30%% closer (default 1 = off)")
    ap.add_argument("--keep-edge", action="store_true", default=True,
                    help="keep blocks cut by photo/ROI edge (default on)")
    ap.add_argument("--drop-edge", dest="keep_edge", action="store_false")
    ap.add_argument("--model", default="FastSAM-x.pt", help="FastSAM-x.pt or FastSAM-s.pt")
    ap.add_argument("--imgsz", type=int, default=1472, help="model input size (1472)")
    ap.add_argument("--conf", type=float, default=0.2)
    ap.add_argument("--max-det", type=int, default=1500)
    ap.add_argument("--work-width", type=int, default=2000)
    ap.add_argument("--combine", action="store_true", help="also merge all photos")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--overwrite", action="store_true", help="explicitly replace existing reports")
    ap.add_argument("--overlay-format", choices=OVERLAY_FORMATS, default=OVERLAY_DEFAULT,
                    help="overlay container (jpg). Use png where endpoint-security "
                         "policy forbids scripts from creating *.jpg files")
    args = ap.parse_args(argv)
    validate_args(args, ap)
    preflight_outputs(args, ap)

    pooled = []
    sources = []
    for img in args.images:
        frags, a, meta = analyse(img, args)
        outdir = args.out or img.parent
        outdir.mkdir(parents=True, exist_ok=True)
        stem = str(outdir / img.stem)
        R = report(frags, meta, args)
        try:
            save_outputs(R, frags, a, stem, args)
        except OSError as exc:
            ap.exit(1, f"Output write failed: {exc}\nNo success claimed; check permissions and output files.\n")
        pooled += frags
        sources.extend(meta["sources"])

    if args.combine and len(args.images) > 1:
        outdir = args.out or args.images[0].parent
        meta = dict(name=f"COMBINED {len(args.images)} photos", mmpp=None,
                    method="per photo", coverage=None, sources=sources)
        R = report(pooled, meta, args)
        try:
            save_outputs(R, pooled, None, str(outdir / "combined"), args)
        except OSError as exc:
            ap.exit(1, f"Combined output write failed: {exc}\nEarlier per-photo reports may exist.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
