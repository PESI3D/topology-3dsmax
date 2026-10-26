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


def check_snapped(test, res, outline_xy):
    """All quads, none folded, the rim on the outline, its corners hit."""
    V, polys = res["V"], T.cells_to_polys(res["T"], res["C"])
    test.assertTrue(all(len(q) == 4 for q in polys))
    areas = [T.polygon_area(V[q, :2]) for q in polys]
    test.assertGreater(min(areas), 0.0)                       # CCW, not folded
    o = T.Outline(outline_xy)
    rim, _loops = T.rim_loops(res["T"])
    rim_ids = np.unique(rim.ravel())
    d = o.distance(V[rim_ids, :2])
    test.assertLess(float(d.max()), 1e-6 * o.length)          # rim on the outline
    for corner in o.P[np.isin(o.cum[:-1], o.corners())]:
        test.assertLess(float(np.hypot(*(V[rim_ids, :2] - corner).T).min()),
                        1e-6 * o.length)                       # corners hit
    return polys, areas


class SnappedRimTest(unittest.TestCase):
    def test_points_rectangle_turned(self):
        rng = np.random.default_rng(3)
        uv = np.vstack([rng.uniform([0, 0], [60, 30], (300, 2)),
                        [[0, 0], [60, 0], [60, 30], [0, 30]]])
        a = math.radians(20)
        xy = np.column_stack([uv[:, 0] * math.cos(a) - uv[:, 1] * math.sin(a),
                              uv[:, 0] * math.sin(a) + uv[:, 1] * math.cos(a)])
        pts = np.column_stack([xy, 50 + 0.1 * xy[:, 0]])
        p = params(quad_rim="snap")
        res = T.compute({"mode": "points", "points": list(map(tuple, pts))}, p)
        corners = xy[-4:]
        polys, areas = check_snapped(self, res, corners)
        # covers the whole site now (no stepped rim)
        self.assertAlmostEqual(sum(areas), 60 * 30, delta=1e-6 * 1800)
        np.testing.assert_allclose(res["V"][:, 2], 50 + 0.1 * res["V"][:, 0], atol=1e-6)

    def test_points_irregular_outline(self):
        rng = np.random.default_rng(7)
        ang = rng.uniform(0, 2 * math.pi, 400)
        rad = 30 * np.sqrt(rng.uniform(0, 1, 400))
        xy = np.column_stack([rad * np.cos(ang) * 1.6, rad * np.sin(ang)])
        pts = np.column_stack([xy, 0.02 * (xy ** 2).sum(1)])
        p = params(quad_rim="snap", cells=25)
        res = T.compute({"mode": "points", "points": list(map(tuple, pts))}, p)
        hull = T.convex_hull(np.round(xy, 9))
        check_snapped(self, res, hull)

    def test_contours_hull(self):
        p = params(peaks="flat", quad_rim="snap")
        segs = ContoursQuadsTest.cone_segs(None)
        V, Tr, C = T.terrain_from_contours(segs, p)
        S = np.asarray(segs)
        hull = T.convex_hull(np.round(np.concatenate([S[:, 0:2], S[:, 3:5]]), 9))
        check_snapped(self, {"V": V, "T": Tr, "C": C}, hull)

    def test_relaxed_rim_has_no_sharp_quads(self):
        def min_angle(V, polys):
            m = 180.0
            for q in polys:
                P = V[q, :2]
                for i in range(4):
                    u, v = P[i - 1] - P[i], P[(i + 1) % 4] - P[i]
                    m = min(m, math.degrees(math.acos(np.clip(
                        u @ v / (np.linalg.norm(u) * np.linalg.norm(v)), -1, 1))))
            return m
        segs = ContoursQuadsTest.cone_segs(None)
        S = np.asarray(segs)
        hull = T.convex_hull(np.round(np.concatenate([S[:, 0:2], S[:, 3:5]]), 9))
        angles = {}
        for relax in (False, True):
            p = params(peaks="flat", quad_rim="snap", rim_relax=relax)
            V, Tr, C = T.terrain_from_contours(segs, p)
            polys, _a = check_snapped(self, {"V": V, "T": Tr, "C": C}, hull)
            angles[relax] = min_angle(V, polys)
        self.assertLess(angles[False], 30.0)
        self.assertGreater(angles[True], 45.0)

    def test_snapped_solid_is_closed(self):
        p = params(peaks="flat", quad_rim="snap", skirt=True, bottom=True)
        segs = ContoursQuadsTest.cone_segs(None)
        res = T.compute({"mode": "contours",
                         "cset": T.ContourSet.from_segs(segs)}, p)
        A = T.assemble(res, p)
        tris = np.asarray(A["tris"])
        e = np.sort(np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]]), 1)
        _u, cnt = np.unique(e, axis=0, return_counts=True)
        self.assertTrue((cnt == 2).all())                     # watertight
        self.assertEqual(A["bottoms"], [])


class SkirtShadingTest(unittest.TestCase):
    def test_sharp_skirt_corners(self):
        rng = np.random.default_rng(5)
        xy = np.vstack([rng.uniform([0, 0], [40, 20], (150, 2)),
                        [[0, 0], [40, 0], [40, 20], [0, 20]]])
        pts = list(map(tuple, np.column_stack([xy, 10 + 0.05 * xy[:, 0]])))
        p = params(grid_angle="axis", quad_rim="snap", skirt=True, bottom=True)
        res = T.compute({"mode": "points", "points": pts}, p)
        polys, kinds, _e = T.build_polygons(res["V"], res["T"], p)
        rings = [r for r, k in zip(polys, kinds) if k == "skirt"]
        groups = T.skirt_groups(rings)
        side = {}
        for r, g in zip(rings, groups):
            (bx, by, _), (ax, ay, _) = r[0], r[1]
            d = (round(np.sign(bx - ax)), round(np.sign(by - ay)))
            side.setdefault(d, set()).add(g)
        self.assertEqual(len(side), 4)                        # four sides
        self.assertTrue(all(len(g) == 1 for g in side.values()))   # one group each
        g = {k: next(iter(v)) for k, v in side.items()}
        order = [(1, 0), (0, 1), (-1, 0), (0, -1)]            # E, N, W, S runs
        for a, b in zip(order, order[1:] + order[:1]):
            self.assertNotEqual(g[a], g[b])                   # corners sharp
        self.assertFalse({1, 4} & set(groups))                # not terrain/bottom
        A = T.assemble(res, p)
        self.assertEqual(sorted(set(A["sg"])), sorted({1, 4} | set(groups)))


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
