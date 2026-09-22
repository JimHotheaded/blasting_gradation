# Repository Audit Report

Date: 2026-09-22  
Scope: `rock_gradation.py`, `.claude/gradation_run.py`, repository guidance, dependencies, and tracked sample CSV.  
Mode: Read-only inspection and in-memory verification; no fixes applied.

## Summary

The code has confirmed calculation defects that can materially change reported gradation and operational splits. Address findings 1–3 before relying on the report for production decisions. Additional issues affect exports, parameter handling, and reproducibility.

Severity indicates potential impact, not how frequently an issue occurs. “Reproduced” means demonstrated using synthetic inputs against the current functions. “Inspection” means the relevant execution path was reviewed without performing its filesystem writes.

## Findings

### 1. High — Fines correction can invent oversize material when every fragment is below the fit threshold

**Location:** `rock_gradation.py:362–368`, `412–413`  
**Evidence:** Reproduced.

When all measured fragments are below `fit_min`, `m0` is 100. The denominator guard prevents division by zero, but the corrected curve above the threshold remains at `F` instead of reaching 100%. Its missing mass becomes apparent oversize.

Using ten equal-weight fragments sized 30, 32, …, 48 mm with default thresholds produced:

- Largest measured fragment: 48 mm.
- Passing at 1,200 mm: measured 100%, report 92.07%.
- Breaker fraction above the 400 mm threshold: 7.93%.

**Recommendation:** Define an explicit policy for a correction threshold at or above the measured maximum; reject unsupported correction or use a valid normalized alternative. Check that report passing reaches 100% beyond the observed maximum when retaining the measured coarse tail.

### 2. High — `--fines none` does not disable fines correction

**Location:** `rock_gradation.py:363–368`, `425–429`  
**Evidence:** Reproduced.

The option changes `F`, but the below-threshold branch still uses the Rosin–Rammler curve. The D-value branch also retains the modeled inverse.

With equal-weight sizes `[10,20,30,40,60,100,200,400,600,800]` and `fines='none'`, passing at 10 mm was measured 0% but reported 20.91%; at 25 mm it was measured 20% but reported 30.63%.

**Recommendation:** Make the disabled-correction path consistently use the measured distribution for passing, splits, bands, and characteristic sizes. Update chart labels accordingly.

### 3. High — Overlapping child masks are double-counted when deciding to discard a parent

**Location:** `rock_gradation.py:225–244`  
**Evidence:** Reproduced with constructed boolean masks.

Coverage is calculated by summing child areas, rather than measuring their unique coverage of the parent. Overlapping or duplicate child masks can therefore satisfy the 50% group threshold without covering half the parent.

A 1,600-pixel parent with two identical 480-pixel children retained only 480 pixels after resolution. Unique child coverage was 30%, but summed coverage was 60%, causing the parent to be discarded. This can understate rock sizes and omit area.

**Recommendation:** Deduplicate masks or calculate the union of child intersections with the parent before applying the group rule. Add overlapping-mask regression cases.

### 4. Medium — Combined output contains non-standard JSON values and ambiguous fragment IDs

**Location:** `rock_gradation.py:370–374`, `466–474`, `678–685`  
**Evidence:** Serialization reproduced; pooled export structure inspected.

Combined metadata deliberately uses NaN for scale and coverage. `json.dump` emits these as literal `NaN`, which strict JSON consumers reject. A strict serialization check using `allow_nan=False` raised `ValueError`.

Pooled fragments also retain image-local labels, while the combined fragment CSV has no source-image column. Labels and pixel coordinates from different images cannot be unambiguously traced back to their photos.

**Recommendation:** Represent unavailable values as JSON `null`. Preserve photo identity and use unique compound fragment identifiers in combined exports.

### 5. Medium — Different input images can silently overwrite each other's outputs

**Location:** `rock_gradation.py:447–474`, `521`, `552`, `671–675`, `685`  
**Evidence:** Inspection and in-memory path construction.

Output identity uses only the input stem. With a shared `--out`, `shot1/image.jpg`, `shot2/image.jpg`, and `image.png` all resolve to the same output prefix. Later files overwrite earlier reports. An input named `combined.jpg` can also collide with the combined report prefix.

**Recommendation:** Detect collisions before processing and require distinct output names or per-image directories. Decide explicitly whether overwriting an existing run is allowed.

### 6. Medium — Overlay write failures are ignored while success is announced

**Location:** `rock_gradation.py:521`, `676–677`; `.claude/gradation_run.py:26–29`, `63–70`  
**Evidence:** Inspection; the wrapper docstring also records a previous local failure mode.

The main program ignores the boolean result of `cv2.imwrite`, then prints that the overlay was saved. The wrapper similarly does nothing when `cv2.imencode` returns false, and the main success message still names `.jpg` even though the wrapper writes `.jpeg`.

The overlay is the documented quality-control artifact, so falsely announcing its creation undermines validation.

**Recommendation:** Check encoding/writing results, verify the expected file, and fail clearly on missing output. Print the actual filename. The machine-specific policy described in the wrapper was not independently tested or bypassed during this audit.

### 7. Medium — Numeric options lack range and relationship validation

**Location:** `rock_gradation.py:575–580`, `593–608`, `631–666`, `412`  
**Evidence:** Negative split reproduced; other paths inspected.

With `bypass=400` and `breaker=100`, the synthetic sample from finding 2 produced a crusher fraction of **−19.35%**. Argument parsing accepts these values without checking their ordering.

Other unguarded inputs include zero or negative lengths, non-finite floats, zero work width, identical pole endpoints, and invalid ROI dimensions. These can cause misleading results or downstream exceptions rather than actionable CLI errors.

**Recommendation:** Validate finite positive scales and lengths, image dimensions, ROI bounds, and `0 <= bypass < breaker` before image processing. Reject coincident pole endpoints.

### 8. Medium — Custom thresholds disagree with fixed-band destination labels

**Location:** `rock_gradation.py:56`, `400–408`, `412`  
**Evidence:** Reproduced.

Bands remain fixed even when a breaker or bypass threshold falls inside one. With `breaker=350`, the entire 300–400 mm band is labeled `crusher`, although its 350–400 mm portion belongs to the breaker split.

For equal-weight sizes `[40,60,100,200,320,360,380,400,600,800]`, that band reported 30.12% retained and labeled all of it crusher.

**Recommendation:** Split bands at configured operational thresholds or label intersected bands as mixed, with their portions explicitly accounted for.

### 9. Medium — `--min-size` filters area, not the selected reported size

**Location:** `rock_gradation.py:269–299`, `608–615`, `643`  
**Evidence:** Reproduced.

The advertised smallest fragment size is converted into a circular pixel-area cutoff. It is not checked against the resulting minor-axis, mean-axis, or perspective-adjusted size.

At 1 mm/pixel, an 80 × 10 pixel rectangle passed the default 30 mm minimum-area cutoff but had a reported minor-axis size of approximately **11.26 mm**.

**Recommendation:** Apply the user-facing cutoff to the final chosen size metric, or rename/document the option as an equivalent-area prefilter. Account for perspective when defining the intended cutoff.

### 10. Medium — Failed Rosin–Rammler fits silently become assumed fits

**Location:** `rock_gradation.py:327–341`, `363`, `375`, `385`  
**Evidence:** Reproduced.

Any fitting exception substitutes a fixed exponent of 1.2 and a median-derived scale. No status distinguishes this fallback from a successful fit, even though it drives the default fines correction.

Ten equal-size 100 mm fragments produced `xc_mm=135.7, n=1.2` through the fallback, presented as ordinary fit parameters.

**Recommendation:** Export fit status and diagnostics, warn when fitting is unsupported, and require an explicit fallback policy before using assumed parameters in deliverable figures.

## Additional Observations

- **Quantile convention:** `d_at` (`323–324`) uses linear interpolation while `pct_at` (`317–320`) uses a strict empirical step distribution. For two equal-weight fragments of 100 and 500 mm, D60 is 180 mm, but measured passing at 180 mm is 50%. Interpolated quantiles can be intentional, but they are not exact inverses of the displayed step distribution. Document the convention and test correction-boundary behavior.
- **Windows wildcard example:** README's `shot12\*.jpg` example is not expanded by this CLI (`630`, `669–670`). In PowerShell, explicitly enumerate paths or implement expansion.
- **Reproducibility:** Requirements are largely unpinned, and no automated tests or coverage requirements exist. Dependency vulnerability status was not assessed; absence of a lockfile alone does not establish a vulnerability.
- **Documentation:** `CLAUDE.md` incorrectly says there is no Git repository. The current guide omits the tracked `.claude/` wrapper and command workflow.

## Validation and Limitations

Both Python files passed in-memory compilation. Focused checks ran with `.venv/Scripts/python.exe -B -`, importing the current source and using synthetic fragments and masks. No test scripts were added, bytecode generation was disabled, and no fixes were made.

The audit did not run FastSAM inference, download weights, install packages, rerun photo analyses, invoke the wrapper's rename instructions, or write analysis outputs. Therefore, segmentation accuracy on real quarry photos, calibration accuracy, claimed percentage error bounds, and dependency security remain unverified. Existing sample CSV values were inspected, not independently regenerated.

SHA-256 comparison of 30 existing files outside `.git/` and `.venv/` found no changes or additions before report creation. Git initially showed the existing untracked `AGENTS.md`; it was left unchanged. This audit report is the only intended new file.

## Suggested Follow-up Order

1. Resolve and regression-test findings 1–3 with explicit mathematical invariants.
2. Correct export integrity and parameter validation in findings 4–8.
3. Define minimum-size and fit-failure semantics for findings 9–10.
4. Run a controlled real-photo comparison, inspect overlays, and record settings and model/dependency versions before accepting revised results.
