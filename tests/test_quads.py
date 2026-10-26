"""Topology quads without 3ds Max: clean grid quads for points and contours.
    python -m unittest discover -s tests
"""

import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Contents" / "python"))

import numpy as np  # noqa: E402

from pesi3d_max.plugins.topology import terrain as T  # noqa: E402


def params(**kw):
    p = T.normalize_params(dict({"quads": True, "cells": 20, "skirt": False}, **kw))
    return p


def polys_of(res, p):
    A = T.assemble(res, p)
    return A, T.cells_to_polys(res["T"], res["C"])


class PointsQuadsTest(unittest.TestCase):
    def plane_points(self, angle_deg=0.0, n=200, seed=1):
        rng = np.random.default_rng(seed)
        uv = rng.uniform([0, 0], [60, 30], size=(n, 2))
        uv = np.vstack([uv, [[0, 0], [60, 0], [60, 30], [0, 30]]])   # a rectangle
        a = math.radians(angle_deg)
        x = uv[:, 0] * math.cos(a) - uv[:, 1] * math.sin(a)
        y = uv[:, 0] * math.sin(a) + uv[:, 1] * math.cos(a)
        z = 100 + 0.1 * x + 0.05 * y                     # a tilted plane
        return list(map(tuple, np.column_stack([x, y, z])))

    def test_all_quads_on_plane(self):
        p = params(grid_angle="axis")
        res = T.compute({"mode": "points", "points": self.plane_points()}, p)
        A, polys = polys_of(res, p)
        self.assertEqual(A["unit"], "quads")
        self.assertTrue(polys)
        self.assertTrue(all(len(q) == 4 for q in polys))
        self.assertEqual(A["nfaces"], len(polys))
        V = res["V"]
        np.testing.assert_allclose(V[:, 2], 100 + 0.1 * V[:, 0] + 0.05 * V[:, 1], atol=1e-6)

    def test_row_by_row_numbering(self):
        p = params(grid_angle="axis")
        res = T.compute({"mode": "points", "points": self.plane_points()}, p)
        V = res["V"]
        h = float(np.min(np.diff(np.unique(np.round(V[:, 0], 6)))))
        rows = np.round((V[:, 1] - V[:, 1].min()) / h).astype(int)
        cols = np.round((V[:, 0] - V[:, 0].min()) / h).astype(int)
        order = np.lexsort((cols, rows))                 # rows S→N, then W→E
        self.assertTrue(np.array_equal(order, np.arange(len(V))))
        # assemble keeps that order for the mesh vertices
        A = T.assemble(res, p)
        np.testing.assert_allclose(np.asarray(A["verts"])[:len(V)], V)

    def test_grid_turns_along_the_site(self):
        pts = self.plane_points(angle_deg=30)
        self.assertAlmostEqual(math.degrees(T.min_rect_angle(np.asarray(pts)[:, :2])), 30, 3)
        p = params()                                      # grid_angle auto
        res = T.compute({"mode": "points", "points": pts}, p)
        _A, polys = polys_of(res, p)
        self.assertTrue(all(len(q) == 4 for q in polys))
        # turned grid: almost the whole 60 x 30 site is covered with cells
        h = 60 / 20
        self.assertGreater(len(polys), 0.8 * (60 / h) * (30 / h))

    def test_skirt_and_quad_bottom(self):
        p = params(grid_angle="axis", skirt=True, bottom=True)
        res = T.compute({"mode": "points", "points": self.plane_points()}, p)
        A = T.assemble(res, p)
        ncell = len(T.cells_to_polys(res["T"], res["C"]))
        self.assertEqual(A["bottoms"], [])               # no big n-gon
        nskirt = sum(1 for k in T.build_polygons(res["V"], res["T"], p)[1] if k == "skirt")
        # every face = two triangles: terrain cells + skirt quads + bottom cells
        self.assertEqual(len(A["tris"]), 2 * (2 * ncell + nskirt))
        nv = len(res["V"])
        self.assertEqual(len(A["verts"]), 2 * nv)        # one base vertex each
        base = np.asarray(A["verts"][nv:])
        np.testing.assert_allclose(base[:, :2], res["V"][:, :2])   # same order
        self.assertTrue(np.allclose(base[:, 2], A["base"]))


class ContoursQuadsTest(unittest.TestCase):
    def cone_segs(self):
        segs = []
        for k, r in enumerate((50.0, 35.0, 20.0, 8.0)):
            n = 48
            for i in range(n):
                a0, a1 = 2 * math.pi * i / n, 2 * math.pi * (i + 1) / n
                segs.append((r * math.cos(a0), r * math.sin(a0), 5.0 * k,
                             r * math.cos(a1), r * math.sin(a1), 5.0 * k))
        return segs

    def test_whole_cells_only_quads(self):
        p = params(peaks="flat")
        V, Tr, C = T.terrain_from_contours(self.cone_segs(), p)
        polys = T.cells_to_polys(Tr, C)
        self.assertTrue(all(len(q) == 4 for q in polys))
        order = np.lexsort((np.round(V[:, 0], 6), np.round(V[:, 1], 6)))
        self.assertTrue(np.array_equal(order, np.arange(len(V))))

    def test_cut_to_outline_keeps_rim_polygons(self):
        p = params(peaks="flat", quad_rim="cut")
        V, Tr, C = T.terrain_from_contours(self.cone_segs(), p)
        polys = T.cells_to_polys(Tr, C)
        self.assertTrue(any(len(q) != 4 for q in polys))


if __name__ == "__main__":
    unittest.main()
