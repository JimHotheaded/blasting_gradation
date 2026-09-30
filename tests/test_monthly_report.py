"""Regression tests for monthly_report.py (audit 2026-09-30 findings 2-5)."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import monthly_report as mr

SIZES = [10, 25, 50, 75, 100, 150, 200, 250, 300, 400, 500, 600, 700, 800, 900, 1000, 1200]


def passing(p100, p400):
    """Monotone passing curve through the given values at 100 and 400 mm."""
    out = []
    for s in SIZES:
        if s <= 100:
            v = p100 * s / 100
        elif s <= 400:
            v = p100 + (p400 - p100) * (s - 100) / 300
        else:
            v = p400 + (100 - p400) * min(1, (s - 400) / 600)
        out.append(dict(size_mm=s, measured=v, rr_fit=v, report=round(v, 2)))
    return out


def result(p100=20, p400=80, **over):
    R = dict(passing=passing(p100, p400), mm_per_px=3.0, fragments=300, delineated_pct=70.0,
             d_values=dict(D10=40, D50=180, D80=380), top_size_mm=700, Cu=4.0, oversize_blocks=2,
             scale_method="auto pole, 2 red segment(s) + pitch", fines_correction="rr",
             weighting="area", depth_model=None, perspective=1.0,
             rosin_rammler=dict(xc_mm=250.0, n=1.5, status="fitted"),
             settings=dict(roi=[0, 0.2, 1, 0.8], metric="minor", fit_min=100, pole_length=2000))
    for k, v in over.items():
        if k in ("metric", "fit_min"):
            R["settings"][k] = v
        else:
            R[k] = v
    R["split"] = mr.conditional_split(R["passing"])
    return R


def build(specs, lang="en"):
    """specs: list of (conf, R). Returns (page, days, stats)."""
    raw, notes = {}, {"days": {}, "highlights": {"en": [], "th": []}}
    for i, (conf, R) in enumerate(specs):
        day = f"2026-10-{i + 1:02d}"
        raw[day] = (R, "")
        notes["days"][day] = {"conf": conf, "notes": {"en": ["n"], "th": ["n"]}}
    return mr.build(lang, "2026-10", Path("."), notes, raw, "2026-10-31")


def curves(page):
    return json.loads(page.split("const CURVES = ")[1].split(";\n", 1)[0])


class SplitTests(unittest.TestCase):
    def test_all_fines_day_has_no_conditional_shares(self):
        split = mr.conditional_split(passing(100, 100))
        self.assertEqual(split["bypass"], 100)
        self.assertIsNone(split["crusher"])
        self.assertIsNone(split["breaker"])

    def test_ordinary_day_shares_sum_to_100(self):
        split = mr.conditional_split(passing(25, 75))
        self.assertAlmostEqual(split["crusher"] + split["breaker"], 100, places=1)

    def test_all_fines_day_is_unavailable_and_excluded_from_monthly_stats(self):
        page, days, st = build([("good", result(20, 80)), ("good", result(30, 90)),
                                ("good", result(100, 100))])
        self.assertEqual(st["m"], 2)            # breaker statistics: two days with rock
        self.assertEqual(st["mf"], 3)           # fines statistics: all three days
        self.assertEqual(st["bmin"], min(d["R"]["split"]["breaker"] for d in days[:2]))
        self.assertIn(">n/a<", page)            # shown, not reported as 0%


class EligibilityTests(unittest.TestCase):
    def test_provisional_day_does_not_shape_monthly_curve(self):
        specs = [("good", result(20 + i, 80 + i)) for i in range(7)] + [("provisional", result(95, 99))]
        page, days, st = build(specs)
        data = curves(page)
        median = next(s for s in data["series"] if s["var"] == "accent")["values"]
        k100 = SIZES.index(100)
        self.assertAlmostEqual(median[k100], 23.0, places=2)   # 20..26 only, not 95
        maxima = next(s for s in data["series"] if s["name"] == "max")["values"]
        self.assertLess(maxima[k100], 95)
        # provisional day still drawn individually, dashed
        self.assertEqual(page.count('stroke-dasharray="6 4"'), 1)


class MethodTextTests(unittest.TestCase):
    def test_default_settings_read_as_before(self):
        page, _, _ = build([("good", result()), ("good", result())])
        self.assertIn("sized by the short axis", page)
        self.assertIn("weighted by visible area", page)
        self.assertIn("none of these photos had a perspective calibration", page)
        self.assertIn("A long flat slab", page)

    def test_method_follows_what_each_day_recorded(self):
        page, _, _ = build([("good", result()),
                            ("good", result(metric="ecd", weighting="volume",
                                            depth_model={"kind": "inverse-row"},
                                            fines_correction="none"))])
        self.assertIn("differed between days", page)
        self.assertIn("weighted differently between days", page)
        self.assertIn("perspective correction was applied on 2 October only", page)
        self.assertIn("Rosin-Rammler fit was unavailable", page)
        self.assertNotIn("A long flat slab", page)          # not every day used the short axis
        self.assertNotIn("none of these photos had a perspective calibration", page)

    def test_thai_method_follows_metadata_too(self):
        page, _, _ = build([("good", result()), ("good", result(metric="mean"))], lang="th")
        self.assertIn("ต่างกันในแต่ละวัน", page)


class PdfExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pdf = Path(self.tmp.name) / "r.pdf"
        self.pdf.write_bytes(b"%PDF-old" + b"x" * 2000 + b"%%EOF")
        self.old = self.pdf.read_bytes()
        self.edge = patch.object(mr, "EDGE_PATHS", [sys.executable])
        self.edge.start()

    def tearDown(self):
        self.edge.stop()
        self.tmp.cleanup()

    def run_with(self, returncode, content):
        def fake(cmd, **kw):
            target = Path(next(a for a in cmd if a.startswith("--print-to-pdf=")).split("=", 1)[1])
            if content is not None:
                target.write_bytes(content)
            return subprocess.CompletedProcess(cmd, returncode)
        with patch.object(mr.subprocess, "run", side_effect=fake):
            return mr.print_pdf('<html lang="en"><body></body></html>', "en", self.pdf)

    def test_edge_failure_is_reported_and_old_pdf_kept(self):
        why = self.run_with(1, b"%PDF-new" + b"y" * 2000 + b"%%EOF")
        self.assertIn("code 1", why)
        self.assertEqual(self.pdf.read_bytes(), self.old)

    def test_success_code_without_output_is_a_failure(self):
        why = self.run_with(0, None)
        self.assertIsNotNone(why)
        self.assertEqual(self.pdf.read_bytes(), self.old)

    def test_truncated_pdf_is_rejected(self):
        why = self.run_with(0, b"%PDF-new" + b"y" * 3000)    # no %%EOF
        self.assertIn("not a complete PDF", why)
        self.assertEqual(self.pdf.read_bytes(), self.old)

    def test_valid_new_pdf_replaces_old(self):
        new = b"%PDF-new" + b"y" * 3000 + b"%%EOF\n"
        self.assertIsNone(self.run_with(0, new))
        self.assertEqual(self.pdf.read_bytes(), new)
        self.assertEqual(list(Path(self.tmp.name).glob(".pdf-*")), [])   # staging cleaned


if __name__ == "__main__":
    unittest.main()
