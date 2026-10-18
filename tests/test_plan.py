"""Terrain from Plan without 3ds Max: read the example site plan.
    python -m unittest discover -s tests

The PDF is Pesi's generated example (no client data) from the IngeTrazo
Topology repo; set PESI3D_PLAN_PDF to use another one.
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Contents" / "python"))

PDF = os.environ.get("PESI3D_PLAN_PDF", r"D:\PROJEKTE\INGETRAZO\ingetrazo-topology"
                     r"\examples\site_plan_spot_heights_1-200_A3.pdf")


@unittest.skipUnless(os.path.isfile(PDF), "example plan not found: " + PDF)
class PlanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from pesi3d_max.plugins.topology import plan, survey_pdf
        cls.plan = plan
        cls.d = survey_pdf.read_pdf(PDF, 0)

    def test_read(self):
        d = self.d
        self.assertGreaterEqual(len(d["recs"]), 3)
        self.assertEqual(d["scale"], 200)
        self.assertGreater(sum(1 for r in d["recs"] if r["symbol"]), len(d["recs"]) // 2)

    def test_records_in_metres(self):
        recs = self.plan.survey_from_pdf(self.d["recs"], 200)
        used = [r for r in recs if r["use"]]
        self.assertGreaterEqual(len(used), 3)
        ex = max(r["e"] for r in used) - min(r["e"] for r in used)
        # an A3 sheet at 1:200 covers at most 84 x 59 m
        self.assertLess(ex, 90.0)
        self.assertGreater(ex, 5.0)
        pts, (e0, n0, h0) = self.plan.survey_to_local(recs)
        self.assertEqual(len(pts), len(used))
        self.assertAlmostEqual(min(p[2] for p in pts), 0.0)
        self.assertAlmostEqual(min(p[0] for p in pts), 0.0)

    def test_rescale(self):
        recs = self.plan.survey_from_pdf(self.d["recs"], 200)
        e = recs[0]["e"]
        self.plan.survey_rescale(recs, 100)
        self.assertAlmostEqual(recs[0]["e"], e / 2)


if __name__ == "__main__":
    unittest.main()
