import contextlib
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import rock_gradation as g


def fragments(sizes):
    return [g.Fragment(i+1, 100, float(s), float(s), float(s), float(s),
                       1., 20., 20., False, f"photo-{i % 2}.jpg")
            for i, s in enumerate(sizes)]


def options(**changes):
    values = dict(fit_min=50., fines="rr", breaker=400., bypass=10.,
                  weight="area", persp=1., overwrite=False)
    values.update(changes)
    return SimpleNamespace(**values)


def report(sizes, **changes):
    fs = fragments(sizes)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        result = g.report(fs, dict(name="synthetic", mmpp=1., method="manual", coverage=100.),
                          options(**changes))
    return result, fs


class CalculationTests(unittest.TestCase):
    def test_no_correction_preserves_measured_distribution(self):
        r, fs = report([10, 20, 30, 40, 60, 100, 200, 400, 600, 800], fines="none")
        self.assertTrue(all(p["measured"] == p["report"] for p in r["passing"]))
        s, c = g.curve(fs)
        self.assertEqual(r["d_values"]["D60"], g.d_at(s, c, 60))

    def test_all_below_fit_has_no_invented_oversize(self):
        r, _ = report(range(30, 50, 2))
        self.assertEqual(r["split"]["breaker"], 0)
        self.assertEqual(r["passing"][-1]["report"], 100)
        self.assertEqual(r["fines_correction"], "none")
        self.assertTrue(r["warnings"])

    def test_equal_sizes_produce_explicit_unavailable_fit(self):
        r, _ = report([100] * 10)
        self.assertEqual(r["rosin_rammler"]["status"], "unavailable")
        self.assertIsNone(r["rosin_rammler"]["xc_mm"])
        self.assertEqual(r["d_values"]["D50"], 100)

    def test_optimizer_failure_is_reported(self):
        with patch.object(g, "curve_fit", side_effect=RuntimeError("test failure")):
            r, _ = report([10, 20, 30, 40, 60, 100, 200, 400, 600, 800])
        self.assertEqual(r["rosin_rammler"]["reason"], "test failure")
        self.assertEqual(r["fines_correction"], "none")

    def test_distribution_invariants_and_quantile_boundaries(self):
        for sizes in ([10, 20, 30, 40, 60, 100, 200, 400, 600, 800],
                      [50, 50, 100, 100, 500, 500], list(range(30, 50, 2))):
            for fines in ("rr", "none"):
                with self.subTest(sizes=sizes, fines=fines):
                    s, c = g.curve(fragments(sizes))
                    fit = g.fit_rr(s, c, 50)
                    passing, quantile, _ = g.report_distribution(s, c, fit, 50, fines)
                    xs = np.unique(np.r_[0, np.geomspace(1, 2000, 400), s, np.nextafter(s, np.inf), 50])
                    ys = np.array([passing(x) for x in xs])
                    self.assertTrue(((ys >= 0) & (ys <= 100)).all())
                    self.assertTrue((np.diff(ys) >= -1e-10).all())
                    self.assertEqual(passing(2000), 100)
                    for p in (10, 50, 60, 95):
                        d = quantile(p)
                        self.assertLessEqual(passing(np.nextafter(d, -np.inf)), p + 1e-8)
                        self.assertGreaterEqual(passing(np.nextafter(d, np.inf)), p - 1e-8)
                    r, _ = report(sizes, fines=fines)
                    self.assertAlmostEqual(sum(r["split"].values()), 100, delta=.02)
                    self.assertAlmostEqual(sum(b["retained_pct"] for b in r["bands"]), 100, delta=.06)

    def test_custom_thresholds_split_bands(self):
        r, _ = report([40, 60, 100, 200, 320, 360, 380, 400, 600, 800], breaker=350, bypass=35)
        bands = {b["band_mm"]: b for b in r["bands"]}
        self.assertEqual(bands["300-350"]["destination"], "crusher")
        self.assertEqual(bands["350-400"]["destination"], "BREAKER")
        self.assertEqual(bands["25-35"]["destination"], "bypass")

    def test_empirical_quantile_is_observed_threshold(self):
        s, c = g.curve(fragments([100, 500]))
        self.assertEqual(g.d_at(s, c, 60), 500)


class MaskTests(unittest.TestCase):
    def resolve(self, arrays):
        masks = [dict(box=(0, 100, 0, 100), m=a.copy(), area=int(a.sum())) for a in arrays]
        return g.resolve_masks(masks, (100, 100), np.zeros((100, 100), np.uint8), 15)

    def test_duplicate_children_do_not_destroy_parent(self):
        parent = np.zeros((100, 100), bool)
        parent[10:50, 10:50] = True
        child = np.zeros_like(parent)
        child[10:50, 10:22] = True
        labels = self.resolve([parent, child, child])
        self.assertEqual(np.count_nonzero(labels), 1600)

    def test_distinct_children_can_replace_group(self):
        parent = np.zeros((100, 100), bool)
        parent[10:50, 10:50] = True
        left, right = np.zeros_like(parent), np.zeros_like(parent)
        left[10:50, 10:30] = True
        right[10:50, 30:50] = True
        labels = self.resolve([parent, left, right])
        self.assertEqual(np.count_nonzero(labels), 1600)
        self.assertEqual(len(np.unique(labels[labels > 0])), 2)

    def test_duplicate_large_facet_is_not_multiple_rocks(self):
        parent = np.zeros((100, 100), bool)
        parent[10:50, 10:50] = True
        child = np.zeros_like(parent)
        child[10:50, 10:34] = True
        self.assertEqual(np.count_nonzero(self.resolve([parent, child, child])), 1600)

    def test_minimum_applies_to_metric_and_perspective(self):
        labels = np.zeros((100, 100), np.int32)
        labels[35:45, 10:90] = 1
        edge = np.zeros_like(labels, bool)
        self.assertEqual(g.measure(labels, 1, 15, edge, "minor", min_size=30), [])
        self.assertEqual(len(g.measure(labels, 1, 15, edge, "ecd", min_size=30)), 1)
        self.assertEqual(g.measure(labels, 1, 15, edge, "ecd", persp=.2, pole_y=0, min_size=30), [])


class CliAndExportTests(unittest.TestCase):
    def test_invalid_options_fail_before_analysis(self):
        cases = [["--scale", "0"], ["--scale", "nan"], ["--work-width", "0"],
                 ["--breaker", "100", "--bypass", "400"], ["--persp", "inf"],
                 ["--roi", "0,0,0,1"], ["--roi", "0.5,0,0.8,1"],
                 ["--pole-px", "1,1,1,1"], ["--conf", "2"],
                 ["--scale", "1", "--pole-px", "0,0,1,1"]]
        for flags in cases:
            with self.subTest(flags=flags), patch.object(g, "analyse") as analyse:
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as err:
                    g.main(["missing.jpg"] + flags)
                self.assertEqual(err.exception.code, 2)
                analyse.assert_not_called()

    def test_colliding_stems_fail_before_analysis(self):
        for paths in (["a/image.jpg", "b/image.png"], ["combined.jpg", "other.jpg"]):
            with patch.object(g, "analyse") as analyse:
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    g.main(list(paths) + ["--out", "output", "--combine"])
                analyse.assert_not_called()

    def test_real_export_strict_json_unique_ids_and_no_overwrite(self):
        r, fs = report([100] * 10)
        r["mm_per_px"] = r["delineated_pct"] = None
        with tempfile.TemporaryDirectory() as folder:
            stem = str(Path(folder) / "combined")
            with contextlib.redirect_stdout(io.StringIO()):
                g.save_outputs(r, fs, None, stem, options())
            data = json.loads(Path(stem + "_result.json").read_text(encoding="utf-8"),
                              parse_constant=lambda x: self.fail("Invalid JSON constant " + x))
            self.assertIsNone(data["mm_per_px"])
            self.assertIsNone(data["rosin_rammler"]["xc_mm"])
            with open(stem + "_fragments.csv", encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len({r["id"] for r in rows}), 10)
            self.assertEqual({r["source_image"] for r in rows}, {"photo-0.jpg", "photo-1.jpg"})
            self.assertTrue(Path(stem + "_curve.png").stat().st_size > 0)
            with self.assertRaises(FileExistsError):
                g.save_outputs(r, fs, None, stem, options())

    def test_encoding_failure_publishes_no_partial_report(self):
        r, fs = report([100] * 10)
        a = dict(bgr=np.zeros((100, 100, 3), np.uint8), labels=np.zeros((100, 100), np.int32),
                 roi=np.ones((100, 100), np.uint8), scale=g.ScaleResult(1., "test"))
        a["labels"][0, 0] = 10
        with tempfile.TemporaryDirectory() as folder, patch.object(g.cv2, "imencode", return_value=(False, None)):
            with self.assertRaises(OSError):
                g.save_outputs(r, fs, a, str(Path(folder) / "test"), options())
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_permission_failure_publishes_no_partial_report(self):
        r, fs = report([100] * 10)
        a = dict(bgr=np.zeros((100, 100, 3), np.uint8), labels=np.full((100, 100), 10, np.int32),
                 roi=np.ones((100, 100), np.uint8), scale=g.ScaleResult(1., "test"))
        with tempfile.TemporaryDirectory() as folder, patch.object(Path, "write_bytes", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                g.save_outputs(r, fs, a, str(Path(folder) / "test"), options())
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_combined_main_keeps_sources_and_null_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            inputs = [root / "one.png", root / "two.png"]
            for p in inputs:
                p.touch()
            def analyse(path, args):
                fs = fragments([40, 60, 100, 200, 320, 360, 380, 400, 600, 800])
                for f in fs:
                    f.source_image = str(path)
                return fs, None, dict(name=path.name, mmpp=1., method="test", coverage=80.,
                                      sources=[dict(path=str(path))])
            with patch.object(g, "analyse", side_effect=analyse), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(g.main([str(p) for p in inputs] + ["--combine", "--out", str(root / "out")]), 0)
            data = json.loads((root / "out/combined_result.json").read_text(encoding="utf-8"))
            self.assertIsNone(data["mm_per_px"])
            self.assertIsNone(data["delineated_pct"])
            self.assertEqual(data["fragments"], 20)
            self.assertEqual(len(data["sources"]), 2)

    def test_existing_output_rejected_before_model_load(self):
        with tempfile.TemporaryDirectory() as folder:
            photo = Path(folder) / "photo.png"
            photo.touch()
            (Path(folder) / "photo_result.json").write_text("old result", encoding="utf-8")
            with patch.object(g, "analyse") as analyse:
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    g.main([str(photo)])
                analyse.assert_not_called()


if __name__ == "__main__":
    unittest.main()
