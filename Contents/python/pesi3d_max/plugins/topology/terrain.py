# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pesi (pesi3d.de)
"""PESI3D Topology for 3ds Max — terrain from contour lines or from points.

* **Terrain from Contours** — select contour splines that lie at their
  altitudes. A regular grid is laid over them, every grid node gets its
  height by harmonic interpolation between the contours (no terraces),
  optional rounded summits & pits and a smoothing radius; clean-up of
  messy lines (simplify, smooth, ignore short lines).
* **Terrain from Points** — select Point helpers, mesh/poly objects
  (their vertices) or splines (their knots). A Delaunay TIN goes exactly
  through every point; long rim triangles can be trimmed.
* **Terrain from Plan** (1.1) - the spot heights of a site plan (vector
  PDF), see plan.py; they become a Terrain from Points.

Both: footprint (outline / rectangle interpolated / rectangle cut),
optional skirt with closed bottom, the contours and a flat contour map as
child splines, smooth shading, quads (contours). The result is ONE
Editable Poly that remembers its source and settings — select it and run
**Edit Terrain…**. Every run is one undo step; Live Preview while the
dialog stays open.

Port of the IngeTrazo plugin "Topology" 1.1 (same terrain code).
Needs numpy (scipy optional) in the 3ds Max Python.

Part of PESI3D Tools since 0.2 (pesi3d_max.plugins.topology); menu, MacroScripts
and the PESI3D toolbar come from the framework, see __init__.py.
"""
from __future__ import annotations

import json
import math
import os
import site
import sys
import time

try:                                    # numpy installed with pip --user
    _us = site.getusersitepackages()
    if _us not in sys.path:
        sys.path.append(_us)
except Exception:  # noqa: BLE001
    pass

KEY = "pesi_topology"
TITLE = "Topology"
VERSION = "1.1"
APPDATA_ID = 0x50D3A2               # node AppData slot (Grading uses …A1)
CHILD_ID = 0x50D3A3                 # AppData tag on the child splines
SETTINGS_ORG = "PESI3D"
SETTINGS_APP = "Topology3dsMax"
MAX_CELLS_SIDE = 2000
MIN_CELLS_SIDE = 10
MAX_TRIANGLES = 1_000_000
WARN_TRIANGLES = 300_000
EPS = 1e-9
# params entered in metres (converted to system units for the solver)
METRE_KEYS = ("cell_size", "simplify", "min_len", "max_edge", "smooth_r",
              "skirt_depth")


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

def default_params() -> dict:
    return {
        "res_mode": "cells",      # "cells" | "size"
        "cells": 150,             # cells on the long side
        "cell_size": 1.0,         # metres
        "boundary": "hull",       # "hull" | "box" (interpolated) | "cut"
        "peaks": "round",         # "flat" | "round" (summits & pits)
        "simplify": 0.0,          # metres, 0 = off   (contour clean-up)
        "smooth": 0,              # passes, 0 = off
        "min_len": 0.0,           # metres, 0 = off
        "max_edge": 0.0,          # metres, 0 = off  (points)
        "soft": True,
        "quads": False,           # one quad per grid cell (points: a grid
                                  # is laid over the TIN)
        "quad_rim": "whole",      # quads: "whole" cells only (stepped rim)
                                  # | "snap" (+ a ring of quads out to the
                                  # outline) | "cut" (contours: n-gons)
        "rim_relax": True,        # quads + "snap": even out the rim quads
        "grid_angle": "auto",     # points + quads: "auto" (along the site)
                                  # | "axis" (world X/Y)
        "smooth_r": 0.0,          # contours: smoothing radius, 0 = raw
        "skirt": True,
        "skirt_depth": 1.0,       # metres below the lowest point
        "bottom": True,
        "contours": False,        # include the contours (child spline)
        "map": False,             # include a flat contour map (child spline)
        "follow": False,          # dialog: re-read the selection
    }


def normalize_params(p) -> dict:
    out = default_params()
    if isinstance(p, dict):
        for k, v in p.items():
            if k in out and (type(v) is type(out[k]) or
                             (isinstance(out[k], float) and
                              isinstance(v, (int, float)))):
                out[k] = type(out[k])(v)
    out["force"] = bool(p.get("force", False)) if isinstance(p, dict) else False
    out["smooth"] = max(0, min(10, int(out["smooth"])))
    out["simplify"] = max(0.0, float(out["simplify"]))
    out["smooth_r"] = max(0.0, float(out["smooth_r"]))
    out["min_len"] = max(0.0, float(out["min_len"]))
    out["cells"] = max(MIN_CELLS_SIDE, min(MAX_CELLS_SIDE, int(out["cells"])))
    out["cell_size"] = max(1e-4, float(out["cell_size"]))
    out["skirt_depth"] = max(0.0, float(out["skirt_depth"]))
    out["max_edge"] = max(0.0, float(out["max_edge"]))
    if out["res_mode"] not in ("cells", "size"):
        out["res_mode"] = "cells"
    if out["peaks"] not in ("flat", "round"):
        out["peaks"] = "round"
    if out["boundary"] not in ("hull", "box", "cut"):
        out["boundary"] = "hull"
    if out["quad_rim"] not in ("whole", "snap", "cut"):
        out["quad_rim"] = "whole"
    if out["grid_angle"] not in ("auto", "axis"):
        out["grid_angle"] = "auto"
    return out


def _qsettings():
    from PySide6.QtCore import QSettings
    return QSettings(SETTINGS_ORG, SETTINGS_APP)


def load_params() -> dict:
    try:
        raw = _qsettings().value("params", "")
        if raw:
            return normalize_params(json.loads(raw))
    except Exception:  # noqa: BLE001
        pass
    return default_params()


def save_params(p: dict) -> None:
    try:
        p = {k: v for k, v in p.items() if k != "force"}
        _qsettings().setValue("params", json.dumps(p))
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Units: the terrain code works in system units; lengths are entered in m
# ---------------------------------------------------------------------------

def _rt():
    from pymxs import runtime as rt
    return rt


def units_per_metre() -> float:
    try:
        return float(_rt().units.decodeValue("1m"))
    except Exception:  # noqa: BLE001
        return 1.0


def fmt_len(v_sys: float, dec=2) -> str:
    return f"{v_sys / units_per_metre():,.{dec}f} m"


def solver_params(p: dict) -> dict:
    q = dict(normalize_params(p))
    f = units_per_metre()
    for k in METRE_KEYS:
        q[k] = q[k] * f
    return q


# ---------------------------------------------------------------------------
# Source data from the 3ds Max selection
# ---------------------------------------------------------------------------

def _p3(p) -> tuple:
    return (float(p.x), float(p.y), float(p.z))


def terrain_record(node):
    rt = _rt()
    try:
        raw = rt.getAppData(node, APPDATA_ID)
    except Exception:  # noqa: BLE001
        return None
    if not raw:
        return None
    try:
        rec = json.loads(raw)
    except ValueError:
        return None
    return rec if isinstance(rec, dict) and "mode" in rec else None


def is_terrain(node) -> bool:
    return terrain_record(node) is not None


def _is_child(node) -> bool:
    try:
        return bool(_rt().getAppData(node, CHILD_ID))
    except Exception:  # noqa: BLE001
        return False


_MXS_SRC = r"""
fn pesiTopoShapeSegs shp steps = (
    -- world-space segments of every spline: x0 y0 z0 x1 y1 z1 …
    local out = #()
    local tmp = undefined
    local s = shp
    if classOf shp != SplineShape and classOf shp != line do (
        tmp = copy shp
        convertToSplineShape tmp
        s = tmp
    )
    for sp = 1 to numSplines s do (
        for g = 1 to numSegments s sp do (
            local a = interpBezier3D s sp g 0.0
            local b = interpBezier3D s sp g 1.0
            local straight = (getSegmentType s sp g) == #line
            if not straight do (
                -- a curve segment whose handles lie on the chord is straight
                local m = interpBezier3D s sp g 0.5
                local d = b - a
                local L2 = dot d d
                if L2 > 0 do (
                    local t = (dot (m - a) d) / L2
                    local q = a + t * d
                    straight = (distance m q) < (1e-4 * (sqrt L2))
                )
            )
            local n = if straight then 1 else steps
            local p0 = a
            for k = 1 to n do (
                local p1 = if k == n then b else (interpBezier3D s sp g (k as float / n))
                join out #(p0.x, p0.y, p0.z, p1.x, p1.y, p1.z)
                p0 = p1
            )
        )
    )
    if tmp != undefined do delete tmp
    out
)
fn pesiTopoMeshVerts obj path = (
    -- world vertices to a binary file (no big arrays through pymxs)
    local m = snapshotAsMesh obj
    local f = fopen path "wb"
    WriteLong f m.numverts #unsigned
    for i = 1 to m.numverts do (
        local p = getVert m i
        WriteFloat f p.x; WriteFloat f p.y; WriteFloat f p.z
    )
    fclose f
    delete m
    ok
)
fn pesiTopoKnots shp = (
    local out = #()
    local tmp = undefined
    local s = shp
    if classOf shp != SplineShape and classOf shp != line do (
        tmp = copy shp
        convertToSplineShape tmp
        s = tmp
    )
    for sp = 1 to numSplines s do
        for k = 1 to numKnots s sp do (
            local p = getKnotPoint s sp k
            join out #(p.x, p.y, p.z)
        )
    if tmp != undefined do delete tmp
    out
)
"""
_MXS_READY = False


def _ensure_mxs():
    global _MXS_READY
    if not _MXS_READY:
        _rt().execute(_MXS_SRC + _MXS_BUILD)
        _MXS_READY = True


def _triples(flat, n):
    return [tuple(float(v) for v in flat[i:i + n])
            for i in range(0, len(flat), n)]


def gather_contours(nodes=None):
    """Contour segments from the selected shapes (a terrain or its child
    splines are skipped)."""
    _ensure_mxs()
    rt = _rt()
    if nodes is None:
        nodes = list(rt.selection)
    segs, names = [], []
    for n in nodes:
        if rt.isDeleted(n) or is_terrain(n) or _is_child(n):
            continue
        if rt.superClassOf(n) == rt.shape:
            try:
                steps = max(4, int(n.steps) + 1)
            except Exception:  # noqa: BLE001
                steps = 6
            flat = list(rt.pesiTopoShapeSegs(n, steps))
            for s in _triples(flat, 6):
                if (s[0], s[1], s[2]) != (s[3], s[4], s[5]):
                    segs.append(s)
            names.append(str(n.name))
    return segs, names


def gather_points(nodes=None):
    """Points from Point helpers, mesh/poly vertices and spline knots."""
    _ensure_mxs()
    rt = _rt()
    if nodes is None:
        nodes = list(rt.selection)
    pts, kinds = [], {"helpers": 0, "vertices": 0, "knots": 0}
    for n in nodes:
        if rt.isDeleted(n) or is_terrain(n) or _is_child(n):
            continue
        sc = rt.superClassOf(n)
        if sc == rt.helper and rt.classOf(n) == rt.Point:
            pts.append(_p3(n.pos))
            kinds["helpers"] += 1
        elif sc == rt.shape:
            q = _triples(list(rt.pesiTopoKnots(n)), 3)
            pts += q
            kinds["knots"] += len(q)
        elif sc == rt.GeometryClass and rt.canConvertTo(n, rt.TriMeshGeometry):
            import numpy as np
            import tempfile
            path = os.path.join(tempfile.gettempdir(), "pesi_topology_pts.bin")
            rt.pesiTopoMeshVerts(n, path)
            with open(path, "rb") as fh:
                cnt = int(np.frombuffer(fh.read(4), "<u4")[0])
                arr = np.frombuffer(fh.read(cnt * 12), "<f4").reshape(-1, 3)
            q = [tuple(r) for r in arr.astype(float).tolist()]
            pts += q
            kinds["vertices"] += len(q)
    return dedupe_points(pts), kinds


class TopoError(Exception):
    """A user-facing refusal."""




def dedupe_points(pts, tol=1e-4):
    """One point per XY spot (within ``tol``); same spot, different heights
    → their mean."""
    acc: dict = {}
    for x, y, z in pts:
        k = (round(x / tol), round(y / tol))
        if k in acc:
            s = acc[k]
            s[2] += z
            s[3] += 1
        else:
            acc[k] = [x, y, z, 1]
    return [(s[0], s[1], s[2] / s[3]) for s in acc.values()]


def chain_segments(segs, tol=1e-6):
    """Join segments into polylines (lists of (x, y, z)); a closed loop
    repeats its first point at the end."""
    def key(x, y, z):
        return (round(x / tol), round(y / tol), round(z / tol))

    adj: dict = {}
    pos: dict = {}
    edges = []
    for i, s in enumerate(segs):
        ka, kb = key(*s[:3]), key(*s[3:])
        pos[ka] = tuple(s[:3])
        pos[kb] = tuple(s[3:])
        adj.setdefault(ka, []).append(i)
        adj.setdefault(kb, []).append(i)
        edges.append((ka, kb))
    used = [False] * len(segs)

    def walk(start_k, first_e):
        line = [start_k]
        k, e = start_k, first_e
        while e is not None:
            used[e] = True
            a, b = edges[e]
            k = b if a == k else a
            line.append(k)
            if len(adj[k]) != 2:
                break
            nxt = [j for j in adj[k] if not used[j]]
            e = nxt[0] if nxt else None
        return line

    lines = []
    # Open chains first (from ends / junctions), then the closed loops.
    for k, es in adj.items():
        if len(es) != 2:
            for e in es:
                if not used[e]:
                    lines.append(walk(k, e))
    for e in range(len(segs)):
        if not used[e]:
            lines.append(walk(edges[e][0], e))
    return [[pos[k] for k in ln] for ln in lines]


# ---------------------------------------------------------------------------
# Geometry helpers (numpy)
# ---------------------------------------------------------------------------

def convex_hull(xy):
    """Monotone chain; CCW, no repeated end point. ``xy``: (n, 2)."""
    pts = sorted(set(map(tuple, xy)))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _inside_convex(poly, X, Y, eps):
    """Vectorised point-in-convex-polygon (CCW) for arrays X, Y."""
    import numpy as np
    inside = np.ones(X.shape, dtype=bool)
    n = len(poly)
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        inside &= ((bx - ax) * (Y - ay) - (by - ay) * (X - ax)) >= -eps
    return inside


def _clip_convex(subject, clip):
    """Sutherland–Hodgman: polygon ``subject`` clipped by CCW convex
    ``clip``. Lists of (x, y)."""
    out = list(subject)
    n = len(clip)
    for i in range(n):
        if not out:
            break
        ax, ay = clip[i]
        bx, by = clip[(i + 1) % n]

        def side(p):
            return (bx - ax) * (p[1] - ay) - (by - ay) * (p[0] - ax)

        inp, out = out, []
        for j in range(len(inp)):
            p, q = inp[j], inp[(j + 1) % len(inp)]
            sp, sq = side(p), side(q)
            if sp >= 0:
                out.append(p)
            if (sp >= 0) != (sq >= 0):
                t = sp / (sp - sq)
                out.append((p[0] + (q[0] - p[0]) * t,
                            p[1] + (q[1] - p[1]) * t))
    return out


def _clip_halfplanes(subject, edges):
    """Like ``_clip_convex`` but only with the given clip edges
    ``[(ax, ay, bx, by), …]`` (the ones near the subject — for a convex
    clip polygon that gives the same result, much faster)."""
    out = list(subject)
    for ax, ay, bx, by in edges:
        if not out:
            break
        inp, out = out, []
        for j in range(len(inp)):
            p, q = inp[j], inp[(j + 1) % len(inp)]
            sp = (bx - ax) * (p[1] - ay) - (by - ay) * (p[0] - ax)
            sq = (bx - ax) * (q[1] - ay) - (by - ay) * (q[0] - ax)
            if sp >= 0:
                out.append(p)
            if (sp >= 0) != (sq >= 0):
                t = sp / (sp - sq)
                out.append((p[0] + (q[0] - p[0]) * t,
                            p[1] + (q[1] - p[1]) * t))
    return out


# ---------------------------------------------------------------------------
# Contours → height grid (harmonic interpolation, multigrid cascade)
# ---------------------------------------------------------------------------

def _rasterize(S, x0, y0, h, nx, ny):
    """Contour samples onto the nodes of a grid: ``(fixed mask, values)``."""
    import numpy as np
    A, B = S[:, :3], S[:, 3:]
    L = np.hypot(B[:, 0] - A[:, 0], B[:, 1] - A[:, 1])
    n = np.ceil(L / (h * 0.3)).astype(np.int64) + 1
    seg = np.repeat(np.arange(len(S)), n)
    start = np.cumsum(n) - n
    t = (np.arange(int(n.sum())) - start[seg]) / np.maximum(n - 1, 1)[seg]
    P = A[seg] + (B[seg] - A[seg]) * t[:, None]
    ix = np.rint((P[:, 0] - x0) / h).astype(np.int64)
    iy = np.rint((P[:, 1] - y0) / h).astype(np.int64)
    ok = (ix >= 0) & (ix <= nx) & (iy >= 0) & (iy <= ny)
    ix, iy, z = ix[ok], iy[ok], P[ok, 2]
    flat = iy * (nx + 1) + ix
    size = (ny + 1) * (nx + 1)
    s = np.bincount(flat, weights=z, minlength=size)
    c = np.bincount(flat, minlength=size)
    fixed = c > 0
    vals = np.zeros(size)
    vals[fixed] = s[fixed] / c[fixed]
    return fixed.reshape(ny + 1, nx + 1), vals.reshape(ny + 1, nx + 1)


def _relax(Z, fixed, iters, omega, tol):
    """Red–black SOR for Laplace's equation; Neumann on the grid border,
    the contour nodes held."""
    import numpy as np
    ny1, nx1 = Z.shape
    jj, ii = np.meshgrid(np.arange(nx1), np.arange(ny1))
    masks = [((ii + jj) % 2 == par) & ~fixed for par in (0, 1)]
    for _ in range(iters):
        change = 0.0
        for m in masks:
            P = np.pad(Z, 1, mode="edge")
            avg = (P[:-2, 1:-1] + P[2:, 1:-1] + P[1:-1, :-2] + P[1:-1, 2:]) * 0.25
            d = (avg - Z)[m]
            Z[m] += omega * d
            if d.size:
                change = max(change, float(np.abs(d).max()))
        if change < tol:
            break
    return Z


def _upsample(Zc, ny, nx, factor):
    """Bilinear: coarse grid (spacing ``factor``·h) → fine (ny+1, nx+1)."""
    import numpy as np
    cy, cx = Zc.shape
    u = np.minimum(np.arange(nx + 1) / factor, cx - 1)
    v = np.minimum(np.arange(ny + 1) / factor, cy - 1)
    j0 = np.minimum(np.floor(u).astype(int), cx - 2) if cx > 1 else np.zeros(nx + 1, int)
    i0 = np.minimum(np.floor(v).astype(int), cy - 2) if cy > 1 else np.zeros(ny + 1, int)
    fu = (u - j0)[None, :]
    fv = (v - i0)[:, None]
    j1 = np.minimum(j0 + 1, cx - 1)
    i1 = np.minimum(i0 + 1, cy - 1)
    z00 = Zc[np.ix_(i0, j0)]
    z01 = Zc[np.ix_(i0, j1)]
    z10 = Zc[np.ix_(i1, j0)]
    z11 = Zc[np.ix_(i1, j1)]
    return (z00 * (1 - fu) * (1 - fv) + z01 * fu * (1 - fv)
            + z10 * (1 - fu) * fv + z11 * fu * fv)


def solve_height_grid(S, x0, y0, h, nx, ny):
    """Height of every node of the (ny+1)×(nx+1) grid from contour segments
    ``S`` (m, 6)."""
    import numpy as np
    zr = float(S[:, [2, 5]].max() - S[:, [2, 5]].min()) or 1.0
    tol = zr * 1e-5
    levels = 0
    while max(nx, ny) / (2 ** (levels + 1)) >= 24:
        levels += 1
    Z = None
    for lev in range(levels, -1, -1):
        f = 2 ** lev
        cnx, cny = math.ceil(nx / f), math.ceil(ny / f)
        fixed, vals = _rasterize(S, x0, y0, h * f, cnx, cny)
        if Z is None:
            Z = np.full((cny + 1, cnx + 1), float(vals[fixed].mean()))
            iters = 4000
        else:
            Z = _upsample(Z, cny, cnx, 2)
            iters = 400
        Z[fixed] = vals[fixed]
        omega = 2.0 / (1.0 + math.sin(math.pi / max(cnx, cny, 2)))
        Z = _relax(Z, fixed, iters, min(omega, 1.97), tol)
    return Z, fixed


def _components(free):
    """4-connected components of the True cells of ``free`` → label array
    (-1 = not free) and the component count."""
    import numpy as np
    ny1, nx1 = free.shape
    lab = np.full(free.shape, -1, dtype=np.int64)
    fl = free.ravel()
    lb = lab.ravel()
    n = 0
    for start in np.flatnonzero(fl).tolist():
        if lb[start] >= 0:
            continue
        lb[start] = n
        stack = [start]
        while stack:
            k = stack.pop()
            r, c = divmod(k, nx1)
            if c > 0 and fl[k - 1] and lb[k - 1] < 0:
                lb[k - 1] = n
                stack.append(k - 1)
            if c < nx1 - 1 and fl[k + 1] and lb[k + 1] < 0:
                lb[k + 1] = n
                stack.append(k + 1)
            if r > 0 and fl[k - nx1] and lb[k - nx1] < 0:
                lb[k - nx1] = n
                stack.append(k - nx1)
            if r < ny1 - 1 and fl[k + nx1] and lb[k + nx1] < 0:
                lb[k + nx1] = n
                stack.append(k + nx1)
        n += 1
    return lab, n


def _chamfer(region, seed):
    """Distance (in cells, chamfer 1/√2) of every ``region`` cell from the
    ``seed`` cells — two raster passes."""
    import numpy as np
    INF = 1e18
    d = np.where(seed, 0.0, INF)
    ny1, nx1 = d.shape
    r2 = math.sqrt(2.0)
    D = d.tolist()
    R = (region | seed).tolist()
    for i in range(ny1):
        row, up = D[i], D[i - 1] if i else None
        for j in range(nx1):
            if not R[i][j]:
                continue
            v = row[j]
            if j and row[j - 1] + 1 < v:
                v = row[j - 1] + 1
            if up is not None:
                if up[j] + 1 < v:
                    v = up[j] + 1
                if j and up[j - 1] + r2 < v:
                    v = up[j - 1] + r2
                if j < nx1 - 1 and up[j + 1] + r2 < v:
                    v = up[j + 1] + r2
            row[j] = v
    for i in range(ny1 - 1, -1, -1):
        row, dn = D[i], D[i + 1] if i < ny1 - 1 else None
        for j in range(nx1 - 1, -1, -1):
            if not R[i][j]:
                continue
            v = row[j]
            if j < nx1 - 1 and row[j + 1] + 1 < v:
                v = row[j + 1] + 1
            if dn is not None:
                if dn[j] + 1 < v:
                    v = dn[j] + 1
                if j < nx1 - 1 and dn[j + 1] + r2 < v:
                    v = dn[j + 1] + r2
                if j and dn[j - 1] + r2 < v:
                    v = dn[j - 1] + r2
            row[j] = v
    return np.asarray(D)


def round_extrema(Z, fixed, h):
    """Summits and pits: the harmonic solution leaves the area inside the
    highest (lowest) closed contour flat. Each such area is lifted (lowered)
    into a dome that leaves the contour with the slope the terrain has just
    outside it and flattens out at the top:

        z = L ± s · (d − d² / 2D)

    d = distance from the contour, D = the largest d in the area, s = the
    mean slope in a ring just outside the contour. Areas open to the grid
    border are left as they are (no way to tell up from down there)."""
    import numpy as np
    ny1, nx1 = Z.shape
    lab, n = _components(~fixed)
    if n == 0:
        return Z
    gy, gx = np.gradient(Z, h)
    slope = np.hypot(gx, gy)
    Z = Z.copy()
    for k in range(n):
        reg = lab == k
        ys, xs = np.nonzero(reg)
        if (ys.min() == 0 or xs.min() == 0 or ys.max() == ny1 - 1
                or xs.max() == nx1 - 1):
            continue                                    # open to the border
        y0, y1 = max(ys.min() - 3, 0), min(ys.max() + 4, ny1)
        x0, x1 = max(xs.min() - 3, 0), min(xs.max() + 4, nx1)
        R = reg[y0:y1, x0:x1]
        F = fixed[y0:y1, x0:x1]
        P = np.pad(R, 1)
        near = (P[:-2, 1:-1] | P[2:, 1:-1] | P[1:-1, :-2] | P[1:-1, 2:]
                | P[:-2, :-2] | P[:-2, 2:] | P[2:, :-2] | P[2:, 2:])
        border = near & F & ~R                          # its contour nodes
        if not border.any():
            continue
        zb = Z[y0:y1, x0:x1][border]
        L = float(np.median(zb))
        if float(zb.max() - zb.min()) > 1e-6 * max(1.0, abs(L)):
            continue                                    # bounded by >1 level
        # A ring of free nodes just outside the contour: which way is down,
        # and how steep.
        Pb = np.pad(border, 2)
        ring = np.zeros_like(R)
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                ring |= Pb[2 + dy:Pb.shape[0] - 2 + dy, 2 + dx:Pb.shape[1] - 2 + dx]
        ring &= ~R & ~F
        if not ring.any():
            continue
        zo = Z[y0:y1, x0:x1][ring]
        sgn = 1.0 if float(zo.mean()) < L else -1.0     # summit / pit
        s = float(slope[y0:y1, x0:x1][ring].mean())
        if s <= 0:
            continue
        d = _chamfer(R, border) * h
        dmax = float(d[R].max())
        if dmax <= 0:
            continue
        dd = d[R]
        sub = Z[y0:y1, x0:x1]
        sub[R] = L + sgn * s * (dd - dd * dd / (2.0 * dmax))
    return Z


def largest_inner_rect(hull, res=400):
    """The largest axis-aligned rectangle inside the convex polygon
    ``hull`` → (x0, y0, x1, y1). Rasterised (``res`` nodes on the long
    side) + the classic largest-rectangle-in-a-histogram per row; the four
    corners are hull nodes, so the rectangle lies inside the hull."""
    import numpy as np
    hx = [q[0] for q in hull]
    hy = [q[1] for q in hull]
    bx0, bx1, by0, by1 = min(hx), max(hx), min(hy), max(hy)
    step = max(bx1 - bx0, by1 - by0) / res
    xs = bx0 + np.arange(int(math.floor((bx1 - bx0) / step)) + 1) * step
    ys = by0 + np.arange(int(math.floor((by1 - by0) / step)) + 1) * step
    X, Y = np.meshgrid(xs, ys)
    M = _inside_convex(hull, X, Y, step * 1e-6)
    ny1, nx1 = M.shape
    hgt = np.zeros(nx1, dtype=np.int64)
    best = (0.0, None)
    for i in range(ny1):
        hgt = np.where(M[i], hgt + 1, 0)
        H = hgt.tolist() + [0]
        stack = []
        for j, hj in enumerate(H):
            start = j
            while stack and stack[-1][1] >= hj:
                s0, sh = stack.pop()
                w = j - s0                       # nodes
                area = (w - 1) * (sh - 1)        # cells
                if sh >= 2 and w >= 2 and area > best[0]:
                    best = (area, (s0, i - sh + 1, j - 1, i))
                start = s0
            stack.append((start, hj))
    if best[1] is None:
        raise TopoError("No rectangle fits inside the data.")
    j0, i0, j1, i1 = best[1]
    return (float(xs[j0]), float(ys[i0]), float(xs[j1]), float(ys[i1]))


def clip_tin_to_rect(V, T, rect):
    """Cut a TIN at an axis-aligned rectangle; new rim vertices take their
    height from the triangle they lie in."""
    import numpy as np
    x0, y0, x1, y1 = rect
    A, B, C = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    tx0 = np.minimum(np.minimum(A[:, 0], B[:, 0]), C[:, 0])
    tx1 = np.maximum(np.maximum(A[:, 0], B[:, 0]), C[:, 0])
    ty0 = np.minimum(np.minimum(A[:, 1], B[:, 1]), C[:, 1])
    ty1 = np.maximum(np.maximum(A[:, 1], B[:, 1]), C[:, 1])
    inside = (tx0 >= x0) & (tx1 <= x1) & (ty0 >= y0) & (ty1 <= y1)
    outside = (tx1 <= x0) | (tx0 >= x1) | (ty1 <= y0) | (ty0 >= y1)
    keep = [T[inside]]
    rect_poly = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    extra_v, extra_t = [], []
    base = len(V)
    for t in np.nonzero(~inside & ~outside)[0].tolist():
        a, b, c = T[t].tolist()
        pa, pb, pc = V[a], V[b], V[c]
        poly = _clip_convex([(pa[0], pa[1]), (pb[0], pb[1]), (pc[0], pc[1])],
                            rect_poly)
        if len(poly) < 3:
            continue
        det = ((pb[1] - pc[1]) * (pa[0] - pc[0])
               + (pc[0] - pb[0]) * (pa[1] - pc[1]))
        if abs(det) < 1e-18:
            continue
        ids = []
        for (px, py) in poly:
            l1 = ((pb[1] - pc[1]) * (px - pc[0]) + (pc[0] - pb[0]) * (py - pc[1])) / det
            l2 = ((pc[1] - pa[1]) * (px - pc[0]) + (pa[0] - pc[0]) * (py - pc[1])) / det
            z = l1 * pa[2] + l2 * pb[2] + (1 - l1 - l2) * pc[2]
            ids.append(base + len(extra_v))
            extra_v.append((px, py, z))
        for k in range(1, len(ids) - 1):
            extra_t.append((ids[0], ids[k], ids[k + 1]))
    if extra_v:
        V = np.vstack([V, np.asarray(extra_v)])
        keep.append(np.asarray(extra_t, dtype=np.int64))
    T2 = np.vstack([k_.reshape(-1, 3) for k_ in keep]).astype(np.int64)
    span = max(x1 - x0, y1 - y0)
    return weld(V, T2, span * 1e-9)


def rim_points(V, spacing, k=12):
    """Extra points along the bounding box (corners included), their height
    by inverse-distance weighting of the ``k`` nearest data points — the
    surface is carried out to a full rectangle."""
    import numpy as np
    x0, y0 = V[:, 0].min(), V[:, 1].min()
    x1, y1 = V[:, 0].max(), V[:, 1].max()
    out = []
    for (ax, ay, bx, by) in ((x0, y0, x1, y0), (x1, y0, x1, y1),
                             (x1, y1, x0, y1), (x0, y1, x0, y0)):
        L = math.hypot(bx - ax, by - ay)
        m = max(1, int(math.ceil(L / spacing)))
        for i in range(m):                       # end = next side's start
            t = i / m
            out.append((ax + (bx - ax) * t, ay + (by - ay) * t))
    R = np.asarray(out, dtype=float)
    k = min(k, len(V))
    Z = np.empty(len(R))
    for s0 in range(0, len(R), 64):
        r = R[s0:s0 + 64]
        d2 = ((r[:, None, 0] - V[None, :, 0]) ** 2
              + (r[:, None, 1] - V[None, :, 1]) ** 2)
        idx = np.argpartition(d2, k - 1, axis=1)[:, :k]
        dk = np.take_along_axis(d2, idx, 1)
        w = 1.0 / np.maximum(dk, 1e-12)
        Z[s0:s0 + 64] = (w * V[idx, 2]).sum(1) / w.sum(1)
    pts = np.column_stack([R, Z])
    # Drop rim points that coincide with data points.
    key = {(round(x, 6), round(y, 6)) for x, y in V[:, :2].tolist()}
    keep = [i for i, (x, y) in enumerate(R.tolist())
            if (round(x, 6), round(y, 6)) not in key]
    return pts[keep]


def _box_blur(A, r, axis):
    """Moving average of width 2r+1 along ``axis`` (edges repeated)."""
    import numpy as np
    if r <= 0:
        return A
    pad = [(0, 0), (0, 0)]
    pad[axis] = (r + 1, r)
    c = np.cumsum(np.pad(A, pad, mode="edge"), axis=axis)
    n = A.shape[axis]
    hi = np.take(c, np.arange(2 * r + 1, 2 * r + 1 + n), axis=axis)
    lo = np.take(c, np.arange(0, n), axis=axis)
    return (hi - lo) / (2 * r + 1)


def _gauss(A, sigma_cells):
    """Gaussian blur ≈ three box blurs (fast at any radius)."""
    r = int(round((math.sqrt(4.0 * sigma_cells ** 2 + 1.0) - 1.0) / 2.0))
    for _ in range(3):
        A = _box_blur(_box_blur(A, r, 0), r, 1)
    return A


def smooth_surface(Z, fixed, vals, radius, h, iters=3):
    """«Perfect» instead of «raw»: blur away the creases the contours leave
    in the surface, then pull it back towards the contours (the residual at
    the contour nodes, spread out and blurred the same way). The surface no
    longer passes exactly through every line — a few centimetres off —
    but has no kinks, and real slopes have none either."""
    if radius <= 0:
        return Z
    sig = radius / h
    Zs = _gauss(Z, sig)
    for _ in range(iters):
        R = Z * 0.0
        R[fixed] = (vals - Zs)[fixed]
        C = _relax(R, fixed, 300, 1.9, 1e-7)
        Zs = Zs + _gauss(C, sig)
    return Zs


def grid_dims(bounds, p):
    """``(h, nx, ny)`` for the bounds ``(x0, y0, x1, y1)``."""
    x0, y0, x1, y1 = bounds
    w, d = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
    if p["res_mode"] == "size":
        h = min(max(p["cell_size"], max(w, d) / MAX_CELLS_SIDE),
                max(w, d) / MIN_CELLS_SIDE)
    else:
        h = max(w, d) / p["cells"]
    nx = max(1, min(MAX_CELLS_SIDE, math.ceil(w / h - 1e-9)))
    ny = max(1, min(MAX_CELLS_SIDE, math.ceil(d / h - 1e-9)))
    return h, nx, ny


def estimate_triangles(segs, p):
    """Terrain triangles the grid will give (before anything is computed):
    2 per cell, times the share of the bounding box the hull covers."""
    import numpy as np
    bounds = contour_bounds(segs)
    h, nx, ny = grid_dims(bounds, p)
    fill = 1.0
    box = max((bounds[2] - bounds[0]) * (bounds[3] - bounds[1]), 1e-12)
    if p["boundary"] in ("hull", "cut"):
        S = np.asarray(segs, dtype=float)
        hull = convex_hull(np.round(np.concatenate([S[:, 0:2], S[:, 3:5]]), 9))
        if len(hull) >= 3:
            if p["boundary"] == "cut":
                r = largest_inner_rect(hull, 200)
                fill = min(1.0, (r[2] - r[0]) * (r[3] - r[1]) / box)
            else:
                a = 0.0
                for i in range(len(hull)):
                    x0, y0 = hull[i]
                    x1, y1 = hull[(i + 1) % len(hull)]
                    a += x0 * y1 - x1 * y0
                fill = min(1.0, abs(a) * 0.5 / box)
    return int(2 * nx * ny * fill), (h, nx, ny)


def check_size(n, force=False):
    if n > MAX_TRIANGLES and not force:
        raise TopoError(
            f"About {n:,} triangles — the limit is {MAX_TRIANGLES:,} "
            "— use fewer cells or a larger cell size.")


def contour_bounds(segs):
    import numpy as np
    S = np.asarray(segs, dtype=float)
    xs = np.concatenate([S[:, 0], S[:, 3]])
    ys = np.concatenate([S[:, 1], S[:, 4]])
    return float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())


def terrain_from_contours(segs, p):
    """``(V (k,3), T (m,3) CCW triangles)`` of the terrain."""
    import numpy as np
    S = np.asarray(segs, dtype=float)
    if len(S) == 0:
        raise TopoError("No contour lines in the selection.")
    zs = S[:, [2, 5]]
    if float(zs.max() - zs.min()) < 1e-6:
        raise TopoError(
            "All contours lie at the same altitude — move the splines to "
            "their heights (Z) first.")
    check_size(estimate_triangles(segs, p)[0], p.get("force", False))
    bounds = contour_bounds(segs)
    h, nx, ny = grid_dims(bounds, p)
    x0, y0 = bounds[0], bounds[1]
    Z, fixed = solve_height_grid(S, x0, y0, h, nx, ny)
    if p["peaks"] == "round":
        Z = round_extrema(Z, fixed, h)
    if p.get("smooth_r", 0.0) > 0:
        _fx, vals = _rasterize(S, x0, y0, h, nx, ny)
        Z = smooth_surface(Z, fixed, vals, p["smooth_r"], h)

    xs = x0 + np.arange(nx + 1) * h
    ys = y0 + np.arange(ny + 1) * h
    X, Y = np.meshgrid(xs, ys)

    if p["boundary"] in ("hull", "cut"):
        xy = np.concatenate([S[:, 0:2], S[:, 3:5]])
        hull = convex_hull(np.round(xy, 9))
        if len(hull) < 3:
            raise TopoError("The contours do not span an area.")
        if p["boundary"] == "cut":
            rx0, ry0, rx1, ry1 = largest_inner_rect(hull)
            hull = [(rx0, ry0), (rx1, ry0), (rx1, ry1), (rx0, ry1)]
    else:
        hull = [(bounds[0], bounds[1]), (bounds[2], bounds[1]),
                (bounds[2], bounds[3]), (bounds[0], bounds[3])]

    eps = h * 1e-7
    inside = _inside_convex(hull, X, Y, eps)
    full = inside[:-1, :-1] & inside[:-1, 1:] & inside[1:, :-1] & inside[1:, 1:]
    if p.get("quads") and p.get("quad_rim", "whole") == "whole":
        return quad_cells(X, Y, Z, full)
    if p.get("quads") and p.get("quad_rim") == "snap":
        outline = Outline(hull)
        full = keep_off_outline(full, X, Y, outline, h)
        V, T, C = quad_cells(X, Y, Z, full)
        n0 = len(V)
        V, T, C = snap_rim(V, T, C, outline,
                           lambda xy, t: bilinear(Z, x0, y0, h, xy), h)
        if p.get("rim_relax", True):
            V = relax_rim(V, T, C, n0, lambda xy: bilinear(Z, x0, y0, h, xy), h)
        return V, T, C

    # Full cells: two triangles each, split along the diagonal whose ends
    # are closer in height (follows ridges and valleys).
    idx = np.arange((ny + 1) * (nx + 1)).reshape(ny + 1, nx + 1)
    a = idx[:-1, :-1][full]
    b = idx[:-1, 1:][full]
    c = idx[1:, 1:][full]
    d = idx[1:, :-1][full]
    Zf = Z.ravel()
    diag_ac = np.abs(Zf[a] - Zf[c]) <= np.abs(Zf[b] - Zf[d])
    # Both pairs are fans from their first vertex, so a cell can later be
    # given back as ONE quad (IngeTrazo draws a convex quad as the same fan).
    t1 = np.where(diag_ac[:, None], np.stack([a, b, c], 1), np.stack([b, c, d], 1))
    t2 = np.where(diag_ac[:, None], np.stack([a, c, d], 1), np.stack([b, d, a], 1))
    V = np.column_stack([X.ravel(), Y.ravel(), Zf])
    tris = [t1, t2]
    nfull = len(a)
    cells = [np.arange(nfull), np.arange(nfull)]
    next_cell = nfull

    # Partial cells along the boundary: clip the square, fan-triangulate.
    corner_in = (inside[:-1, :-1].astype(int) + inside[:-1, 1:] +
                 inside[1:, :-1] + inside[1:, 1:])
    # Partial cells: 1–3 corners inside, or crossed by the hull's outline
    # (a cell with no corner inside can still hold a sharp hull corner).
    part = (corner_in > 0) & (corner_in < 4)
    hp = np.asarray(hull + hull[:1], dtype=float)
    for k in range(len(hull)):
        (ax, ay), (bx, by) = hp[k], hp[k + 1]
        ns = int(math.ceil(math.hypot(bx - ax, by - ay) / (h * 0.25))) + 1
        t = np.linspace(0.0, 1.0, ns)
        cx_ = np.floor((ax + (bx - ax) * t - x0) / h).astype(np.int64)
        cy_ = np.floor((ay + (by - ay) * t - y0) / h).astype(np.int64)
        ok = (cx_ >= 0) & (cx_ < nx) & (cy_ >= 0) & (cy_ < ny)
        part[cy_[ok], cx_[ok]] = True
    part &= ~full
    extra_v = []
    extra_t = []
    extra_c = []
    base = len(V)
    iy_all, ix_all = np.nonzero(part)
    # hull edges and their boxes: each cell is clipped only by the edges
    # near it (3ds Max port: same result for a convex hull, far faster)
    HE = np.asarray([(hp[k][0], hp[k][1], hp[k + 1][0], hp[k + 1][1])
                     for k in range(len(hull))], dtype=float)
    ex0 = np.minimum(HE[:, 0], HE[:, 2]) - 1.01 * h
    ex1 = np.maximum(HE[:, 0], HE[:, 2]) + 1.01 * h
    ey0 = np.minimum(HE[:, 1], HE[:, 3]) - 1.01 * h
    ey1 = np.maximum(HE[:, 1], HE[:, 3]) + 1.01 * h
    HEl = HE.tolist()
    for iy, ix in zip(iy_all.tolist(), ix_all.tolist()):
        cx0, cy0 = x0 + ix * h, y0 + iy * h
        sq = [(cx0, cy0), (cx0 + h, cy0), (cx0 + h, cy0 + h), (cx0, cy0 + h)]
        near = np.nonzero((ex1 >= cx0) & (ex0 <= cx0 + h) &
                          (ey1 >= cy0) & (ey0 <= cy0 + h))[0]
        poly = _clip_halfplanes(sq, [HEl[k] for k in near.tolist()])
        if len(poly) < 3:
            continue
        area = 0.0
        for k in range(len(poly)):
            area += (poly[k][0] * poly[(k + 1) % len(poly)][1]
                     - poly[(k + 1) % len(poly)][0] * poly[k][1])
        if area * 0.5 < h * h * 1e-6:
            continue
        z00, z10 = Z[iy, ix], Z[iy, ix + 1]
        z01, z11 = Z[iy + 1, ix], Z[iy + 1, ix + 1]
        ids = []
        for (px, py) in poly:
            fu = min(max((px - cx0) / h, 0.0), 1.0)
            fv = min(max((py - cy0) / h, 0.0), 1.0)
            z = (z00 * (1 - fu) * (1 - fv) + z10 * fu * (1 - fv)
                 + z01 * (1 - fu) * fv + z11 * fu * fv)
            ids.append(base + len(extra_v))
            extra_v.append((px, py, z))
        for k in range(1, len(ids) - 1):
            extra_t.append((ids[0], ids[k], ids[k + 1]))
            extra_c.append(next_cell)
        next_cell += 1
    if extra_v:
        V = np.vstack([V, np.asarray(extra_v)])
        tris.append(np.asarray(extra_t, dtype=np.int64).reshape(-1, 3))
        cells.append(np.asarray(extra_c, dtype=np.int64))
    T = np.vstack([t.reshape(-1, 3) for t in tris]).astype(np.int64)
    C = np.concatenate(cells).astype(np.int64)
    V, T, ok = weld(V, T, h * 1e-6, with_mask=True)
    return V, T, C[ok]


# ---------------------------------------------------------------------------
# Points → Delaunay TIN (Bowyer–Watson, numpy-vectorised circle test)
# ---------------------------------------------------------------------------

def _circum(P, a, b, c):
    ax, ay = P[a]
    bx, by = P[b]
    cx, cy = P[c]
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-300:
        return (0.0, 0.0, math.inf)
    a2, b2, c2 = ax * ax + ay * ay, bx * bx + by * by, cx * cx + cy * cy
    ux = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d
    uy = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d
    return (ux, uy, (ax - ux) ** 2 + (ay - uy) ** 2)


def _incircle_ok(cx, cy, r2, px, py):
    return (cx - px) ** 2 + (cy - py) ** 2 < r2


def delaunay(xy):
    """Delaunay triangulation of (n, 2) points → (m, 3) CCW index array.

    Bowyer–Watson with a neighbour map: each point is found by walking from
    the last new triangle (points inserted in a snake order over a grid, so
    the walk is short) and only the triangles around it are tested — about
    linear time instead of quadratic."""
    import numpy as np
    xy = np.asarray(xy, dtype=float)
    n = len(xy)
    if n < 3:
        raise TopoError("At least three points are needed.")
    mn, mx = xy.min(0), xy.max(0)
    span = float(max(mx - mn)) or 1.0
    c = (mn + mx) / 2
    P = ((xy - c) / span).tolist()
    big = 1.0e4
    P += [[-big, -big], [big, -big], [0.0, big]]
    X = [q[0] for q in P]
    Y = [q[1] for q in P]

    tri = []          # [a, b, c] CCW, or None when deleted
    cc = []           # (cx, cy, r2)
    edge = {}         # directed edge (a, b) -> triangle id

    def circ(a, b, c3):
        ax, ay, bx, by, cx_, cy_ = X[a], Y[a], X[b], Y[b], X[c3], Y[c3]
        d = 2.0 * (ax * (by - cy_) + bx * (cy_ - ay) + cx_ * (ay - by))
        if abs(d) < 1e-300:
            return (0.0, 0.0, math.inf)
        a2, b2, c2 = ax * ax + ay * ay, bx * bx + by * by, cx_ * cx_ + cy_ * cy_
        ux = (a2 * (by - cy_) + b2 * (cy_ - ay) + c2 * (ay - by)) / d
        uy = (a2 * (cx_ - bx) + b2 * (ax - cx_) + c2 * (bx - ax)) / d
        return (ux, uy, (ax - ux) ** 2 + (ay - uy) ** 2)

    def add(a, b, c3):
        t = len(tri)
        tri.append([a, b, c3])
        cc.append(circ(a, b, c3))
        edge[(a, b)] = t
        edge[(b, c3)] = t
        edge[(c3, a)] = t
        return t

    last = add(n, n + 1, n + 2)

    # Insertion order: snake over a √n × √n grid of buckets (locality).
    k = max(1, int(math.sqrt(n / 4.0)))
    gx = np.minimum((((xy[:, 0] - mn[0]) / (span or 1)) * k).astype(int), k - 1)
    gy = np.minimum((((xy[:, 1] - mn[1]) / (span or 1)) * k).astype(int), k - 1)
    gx = np.where(gy % 2 == 1, k - 1 - gx, gx)
    order = np.lexsort((xy[:, 0], gx, gy)).tolist()

    def orient(a, b, px, py):
        return (X[b] - X[a]) * (py - Y[a]) - (Y[b] - Y[a]) * (px - X[a])

    for i in order:
        px, py = X[i], Y[i]
        # 1. Walk to the triangle that holds the point.
        t = last
        if tri[t] is None:
            t = next(j for j in range(len(tri) - 1, -1, -1) if tri[j] is not None)
        steps = 0
        while True:
            a, b, c3 = tri[t]
            if orient(a, b, px, py) < 0:
                nt = edge.get((b, a))
            elif orient(b, c3, px, py) < 0:
                nt = edge.get((c3, b))
            elif orient(c3, a, px, py) < 0:
                nt = edge.get((a, c3))
            else:
                break
            steps += 1
            if nt is None or steps > 4 * len(tri) + 10:
                # Fallback (degenerate walk): any triangle whose circle
                # holds the point.
                nt = next(j for j, tt in enumerate(tri) if tt is not None
                          and _incircle_ok(*cc[j], px, py))
                t = nt
                break
            t = nt
        # 2. The cavity: triangles around it whose circle holds the point.
        bad = {t}
        stack = [t]
        while stack:
            u = stack.pop()
            a, b, c3 = tri[u]
            for e0, e1 in ((a, b), (b, c3), (c3, a)):
                v = edge.get((e1, e0))
                if v is not None and v not in bad:
                    cx_, cy_, r2 = cc[v]
                    if (cx_ - px) ** 2 + (cy_ - py) ** 2 < r2:
                        bad.add(v)
                        stack.append(v)
        # 3. Its rim, then re-triangulate as a fan to the point.
        rim = []
        for u in bad:
            a, b, c3 = tri[u]
            for e0, e1 in ((a, b), (b, c3), (c3, a)):
                if edge.get((e1, e0)) not in bad:
                    rim.append((e0, e1))
        for u in bad:
            a, b, c3 = tri[u]
            for e in ((a, b), (b, c3), (c3, a)):
                if edge.get(e) == u:
                    del edge[e]
            tri[u] = None
        for e0, e1 in rim:
            last = add(e0, e1, i)

    T = np.asarray([tt for tt in tri if tt is not None], dtype=np.int64)
    T = T[(T < n).all(1)]
    A, B, C = xy[T[:, 0]], xy[T[:, 1]], xy[T[:, 2]]
    cr = (B[:, 0] - A[:, 0]) * (C[:, 1] - A[:, 1]) - (B[:, 1] - A[:, 1]) * (C[:, 0] - A[:, 0])
    T[cr < 0] = T[cr < 0][:, [0, 2, 1]]
    return T[np.abs(cr) > span * span * 1e-14]


def trim_long_edges(V, T, max_len):
    """Peel rim triangles with an edge longer than ``max_len`` (a concave
    outline instead of the convex hull)."""
    import numpy as np
    if max_len <= 0 or len(T) == 0:
        return T
    T = T.copy()
    while True:
        e = np.concatenate([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]])
        k = np.sort(e, 1)
        _u, inv, cnt = np.unique(k, axis=0, return_inverse=True,
                                 return_counts=True)
        inv = inv.ravel()
        rim = (cnt[inv] == 1)
        L = np.hypot(*(V[e[:, 0], :2] - V[e[:, 1], :2]).T)
        bad_e = rim & (L > max_len)
        m = len(T)
        bad_t = bad_e[:m] | bad_e[m:2 * m] | bad_e[2 * m:]
        if not bad_t.any():
            return T
        T = T[~bad_t]
        if len(T) == 0:
            raise TopoError("Max. edge length removed every triangle — "
                            "increase it or set it to 0.")


def estimate_point_triangles(n_points):
    """A Delaunay TIN of n points has ≈ 2n triangles."""
    return max(0, 2 * int(n_points) - 2)


def terrain_from_points(points, p):
    import numpy as np
    V = np.asarray(points, dtype=float)
    if len(V) < 3:
        raise TopoError("Select at least three points (Point helpers, "
                        "mesh/poly vertices or spline knots).")
    check_size(estimate_point_triangles(len(V)), p.get("force", False))
    mode = p["boundary"]
    if mode == "box":
        ext = V[:, :2].max(0) - V[:, :2].min(0)
        area = float(ext[0] * ext[1]) or float(max(ext)) ** 2 or 1.0
        spacing = max(math.sqrt(area / len(V)) * 1.5, float(max(ext)) / 400)
        V = np.vstack([V, rim_points(V, spacing)])
    T = delaunay(V[:, :2])
    if len(T) == 0:
        raise TopoError("The points are collinear — no surface.")
    if mode == "hull":
        T = trim_long_edges(V, T, p["max_edge"])
    elif mode == "cut":
        hull = convex_hull(np.round(V[:, :2], 9))
        V, T = clip_tin_to_rect(V, T, largest_inner_rect(hull))
    return V, T


def weld(V, T, tol, with_mask=False):
    """Merge coincident vertices; drop degenerate triangles."""
    import numpy as np
    key = np.round(V / max(tol, 1e-9)).astype(np.int64)
    _u, first, inv = np.unique(key, axis=0, return_index=True,
                               return_inverse=True)
    inv = inv.ravel()
    V2 = V[first]
    T2 = inv[T]
    ok = (T2[:, 0] != T2[:, 1]) & (T2[:, 1] != T2[:, 2]) & (T2[:, 0] != T2[:, 2])
    if with_mask:
        return V2, T2[ok], ok
    return V2, T2[ok]


# ---------------------------------------------------------------------------
# Clean quads: whole grid cells only, vertices numbered row by row
# ---------------------------------------------------------------------------

def quad_cells(X, Y, Z, full):
    """Grid nodes ``X, Y, Z`` (ny+1, nx+1) and the cells to keep ``full``
    (ny, nx) → ``(V, T, C)``: two fan triangles per cell (split along the
    diagonal whose ends are closer in height), C = cell id. Only the nodes
    the cells use are kept, numbered row by row (rows south → north,
    west → east in each row); cells in the same order. ``assemble`` turns
    each cell back into ONE quad polygon."""
    import numpy as np
    if not full.any():
        raise TopoError("No whole grid cell fits — use smaller cells.")
    ny, nx = full.shape
    idx = np.arange((ny + 1) * (nx + 1)).reshape(ny + 1, nx + 1)
    used = np.zeros((ny + 1, nx + 1), bool)
    used[:-1, :-1] |= full
    used[:-1, 1:] |= full
    used[1:, :-1] |= full
    used[1:, 1:] |= full
    remap = -np.ones(idx.size, dtype=np.int64)
    remap[used.ravel()] = np.arange(int(used.sum()))
    a = remap[idx[:-1, :-1][full]]
    b = remap[idx[:-1, 1:][full]]
    c = remap[idx[1:, 1:][full]]
    d = remap[idx[1:, :-1][full]]
    Zf = Z.ravel()[used.ravel()]
    diag_ac = np.abs(Zf[a] - Zf[c]) <= np.abs(Zf[b] - Zf[d])
    t1 = np.where(diag_ac[:, None], np.stack([a, b, c], 1), np.stack([b, c, d], 1))
    t2 = np.where(diag_ac[:, None], np.stack([a, c, d], 1), np.stack([b, d, a], 1))
    n = len(a)
    T = np.empty((2 * n, 3), dtype=np.int64)
    T[0::2], T[1::2] = t1, t2                 # a cell's two triangles together
    C = np.repeat(np.arange(n, dtype=np.int64), 2)
    V = np.column_stack([X.ravel()[used.ravel()], Y.ravel()[used.ravel()], Zf])
    return V, T, C


def min_rect_angle(xy):
    """Angle (radians, -45°…45°) of the smallest rectangle round the points
    — a grid turned by it runs along the site."""
    import numpy as np
    hull = np.asarray(convex_hull(np.round(np.asarray(xy, float), 9)), float)
    if len(hull) < 3:
        return 0.0
    best, angle = None, 0.0
    for i in range(len(hull)):
        dx, dy = hull[(i + 1) % len(hull)] - hull[i]
        if dx == 0 and dy == 0:
            continue
        a = math.atan2(dy, dx)
        c, s = math.cos(a), math.sin(a)
        u = hull[:, 0] * c + hull[:, 1] * s
        v = -hull[:, 0] * s + hull[:, 1] * c
        area = float(np.ptp(u) * np.ptp(v))
        if best is None or area < best - 1e-12 * max(area, 1.0):
            best, angle = area, a
    q = math.pi / 2
    angle = (angle + q / 2) % q - q / 2          # same rectangle, nearest to X
    return 0.0 if abs(angle) < 1e-9 else angle


def sample_tin(P, Zv, T, u0, v0, h, nx, ny):
    """Heights of the grid nodes ``u0 + i·h, v0 + j·h`` on the TIN
    (vertices ``P`` (n, 2), heights ``Zv``); NaN outside the TIN."""
    import numpy as np
    out = np.full((ny + 1) * (nx + 1), np.nan)
    A, B, Cc = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    det = (B[:, 1] - Cc[:, 1]) * (A[:, 0] - Cc[:, 0]) + \
          (Cc[:, 0] - B[:, 0]) * (A[:, 1] - Cc[:, 1])
    ok = np.abs(det) > 1e-18
    A, B, Cc, det, T = A[ok], B[ok], Cc[ok], det[ok], T[ok]
    lo = np.minimum(np.minimum(A, B), Cc)
    hi = np.maximum(np.maximum(A, B), Cc)
    e = 1e-7
    i0 = np.clip(np.ceil((lo[:, 0] - u0) / h - e), 0, nx).astype(np.int64)
    i1 = np.clip(np.floor((hi[:, 0] - u0) / h + e), -1, nx).astype(np.int64)
    j0 = np.clip(np.ceil((lo[:, 1] - v0) / h - e), 0, ny).astype(np.int64)
    j1 = np.clip(np.floor((hi[:, 1] - v0) / h + e), -1, ny).astype(np.int64)
    wi = np.maximum(i1 - i0 + 1, 0)
    wj = np.maximum(j1 - j0 + 1, 0)
    cnt = wi * wj
    start = 0
    while start < len(T):                       # chunks of ≈ 4 M candidates
        cs = np.cumsum(cnt[start:])
        stop = start + max(1, int(np.searchsorted(cs, 4_000_000)) + 1)
        sl = slice(start, min(stop, len(T)))
        n = cnt[sl]
        tot = int(n.sum())
        start = sl.stop
        if tot == 0:
            continue
        t = np.repeat(np.arange(sl.start, sl.stop), n)
        k = np.arange(tot) - np.repeat(np.cumsum(n) - n, n)
        ii = i0[t] + k % wi[t]
        jj = j0[t] + k // wi[t]
        px, py = u0 + ii * h, v0 + jj * h
        l1 = ((B[t, 1] - Cc[t, 1]) * (px - Cc[t, 0]) +
              (Cc[t, 0] - B[t, 0]) * (py - Cc[t, 1])) / det[t]
        l2 = ((Cc[t, 1] - A[t, 1]) * (px - Cc[t, 0]) +
              (A[t, 0] - Cc[t, 0]) * (py - Cc[t, 1])) / det[t]
        l3 = 1.0 - l1 - l2
        tol = -1e-9
        inside = (l1 >= tol) & (l2 >= tol) & (l3 >= tol)
        tt = T[t[inside]]
        z = (l1[inside] * Zv[tt[:, 0]] + l2[inside] * Zv[tt[:, 1]]
             + l3[inside] * Zv[tt[:, 2]])
        out[jj[inside] * (nx + 1) + ii[inside]] = z
    return out.reshape(ny + 1, nx + 1)


class Outline:
    """A closed CCW polyline (the footprint) with arc-length parameters;
    optional heights ``z`` at its corners (interpolated along the edges)."""

    def __init__(self, xy, z=None):
        import numpy as np
        P = np.asarray(xy, dtype=float)[:, :2]
        Z = None if z is None else np.asarray(z, dtype=float)
        if len(P) > 1 and np.allclose(P[0], P[-1]):
            P = P[:-1]
            Z = None if Z is None else Z[:-1]
        if polygon_area(P) < 0:
            P = P[::-1]
            Z = None if Z is None else Z[::-1]
        self.P, self.Z = P, Z
        self.Q = np.roll(P, -1, axis=0)
        self.seg = np.hypot(*(self.Q - P).T)
        self.cum = np.concatenate([[0.0], np.cumsum(self.seg)])
        self.length = float(self.cum[-1])

    def project(self, pts):
        """Nearest point on the outline → (parameter t, distance)."""
        import numpy as np
        pts = np.asarray(pts, dtype=float)[:, :2]
        best_t = np.zeros(len(pts))
        best_d = np.full(len(pts), np.inf)
        D = self.Q - self.P
        L2 = np.maximum((D ** 2).sum(1), 1e-300)
        step = max(1, 4_000_000 // max(len(self.P), 1))
        for s0 in range(0, len(pts), step):
            q = pts[s0:s0 + step]
            u = ((q[:, None, 0] - self.P[None, :, 0]) * D[None, :, 0] +
                 (q[:, None, 1] - self.P[None, :, 1]) * D[None, :, 1]) / L2[None]
            u = np.clip(u, 0.0, 1.0)
            cx = self.P[None, :, 0] + u * D[None, :, 0]
            cy = self.P[None, :, 1] + u * D[None, :, 1]
            d = np.hypot(q[:, None, 0] - cx, q[:, None, 1] - cy)
            k = d.argmin(1)
            r = np.arange(len(q))
            best_d[s0:s0 + step] = d[r, k]
            best_t[s0:s0 + step] = self.cum[k] + u[r, k] * self.seg[k]
        return best_t, best_d

    def distance(self, pts):
        return self.project(pts)[1]

    def _seg_of(self, t):
        import numpy as np
        t = np.mod(np.asarray(t, dtype=float), self.length)
        k = np.clip(np.searchsorted(self.cum, t, side="right") - 1, 0, len(self.P) - 1)
        f = (t - self.cum[k]) / np.maximum(self.seg[k], 1e-300)
        return k, f

    def at(self, t):
        """Points at the parameters ``t`` (wrapped round the loop)."""
        k, f = self._seg_of(t)
        return self.P[k] + f[:, None] * (self.Q[k] - self.P[k])

    def z_at(self, t):
        import numpy as np
        k, f = self._seg_of(t)
        Zn = np.roll(self.Z, -1)
        return self.Z[k] + f * (Zn[k] - self.Z[k])

    def corners(self, min_turn_deg=25.0):
        """Parameters of the outline's real corners (turn ≥ min_turn)."""
        import numpy as np
        a = self.Q - self.P
        b = np.roll(a, 1, axis=0)                        # edge arriving at P[i]
        ang = np.degrees(np.abs(np.arctan2(b[:, 0] * a[:, 1] - b[:, 1] * a[:, 0],
                                           (b * a).sum(1))))
        return self.cum[:-1][ang >= min_turn_deg]


def polygon_area(P):
    import numpy as np
    P = np.asarray(P, dtype=float)
    return 0.5 * float(np.sum(P[:, 0] * np.roll(P[:, 1], -1)
                              - np.roll(P[:, 0], -1) * P[:, 1]))


def snap_rim(V, T, C, outline, zfun, h):
    """Whole-cell quads (``quad_cells``) → the same quads plus ONE ring of
    quads out to ``outline``: every rim node of the cells gets a partner on
    the outline (nearest point, kept in order and evened out; the outline's
    corners are hit exactly). Heights of the new nodes: ``zfun(xy, t)``.
    The new nodes follow the old ones, each loop from its south-west node."""
    import numpy as np
    _rim, loops = rim_loops(T)
    V = np.asarray(V, dtype=float)
    newV, newT, newC = [], [], []
    nid = len(V)
    cid = int(C.max()) + 1 if len(C) else 0
    L = outline.length
    corners = outline.corners()
    for loop in loops:
        if len(loop) < 4 or polygon_area(V[loop, :2]) <= 0:
            continue                                     # a hole: leave it
        k0 = int(np.argmin(loop))                        # lowest number = SW
        loop = loop[k0:] + loop[:k0]
        n = len(loop)
        t, _d = outline.project(V[loop, :2])
        # unwrap into one increasing turn round the outline
        d = np.diff(np.concatenate([t, t[:1]]))
        d = (d + L / 2) % L - L / 2
        if abs(float(d.sum()) - L) > 0.25 * L:
            continue                                     # not round the outline
        d = np.maximum(d, 1e-3 * h)
        d *= L / float(d.sum())
        tt = t[0] + np.concatenate([[0.0], np.cumsum(d[:-1])])
        for _ in range(4):                               # even the spacing out
            prev = np.roll(tt, 1)
            prev[0] -= L
            nxt = np.roll(tt, -1)
            nxt[-1] += L
            tt = 0.25 * prev + 0.5 * tt + 0.25 * nxt
        for c in corners:                                # hit the corners
            c = tt[0] + ((c - tt[0]) % L)
            i = int(np.argmin(np.abs(tt - c)))
            lo = tt[i - 1] if i > 0 else tt[-1] - L
            hi = tt[i + 1] if i < n - 1 else tt[0] + L
            if lo < c < hi:
                tt[i] = c
        P2 = outline.at(tt)
        Z2 = np.asarray(zfun(P2, tt), dtype=float)
        ids = list(range(nid, nid + n))
        nid += n
        newV.append(np.column_stack([P2, Z2]))
        for i in range(n):
            A, B = loop[i], loop[(i + 1) % n]
            A2, B2 = ids[i], ids[(i + 1) % n]
            newT += [(A, A2, B2), (A, B2, B)]            # quad A A' B' B
            newC += [cid, cid]
            cid += 1
    if not newV:
        return V, T, C
    return (np.vstack([V] + newV),
            np.vstack([T, np.asarray(newT, dtype=np.int64)]),
            np.concatenate([C, np.asarray(newC, dtype=np.int64)]))


def relax_rim(V, T, C, first_outline_id, zfun, h, rings=2, iters=12):
    """Even out the quads next to a snapped rim: the nodes up to ``rings``
    quad edges in from the outline move step by step towards the middle of
    their neighbours (the outline nodes stay put); a step that would fold
    or squash a quad is not taken. Moved nodes get their height again from
    the surface, ``zfun(xy)``."""
    import numpy as np
    V = np.array(V, dtype=float)
    polys = cells_to_polys(T, C)
    nbr = {}
    owner = {}
    for qi, q in enumerate(polys):
        for k in range(len(q)):
            a, b = q[k], q[(k + 1) % len(q)]
            nbr.setdefault(a, set()).add(b)
            nbr.setdefault(b, set()).add(a)
            owner.setdefault(a, []).append(qi)
    fixed = set(range(first_outline_id, len(V)))
    depth = {i: 0 for i in fixed}
    front = list(fixed)
    for d in range(1, rings + 1):
        nxt = []
        for i in front:
            for j in nbr.get(i, ()):
                if j not in depth:
                    depth[j] = d
                    nxt.append(j)
        front = nxt
    movable = sorted(i for i, d in depth.items() if d >= 1)
    if not movable:
        return V
    min_area = 0.05 * h * h

    def ok(i):
        for qi in owner.get(i, ()):
            if polygon_area(V[polys[qi], :2]) < min_area:
                return False
        return True

    for _ in range(iters):
        for i in movable:
            old = V[i, :2].copy()
            m = np.mean(V[list(nbr[i]), :2], axis=0)
            V[i, :2] = old + 0.5 * (m - old)
            if not ok(i):
                V[i, :2] = old
    z = np.asarray(zfun(V[movable, :2]), dtype=float)
    good = np.isfinite(z)
    V[np.asarray(movable)[good], 2] = z[good]
    return V


def tin_at(P, Zv, T, xy):
    """Heights of the TIN (vertices ``P`` (n, 2), heights ``Zv``) at the
    points ``xy``; NaN outside it."""
    import numpy as np
    xy = np.asarray(xy, dtype=float)
    out = np.full(len(xy), np.nan)
    A, B, Cc = P[T[:, 0]], P[T[:, 1]], P[T[:, 2]]
    det = (B[:, 1] - Cc[:, 1]) * (A[:, 0] - Cc[:, 0]) + \
          (Cc[:, 0] - B[:, 0]) * (A[:, 1] - Cc[:, 1])
    ok = np.abs(det) > 1e-18
    A, B, Cc, det, T = A[ok], B[ok], Cc[ok], det[ok], T[ok]
    step = max(1, 4_000_000 // max(len(T), 1))
    for s0 in range(0, len(xy), step):
        q = xy[s0:s0 + step]
        l1 = ((B[None, :, 1] - Cc[None, :, 1]) * (q[:, None, 0] - Cc[None, :, 0]) +
              (Cc[None, :, 0] - B[None, :, 0]) * (q[:, None, 1] - Cc[None, :, 1])) / det[None]
        l2 = ((Cc[None, :, 1] - A[None, :, 1]) * (q[:, None, 0] - Cc[None, :, 0]) +
              (A[None, :, 0] - Cc[None, :, 0]) * (q[:, None, 1] - Cc[None, :, 1])) / det[None]
        l3 = 1.0 - l1 - l2
        inside = (l1 >= -1e-9) & (l2 >= -1e-9) & (l3 >= -1e-9)
        has = inside.any(1)
        k = inside.argmax(1)
        r = np.arange(len(q))
        tt = T[k]
        z = (l1[r, k] * Zv[tt[:, 0]] + l2[r, k] * Zv[tt[:, 1]]
             + l3[r, k] * Zv[tt[:, 2]])
        out[s0:s0 + step] = np.where(has, z, np.nan)
    return out


def keep_off_outline(full, X, Y, outline, h):
    """Whole cells whose corners stay ≥ 0.4 cells off the outline — room
    for the ring of quads ``snap_rim`` lays round them."""
    import numpy as np
    used = np.zeros(X.shape, bool)
    used[:-1, :-1] |= full
    used[:-1, 1:] |= full
    used[1:, :-1] |= full
    used[1:, 1:] |= full
    ok = np.zeros(X.shape, bool)
    ok[used] = outline.distance(np.column_stack([X[used], Y[used]])) >= 0.4 * h
    return full & ok[:-1, :-1] & ok[:-1, 1:] & ok[1:, :-1] & ok[1:, 1:]


def bilinear(Z, x0, y0, h, xy):
    """Heights of the grid ``Z`` at the points ``xy`` (clamped to it)."""
    import numpy as np
    ny, nx = Z.shape[0] - 1, Z.shape[1] - 1
    fx = np.clip((xy[:, 0] - x0) / h, 0, nx)
    fy = np.clip((xy[:, 1] - y0) / h, 0, ny)
    i = np.minimum(np.floor(fx).astype(int), max(nx - 1, 0))
    j = np.minimum(np.floor(fy).astype(int), max(ny - 1, 0))
    u, v = fx - i, fy - j
    return (Z[j, i] * (1 - u) * (1 - v) + Z[j, i + 1] * u * (1 - v)
            + Z[j + 1, i] * (1 - u) * v + Z[j + 1, i + 1] * u * v)


def quad_grid_from_tin(V, T, p):
    """A TIN (points) → clean quads: a regular grid over it (turned along
    the site with ``grid_angle`` "auto" and the outline footprint), heights
    sampled from the TIN, whole cells inside it only — with ``quad_rim``
    "snap" plus a ring of quads out to the TIN's outline."""
    import numpy as np
    used = np.unique(T.ravel())
    theta = 0.0
    if p.get("grid_angle", "auto") == "auto" and p["boundary"] == "hull":
        theta = min_rect_angle(V[used, :2])
    c, s = math.cos(theta), math.sin(theta)
    L = np.column_stack([V[:, 0] * c + V[:, 1] * s,
                         -V[:, 0] * s + V[:, 1] * c])
    u0, v0 = L[used].min(0)
    u1, v1 = L[used].max(0)
    h, nx, ny = grid_dims((u0, v0, u1, v1), p)
    check_size(2 * nx * ny, p.get("force", False))
    Z = sample_tin(L, V[:, 2], T, u0, v0, h, nx, ny)
    fin = np.isfinite(Z)
    full = fin[:-1, :-1] & fin[:-1, 1:] & fin[1:, :-1] & fin[1:, 1:]
    U, W = np.meshgrid(u0 + np.arange(nx + 1) * h, v0 + np.arange(ny + 1) * h)
    outline = None
    if p.get("quad_rim") == "snap":
        _rim, loops = rim_loops(T)
        best = 0.0
        for lp in loops:                             # the TIN's outer outline
            if len(lp) >= 3 and polygon_area(L[lp]) > best:
                best = polygon_area(L[lp])
                outline = Outline(L[lp], V[lp, 2])
        if outline is not None:
            full = keep_off_outline(full, U, W, outline, h)
    Vq, Tq, Cq = quad_cells(U, W, np.nan_to_num(Z), full)
    if outline is not None:
        n0 = len(Vq)
        Vq, Tq, Cq = snap_rim(Vq, Tq, Cq, outline,
                              lambda xy, t: outline.z_at(t), h)
        if p.get("rim_relax", True):
            Vq = relax_rim(Vq, Tq, Cq, n0,
                           lambda xy: tin_at(L, V[:, 2], T, xy), h)
    X = Vq[:, 0] * c - Vq[:, 1] * s
    Y = Vq[:, 0] * s + Vq[:, 1] * c
    return np.column_stack([X, Y, Vq[:, 2]]), Tq, Cq


# ---------------------------------------------------------------------------
# Skirt, bottom, the group
# ---------------------------------------------------------------------------

def rim_loops(T):
    """Directed rim edges (interior on the left) chained into loops."""
    import numpy as np
    e = np.concatenate([T[:, [0, 1]], T[:, [1, 2]], T[:, [2, 0]]])
    k = np.sort(e, 1)
    _u, inv, cnt = np.unique(k, axis=0, return_inverse=True, return_counts=True)
    rim = e[cnt[inv.ravel()] == 1]
    nxt: dict = {}
    for a, b in rim.tolist():
        nxt.setdefault(a, []).append(b)
    loops = []
    used = set()
    for a, b in rim.tolist():
        if (a, b) in used:
            continue
        loop = [a]
        cur, to = a, b
        while (cur, to) not in used:
            used.add((cur, to))
            loop.append(to)
            cur = to
            outs = [x for x in nxt.get(cur, []) if (cur, x) not in used]
            if not outs:
                break
            to = outs[0]
        if loop[-1] == loop[0]:
            loop.pop()
        loops.append(loop)
    return rim, loops


def cells_to_polys(T, C):
    """Triangles that fan from one cell (same id in ``C``, consecutive) →
    one polygon per cell: a quad for a full grid cell, the clipped polygon
    on the rim. IngeTrazo draws a convex polygon as the fan from its first
    vertex — exactly the triangles it was made of."""
    import numpy as np
    order = np.argsort(C, kind="stable")      # a cell's fan, in fan order
    T, C = T[order], C[order]
    polys = []
    cur, poly = None, None
    for (a, b, c), cid in zip(T.tolist(), C.tolist()):
        if cid == cur and poly is not None and poly[0] == a and poly[-1] == b:
            poly.append(c)
            continue
        if poly is not None:
            polys.append(poly)
        cur, poly = cid, [a, b, c]
    if poly is not None:
        polys.append(poly)
    return polys


def build_polygons(V, T, p, segs=None):
    """Extra polygons (skirt quads, bottom loops) as ``(rings, kinds)`` and
    extra edges — the terrain triangles themselves stay arrays."""
    import numpy as np
    polys, kinds = [], []
    zmin = float(V[:, 2].min())
    zmax = float(V[:, 2].max())
    base = zmin - p["skirt_depth"]
    edges = []
    if p["skirt"]:
        rim, loops = rim_loops(T)
        if p["skirt_depth"] > 1e-9:
            for a, b in rim.tolist():
                A, B = V[a].tolist(), V[b].tolist()
                polys.append([tuple(B), tuple(A), (A[0], A[1], base),
                              (B[0], B[1], base)])
                kinds.append("skirt")
        if p["bottom"]:
            for loop in loops:
                if len(loop) < 3:
                    continue
                xy = V[loop, :2]
                area = 0.5 * float(np.sum(xy[:, 0] * np.roll(xy[:, 1], -1)
                                          - np.roll(xy[:, 0], -1) * xy[:, 1]))
                if area <= 0:
                    continue                    # a hole in the rim
                polys.append([(float(V[i, 0]), float(V[i, 1]), base)
                              for i in reversed(loop)])
                kinds.append("bottom")
    map_z = base if p["skirt"] else zmin - max(1.0, 0.05 * (zmax - zmin))
    if segs:
        for s in segs:
            if p.get("contours"):
                edges.append((tuple(s[:3]), tuple(s[3:])))
            if p.get("map"):
                edges.append(((s[0], s[1], map_z), (s[3], s[4], map_z)))
    return polys, kinds, edges


# ---------------------------------------------------------------------------
# Contour set — the lines the Altitude Editor works on
# ---------------------------------------------------------------------------

def _dp_keep(P, tol):
    """Douglas–Peucker on the XY of an open polyline → kept indices."""
    import numpy as np
    n = len(P)
    keep = np.zeros(n, dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        seg = P[b, :2] - P[a, :2]
        L = float(np.hypot(*seg))
        q = P[a + 1:b, :2] - P[a, :2]
        if L < 1e-12:
            d = np.hypot(q[:, 0], q[:, 1])
        else:
            d = np.abs(q[:, 0] * seg[1] - q[:, 1] * seg[0]) / L
        k = int(np.argmax(d))
        if d[k] > tol:
            m = a + 1 + k
            keep[m] = True
            stack.append((a, m))
            stack.append((m, b))
    return keep


def simplify_line(xyz, tol, closed):
    """Fewer vertices, same shape: drop the ones closer than ``tol`` to the
    line through their neighbours (Douglas–Peucker, in plan)."""
    import numpy as np
    if tol <= 0 or len(xyz) < 3:
        return xyz
    if closed:
        P = xyz[:-1] if np.allclose(xyz[0], xyz[-1]) else xyz
        if len(P) < 4:
            return xyz
        far = int(np.argmax(np.hypot(*(P[:, :2] - P[0, :2]).T)))
        A = P[:far + 1]
        B = np.vstack([P[far:], P[:1]])
        ka, kb = _dp_keep(A, tol), _dp_keep(B, tol)
        out = np.vstack([A[ka], B[kb][1:]])
        if len(out) < 4:                  # keep at least a triangle
            return xyz
        return out
    return xyz[_dp_keep(xyz, tol)]


def smooth_line(xyz, passes, closed):
    """Remove small zigzags without shrinking the line: Taubin smoothing
    (a step towards the neighbours, then a slightly larger one back).
    Open lines keep their end points."""
    import numpy as np
    if passes <= 0 or len(xyz) < 3:
        return xyz
    loop = closed and np.allclose(xyz[0], xyz[-1])
    P = xyz[:-1].copy() if loop else xyz.copy()
    if len(P) < 3:
        return xyz
    for _ in range(int(passes)):
        for f in (0.5, -0.53):
            if closed:
                avg = (np.roll(P, 1, 0) + np.roll(P, -1, 0)) * 0.5
                P = P + f * (avg - P)
            else:
                avg = (P[:-2] + P[2:]) * 0.5
                P[1:-1] = P[1:-1] + f * (avg - P[1:-1])
    return np.vstack([P, P[:1]]) if loop else P


def line_length(xyz):
    import numpy as np
    return float(np.sum(np.hypot(*np.diff(xyz[:, :2], axis=0).T)))


class ContourSet:
    """The contour lines of one terrain: each line keeps its original
    vertices; ``alt`` (an altitude the user gave it, or None = keep its own
    heights) and ``on`` (included or not) are the edits."""

    def __init__(self, lines):
        import numpy as np
        self.lines = []
        for ln in lines:
            xyz = np.asarray(ln["xyz"], dtype=float).reshape(-1, 3)
            if len(xyz) < 2:
                continue
            closed = bool(ln.get("closed", np.allclose(xyz[0], xyz[-1])))
            alt = ln.get("alt")
            self.lines.append({"xyz": xyz, "closed": closed,
                               "alt": None if alt is None else float(alt),
                               "on": bool(ln.get("on", True))})
        self.clean = {"simplify": 0.0, "smooth": 0, "min_len": 0.0}
        self._geo = {}

    def set_clean(self, simplify=0.0, smooth=0, min_len=0.0):
        """Clean-up settings (metres / passes); True when they changed."""
        new = {"simplify": max(0.0, float(simplify)),
               "smooth": max(0, int(smooth)),
               "min_len": max(0.0, float(min_len))}
        if new == self.clean:
            return False
        if (new["simplify"], new["smooth"]) != (self.clean["simplify"],
                                                self.clean["smooth"]):
            self._geo = {}
        self.clean = new
        return True

    def length(self, i):
        return line_length(self.lines[i]["xyz"])

    def is_short(self, i):
        m = self.clean["min_len"]
        return m > 0 and self.length(i) < m

    def active(self, i):
        return self.lines[i]["on"] and not self.is_short(i)

    def cleaned(self, i):
        """Smoothed and simplified vertices (own heights), cached."""
        g = self._geo.get(i)
        if g is None:
            ln = self.lines[i]
            g = smooth_line(ln["xyz"], self.clean["smooth"], ln["closed"])
            g = simplify_line(g, self.clean["simplify"], ln["closed"])
            self._geo[i] = g
        return g

    def geom(self, i):
        """What the terrain is built from: cleaned, at the effective height."""
        ln = self.lines[i]
        g = self.cleaned(i)
        if ln["alt"] is None:
            return g
        q = g.copy()
        q[:, 2] = ln["alt"]
        return q

    def stats(self):
        """(vertices before, after, short lines ignored) of the lines on."""
        before = after = short = 0
        for i, ln in enumerate(self.lines):
            if not ln["on"]:
                continue
            if self.is_short(i):
                short += 1
                continue
            before += len(ln["xyz"])
            after += len(self.cleaned(i))
        return before, after, short

    @classmethod
    def from_segs(cls, segs):
        import numpy as np
        out = []
        for pl in chain_segments(segs):
            xyz = np.asarray(pl, dtype=float)
            out.append({"xyz": xyz, "closed": len(xyz) > 2 and
                        bool(np.allclose(xyz[0], xyz[-1]))})
        # Longest first: the list reads from the main lines down.
        out.sort(key=lambda d: -float(np.sum(np.hypot(
            *np.diff(d["xyz"][:, :2], axis=0).T))))
        return cls(out)

    @classmethod
    def from_record(cls, rec):
        return cls(rec)

    def to_record(self):
        return [{"xyz": [[round(float(v), 4) for v in q] for q in ln["xyz"]],
                 "closed": ln["closed"], "alt": ln["alt"], "on": ln["on"]}
                for ln in self.lines]

    def __len__(self):
        return len(self.lines)

    def own_z(self, i):
        """The line's own (mean) height and whether it varies (3D line)."""
        z = self.lines[i]["xyz"][:, 2]
        return float(z.mean()), float(z.max() - z.min()) > 1e-3

    def altitude(self, i):
        ln = self.lines[i]
        return ln["alt"] if ln["alt"] is not None else self.own_z(i)[0]

    def xyz(self, i):
        """Vertices at the effective height."""
        ln = self.lines[i]
        if ln["alt"] is None:
            return ln["xyz"]
        q = ln["xyz"].copy()
        q[:, 2] = ln["alt"]
        return q

    def segs(self):
        out = []
        for i, ln in enumerate(self.lines):
            if not self.active(i):
                continue
            q = self.geom(i)
            for a, b in zip(q[:-1], q[1:]):
                if (a[0], a[1]) != (b[0], b[1]):
                    out.append((float(a[0]), float(a[1]), float(a[2]),
                                float(b[0]), float(b[1]), float(b[2])))
        return out

    def all_flat(self):
        """True when every included line sits at one height (a 2D DWG)."""
        zs = {round(self.altitude(i), 4) for i in range(len(self.lines))
              if self.active(i)}
        return len(zs) <= 1




# ---------------------------------------------------------------------------
# Compute: source + params → mesh arrays (no 3ds Max objects)
# ---------------------------------------------------------------------------

def compute(data, p):
    """``data``: {"mode": "contours", "cset": ContourSet} or
    {"mode": "points", "points": [...]}; ``p`` in system units.
    → dict with V, T, C (cells or None), segs (contours used), info."""
    import numpy as np
    t0 = time.perf_counter()
    C = None
    segs = None
    if data["mode"] == "contours":
        cset = data["cset"]
        cset.set_clean(p["simplify"], p["smooth"], p["min_len"])
        segs = cset.segs()
        if not segs:
            raise TopoError("No contour line is included.")
        V, T, C = terrain_from_contours(segs, p)
    else:
        V, T = terrain_from_points(data["points"], p)
        if p.get("quads"):
            V, T, C = quad_grid_from_tin(np.asarray(V, float),
                                         np.asarray(T, np.int64), p)
    V = np.asarray(V, dtype=float)
    T = np.asarray(T, dtype=np.int64)
    if len(T) == 0:
        raise TopoError("No surface could be built.")
    check_size(len(T), p.get("force", False))
    return {"V": V, "T": T, "C": C, "segs": segs,
            "seconds": time.perf_counter() - t0}


def assemble(res, p):
    """Mesh arrays for 3ds Max: compact vertices, terrain faces (triangles
    or one polygon per grid cell), skirt, bottom loops.
    → dict(xs, tris, sg, hide, bottoms, extra, nfaces, unit, zmin, zmax,
    base)"""
    import numpy as np
    V, T, C = res["V"], res["T"], res["C"]
    polys, kinds, _e = build_polygons(V, T, p, None)
    used = np.zeros(len(V), bool)
    used[T.ravel()] = True
    remap = -np.ones(len(V), dtype=np.int64)
    remap[used] = np.arange(int(used.sum()))
    Vc = V[used]
    T2 = remap[T]
    span = float(max(np.ptp(Vc[:, 0]), np.ptp(Vc[:, 1]), 1e-9))
    tol = span * 1e-7
    key_of = {}
    for i, q in enumerate(Vc.tolist()):
        key_of[(round(q[0] / tol), round(q[1] / tol), round(q[2] / tol))] = i
    verts = Vc.tolist()

    def vid(q, allow_new=True):
        k = (round(q[0] / tol), round(q[1] / tol), round(q[2] / tol))
        j = key_of.get(k)
        if j is None and allow_new:
            j = len(verts)
            verts.append(list(q))
            key_of[k] = j
        return j

    tris, sg, hide = [], [], []
    soft = bool(p["soft"])
    # terrain
    nfaces = 0
    unit = "triangles"
    qpolys = None
    if C is not None and p.get("quads"):
        unit = "quads"
        qpolys = cells_to_polys(T2, C)
        for poly in qpolys:
            n = len(poly)
            for k in range(1, n - 1):
                f = len(tris)
                tris.append((poly[0], poly[k], poly[k + 1]))
                sg.append(1 if soft else 0)
                if k >= 2:
                    hide.append((f, 1))            # v0–vk
                if k + 1 <= n - 2:
                    hide.append((f, 3))            # vk+1–v0
            nfaces += 1
    else:
        for a, b, c in T2.tolist():
            tris.append((a, b, c))
            sg.append(1 if soft else 0)
        nfaces = len(T2)
    # quads: the bottom is the terrain's cell grid again, flat at the base
    # (instead of one big polygon); its vertices follow the terrain's, row
    # by row, and the skirt shares the ones on the rim
    zbase = float(V[:, 2].min()) - p["skirt_depth"]
    quad_bottom = (qpolys is not None and p["skirt"] and p["bottom"]
                   and any(k == "bottom" for k in kinds))
    if quad_bottom:
        nterr = len(verts)
        base_of = [vid((q[0], q[1], zbase)) for q in verts[:nterr]]
    # skirt quads (B, A, A_base, B_base) → two triangles, hidden diagonal
    bottoms = []
    for ring, kind in zip(polys, kinds):
        if kind == "skirt":
            B, A, Ab, Bb = (vid(q) for q in ring)
            f = len(tris)
            tris.append((B, A, Ab))
            tris.append((B, Ab, Bb))
            sg += [2 if soft else 0] * 2
            hide += [(f, 3), (f + 1, 1)]
        elif kind == "bottom" and not quad_bottom:
            bottoms.append([vid(q) for q in ring])
    if quad_bottom:
        for poly in qpolys:
            ids = [base_of[i] for i in reversed(poly)]      # faces down
            n = len(ids)
            for k in range(1, n - 1):
                f = len(tris)
                tris.append((ids[0], ids[k], ids[k + 1]))
                sg.append(4 if soft else 0)
                if k >= 2:
                    hide.append((f, 1))
                if k + 1 <= n - 2:
                    hide.append((f, 3))
    # vertices only the bottom uses go after the mesh vertices
    used_v = np.zeros(len(verts), bool)
    used_v[np.asarray(tris, dtype=np.int64).ravel()] = True
    nmesh = int(used_v.sum())
    if nmesh != len(verts):
        order = np.concatenate([np.nonzero(used_v)[0], np.nonzero(~used_v)[0]])
        newid = np.empty(len(verts), dtype=np.int64)
        newid[order] = np.arange(len(verts))
        verts = [verts[i] for i in order.tolist()]
        tris = [tuple(int(newid[v]) for v in t) for t in tris]
        bottoms = [[int(newid[v]) for v in b] for b in bottoms]
    zmin, zmax = float(V[:, 2].min()), float(V[:, 2].max())
    return {"verts": verts, "nmesh": nmesh, "tris": tris, "sg": sg,
            "hide": hide, "bottoms": bottoms, "nfaces": nfaces, "unit": unit,
            "zmin": zmin, "zmax": zmax,
            "base": zmin - p["skirt_depth"]}


def slope_max(res):
    """Steepest terrain triangle (degrees)."""
    import numpy as np
    V, T = res["V"], res["T"]
    A, B, Cc = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
    n = np.cross(B - A, Cc - A)
    nl = np.linalg.norm(n, axis=1)
    pa = np.abs(n[:, 2])                    # 2 × plan area
    # ignore sliver triangles along the clipped rim (no real slope)
    ok = (nl > 1e-300) & (pa > 1e-3 * float(np.median(pa) if len(pa) else 0))
    if not ok.any():
        return 0.0
    return float(np.degrees(np.arccos(np.clip(np.abs(n[ok, 2]) / nl[ok], 0, 1))).max())


def slope_text(deg):
    if deg < 0.05:
        return "flat"
    if deg >= 89.9:
        return f"{deg:.0f}°"
    return f"{deg:.0f}° (1 : {1.0 / math.tan(math.radians(deg)):.1f})"


# ---------------------------------------------------------------------------
# 3ds Max: build the Editable Poly (+ child splines)
# ---------------------------------------------------------------------------

_MXS_BUILD = r"""
fn pesiTopoBuildFile path = (
    -- mesh data from a binary file (large arrays are not passed through
    -- pymxs: that can upset the MAXScript garbage collector)
    local f = fopen path "rb"
    local nv = ReadLong f #unsigned
    local nmesh = ReadLong f #unsigned
    local nf = ReadLong f #unsigned
    local nhid = ReadLong f #unsigned
    local nbot = ReadLong f #unsigned
    local nloops = ReadLong f #unsigned
    local vs = #()
    vs.count = nmesh
    for i = 1 to nmesh do vs[i] = [ReadFloat f, ReadFloat f, ReadFloat f]
    local extra = #()
    for i = nmesh + 1 to nv do append extra [ReadFloat f, ReadFloat f, ReadFloat f]
    local fs = #()
    fs.count = nf
    for i = 1 to nf do fs[i] = [ReadLong f #unsigned, ReadLong f #unsigned, ReadLong f #unsigned]
    local sg = #()
    sg.count = nf
    for i = 1 to nf do sg[i] = ReadByte f #unsigned
    local m = mesh vertices:vs faces:fs
    vs = undefined
    fs = undefined
    for i = 1 to nf do setFaceSmoothGroup m i (if sg[i] == 0 then 0 else (bit.set 0 sg[i] true))
    for i = 1 to nhid do (
        local fc = ReadLong f #unsigned
        local ed = ReadByte f #unsigned
        setEdgeVis m fc ed false
    )
    update m
    convertToPoly m
    for p in extra do polyop.createVert m p
    local failed = 0
    local bot = for i = 1 to nbot collect (ReadLong f #unsigned)
    local k = 0
    for i = 1 to nloops do (
        local c = ReadLong f #unsigned
        local loop = for j = 1 to c collect bot[k + j]
        k += c
        local r = try (polyop.createPolygon m loop) catch undefined
        if r == undefined do failed += 1
    )
    fclose f
    CenterPivot m
    #(m, failed)
)
fn pesiTopoSplineFile nm path = (
    local f = fopen path "rb"
    local nl = ReadLong f #unsigned
    local s = SplineShape name:nm
    for i = 1 to nl do (
        local c = ReadLong f #unsigned
        local cl = ReadByte f #unsigned
        local sp = addNewSpline s
        for j = 1 to c do addKnot s sp #corner #line [ReadFloat f, ReadFloat f, ReadFloat f]
        if cl == 1 do close s sp
    )
    fclose f
    updateShape s
    CenterPivot s
    s
)
"""


def _next_name():
    rt = _rt()
    used = {str(n.name) for n in rt.objects}
    if "Terrain" not in used:
        return "Terrain"
    k = 2
    while f"Terrain {k}" in used:
        k += 1
    return f"Terrain {k}"


def _spline(name, lines, closed):
    import struct
    import tempfile
    import numpy as np
    rt = _rt()
    path = os.path.join(tempfile.gettempdir(), "pesi_topology_lines.bin")
    with open(path, "wb") as fh:
        fh.write(struct.pack("<I", len(lines)))
        for ln, c in zip(lines, closed):
            P = np.asarray(ln, dtype="<f4").reshape(-1, 3)
            if c and len(P) > 2 and np.allclose(P[0], P[-1]):
                P = P[:-1]                     # close() adds the last segment
            fh.write(struct.pack("<IB", len(P), 1 if c else 0))
            fh.write(P.tobytes())
    s = rt.pesiTopoSplineFile(name, path)
    rt.setAppData(s, CHILD_ID, "1")
    return s


def build_node(res, p, data, rec=None, name="Terrain"):
    """Editable Poly terrain node (+ contour / map child splines)."""
    _ensure_mxs()
    rt = _rt()
    A = assemble(res, p)
    import struct
    import tempfile
    import numpy as np
    path = os.path.join(tempfile.gettempdir(), "pesi_topology_mesh.bin")
    verts = np.asarray(A["verts"], dtype="<f4").reshape(-1, 3)
    tris = np.asarray(A["tris"], dtype="<u4").reshape(-1, 3) + 1
    sg = np.asarray(A["sg"], dtype="u1")
    with open(path, "wb") as fh:
        nbot = sum(len(b) for b in A["bottoms"])
        fh.write(struct.pack("<6I", len(verts), A["nmesh"], len(tris),
                             len(A["hide"]), nbot, len(A["bottoms"])))
        fh.write(verts.tobytes())
        fh.write(tris.tobytes())
        fh.write(sg.tobytes())
        for f_, e_ in A["hide"]:
            fh.write(struct.pack("<IB", f_ + 1, e_))
        for b in A["bottoms"]:
            fh.write(np.asarray(b, dtype="<u4").__add__(1).tobytes())
        for b in A["bottoms"]:
            fh.write(struct.pack("<I", len(b)))
    out = rt.pesiTopoBuildFile(path)
    node, failed = out[0], int(out[1])
    node.name = name
    node.wirecolor = rt.color(120, 150, 90)
    if rec is not None:
        rt.setAppData(node, APPDATA_ID, json.dumps(rec, separators=(",", ":")))
    # child splines
    kids = []
    if data["mode"] == "contours" and (p.get("contours") or p.get("map")):
        cset = data["cset"]
        lines, closed = [], []
        for i in range(len(cset)):
            if cset.active(i):
                g = cset.geom(i)
                lines.append(g.tolist())
                closed.append(cset.lines[i]["closed"])
        if lines:
            if p.get("contours"):
                kids.append(_spline(name + " Contours", lines, closed))
            if p.get("map"):
                if p["skirt"]:
                    mz = A["base"]
                else:
                    mz = A["zmin"] - max(units_per_metre(),
                                         0.05 * (A["zmax"] - A["zmin"]))
                flat = [[[q[0], q[1], mz] for q in ln] for ln in lines]
                kids.append(_spline(name + " Map", flat, closed))
    for k in kids:
        k.parent = node
        k.wirecolor = rt.color(60, 90, 160)
    return node, kids, A, failed


def make_record(data, p):
    rec = {"mode": data["mode"], "version": VERSION,
           "params": {k: v for k, v in normalize_params(p).items()
                      if k != "force"}}
    if data["mode"] == "contours":
        rec["lines"] = data["cset"].to_record()
    else:
        rec["points"] = [[round(float(v), 5) for v in q]
                         for q in data["points"]]
        if data.get("source"):                 # Terrain from Plan: file, scale
            rec["source"] = data["source"]
    return rec


def data_from_record(rec):
    if rec["mode"] == "contours":
        return {"mode": "contours", "cset": ContourSet.from_record(rec["lines"])}
    data = {"mode": "points", "points": [tuple(q) for q in rec["points"]]}
    if rec.get("source"):
        data["source"] = rec["source"]
    return data


def _children(node):
    rt = _rt()
    return [c for c in node.children if _is_child(c)]


def _copy_look(src, dst):
    rt = _rt()
    dst.name = src.name
    for attr in ("material", "wirecolor", "parent", "renderable",
                 "castShadows", "receiveShadows", "primaryVisibility",
                 "secondaryVisibility", "gbufferChannel"):
        try:
            setattr(dst, attr, getattr(src, attr))
        except Exception:  # noqa: BLE001
            pass
    try:
        src.layer.addNode(dst)
    except Exception:  # noqa: BLE001
        pass


def commit(res, data, p_ui, p_sys, old=None, select=True):
    """Create the terrain (or replace ``old``) as ONE undo step."""
    import pymxs
    rt = _rt()
    with pymxs.undo(True, "Topology"):
        rec = make_record(data, p_ui)
        name = _next_name() if old is None else str(old.name)
        node, kids, A, failed = build_node(res, p_sys, data, rec,
                                           "tmp" if old is not None else name)
        if old is not None and not rt.isDeleted(old):
            for c in _children(old):
                rt.delete(c)
            _copy_look(old, node)
            for k in kids:
                k.name = str(node.name) + k.name[3:]
                try:
                    old.layer.addNode(k)
                except Exception:  # noqa: BLE001
                    pass
            rt.delete(old)
        if select:
            rt.select(node)
    rt.redrawViews()
    return node


def _set_hidden(node, hidden):
    """Hide/unhide a terrain and its child splines while it is being edited.
    Outside the undo history: otherwise undoing an edit brings the old
    terrain back hidden."""
    import pymxs
    with pymxs.undo(False):
        node.isHidden = hidden
        for c in _children(node):
            c.isHidden = hidden


def _zoom_to(node):
    """Frame the active viewport on ``node`` (selection stays as it is),
    with a margin - ZoomToBounds on the bounding box cuts corners off in a
    perspective view, a cube round the bounding sphere fits from any angle."""
    rt = _rt()
    try:
        lo, hi = node.min, node.max
        c = (lo + hi) / 2
        r = rt.length(hi - lo) / 2 * 0.6     # ZoomToBounds adds its own margin
        d = rt.Point3(r, r, r)
        rt.viewport.ZoomToBounds(False, c - d, c + d)
    except Exception:  # noqa: BLE001
        pass


def selected_terrain():
    rt = _rt()
    sel = [n for n in rt.selection if is_terrain(n)]
    return sel[0] if len(sel) == 1 else None


# ---------------------------------------------------------------------------
# The dialog (modeless, parented to the 3ds Max main window)
# ---------------------------------------------------------------------------

def _make_dialog_class():
    import pymxs
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox,
                                   QDialog, QDoubleSpinBox, QGridLayout,
                                   QGroupBox, QHBoxLayout, QLabel,
                                   QMessageBox, QPushButton, QRadioButton,
                                   QSpinBox, QVBoxLayout)
    rt = _rt()

    def dspin(lo, hi, dec=2, step=0.1, suffix=" m", special=None):
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setDecimals(dec)
        s.setSingleStep(step)
        s.setSuffix(suffix)
        if special:
            s.setSpecialValueText(special)
        return s

    class TopologyDialog(QDialog):
        _PV_ON = ("QPushButton { background: #2e9e4f; color: white; "
                  "font-weight: bold; border: 1px solid #1f7a3a; "
                  "border-radius: 3px; padding: 4px 10px; }")
        _PV_OFF = "QPushButton { padding: 4px 10px; }"
        _ST = {"ok": "background:#1f6b3a; color:white;",
               "err": "background:#8a2a2a; color:white;",
               "off": "background:#444; color:#ddd;",
               "warn": "background:#8a6a1a; color:white;"}

        def __init__(self, data, old=None, parent=None):
            super().__init__(parent)
            self.data = data
            self.mode = data["mode"]
            self.old = old
            # a terrain from a plan appears somewhere new: show it once
            self._frame = old is None and bool(data.get("source"))
            self.preview = []            # preview nodes
            self.result = None           # (res, key)
            self._busy = False
            self._last_sel = None
            if old is not None:
                self.params = normalize_params(terrain_record(old).get("params"))
                what = "Edit Terrain"
            else:
                self.params = load_params()
                what = ("Terrain from Contours" if self.mode == "contours"
                        else "Terrain from Points")
            self.setWindowTitle(f"Topology — {what}")
            self.setAttribute(Qt.WA_DeleteOnClose, True)
            self.setMinimumWidth(460)
            self._build_ui()
            self._load_ui()
            self._timer = QTimer(self)
            self._timer.setSingleShot(True)
            self._timer.setInterval(300)
            self._timer.timeout.connect(self._recompute)
            self._poll = QTimer(self)
            self._poll.setInterval(700)
            self._poll.timeout.connect(self._poll_selection)
            self._poll.start()
            if old is not None:
                _set_hidden(old, True)
            self._update_source()
            self._schedule()

        # ---------------- UI ----------------
        def _build_ui(self):
            lay = QVBoxLayout(self)
            self.setStyleSheet("QGroupBox { margin-top: 10px; padding-top: 8px; }"
                               "QGroupBox::title { subcontrol-origin: margin; left: 6px; }")
            contours = self.mode == "contours"
            # Source
            g = QGroupBox("Source")
            gl = QGridLayout(g)
            self.lbl_src = QLabel("")
            self.lbl_src.setWordWrap(True)
            gl.addWidget(self.lbl_src, 0, 0, 1, 3)
            self.chk_follow = QCheckBox("Follow selection")
            gl.addWidget(self.chk_follow, 1, 0, 1, 2)
            self.btn_read = QPushButton("Read selection")
            gl.addWidget(self.btn_read, 1, 2)
            lay.addWidget(g)
            # Clean up lines (contours)
            self.sp_simplify = dspin(0, 1000, 2, 0.05, " m", "Off")
            self.sp_smooth_l = QSpinBox()
            self.sp_smooth_l.setRange(0, 10)
            self.sp_smooth_l.setSpecialValueText("Off")
            self.sp_smooth_l.setSuffix(" passes")
            self.sp_minlen = dspin(0, 100000, 1, 1.0, " m", "Off")
            self.lbl_clean = QLabel("")
            if contours:
                g = QGroupBox("Clean up lines")
                gl = QGridLayout(g)
                gl.addWidget(QLabel("Simplify (tolerance):"), 0, 0)
                gl.addWidget(self.sp_simplify, 0, 1)
                gl.addWidget(QLabel("Smooth:"), 1, 0)
                gl.addWidget(self.sp_smooth_l, 1, 1)
                gl.addWidget(QLabel("Ignore lines shorter than:"), 2, 0)
                gl.addWidget(self.sp_minlen, 2, 1)
                gl.addWidget(self.lbl_clean, 3, 0, 1, 2)
                lay.addWidget(g)
            # Grid / Triangulation
            self.rb_cells = QRadioButton("Cells on long side")
            self.rb_size = QRadioButton("Cell size")
            bg = QButtonGroup(self)
            bg.addButton(self.rb_cells)
            bg.addButton(self.rb_size)
            self.sp_cells = QSpinBox()
            self.sp_cells.setRange(MIN_CELLS_SIDE, MAX_CELLS_SIDE)
            self.sp_cells.setSingleStep(10)
            self.sp_csize = dspin(0.01, 10000, 3, 0.25)
            self.cb_bound = QComboBox()
            self.cb_peaks = QComboBox()
            self.cb_peaks.addItem("Rounded (interpolated)", "round")
            self.cb_peaks.addItem("Flat", "flat")
            self.sp_sr = dspin(0, 1000, 1, 0.5, " m", "Off (raw)")
            self.sp_maxedge = dspin(0, 100000, 2, 1.0, " m", "Off")
            self.lbl_grid = QLabel("")
            self.cb_angle = QComboBox()
            self.cb_angle.addItem("Along the site (auto)", "auto")
            self.cb_angle.addItem("World X / Y", "axis")
            self.cb_rim = QComboBox()
            self.cb_rim.addItem("Whole cells only (stepped rim)", "whole")
            self.cb_rim.addItem("Snap to the outline (quads, clean rim)", "snap")
            if contours:
                self.cb_rim.addItem("Cut to the outline (n-gons on the rim)", "cut")
            self.cb_rim.setToolTip(
                "Whole cells only: only grid cells that lie inside - the rim "
                "steps along the outline.\n"
                "Snap to the outline: the whole cells plus one ring of quads "
                "whose outer nodes sit on the outline (corners included).\n"
                "Cut to the outline: the rim cells are cut off at the outline "
                "(triangles and pentagons there).")
            if contours:
                g = QGroupBox("Grid")
                gl = QGridLayout(g)
                gl.addWidget(self.rb_cells, 0, 0)
                gl.addWidget(self.sp_cells, 0, 1)
                gl.addWidget(self.rb_size, 1, 0)
                gl.addWidget(self.sp_csize, 1, 1)
                gl.addWidget(self.lbl_grid, 2, 0, 1, 2)
                gl.addWidget(QLabel("Footprint:"), 3, 0)
                self.cb_bound.addItem("Outline (convex hull)", "hull")
                gl.addWidget(self.cb_bound, 3, 1)
                gl.addWidget(QLabel("Summits & pits:"), 4, 0)
                gl.addWidget(self.cb_peaks, 4, 1)
                gl.addWidget(QLabel("Smooth surface (radius):"), 5, 0)
                gl.addWidget(self.sp_sr, 5, 1)
                self.sp_sr.setToolTip(
                    "Off: the surface runs exactly through every contour.\n"
                    "A radius (e.g. 2–5 m) rounds the whole surface off "
                    "without creases at the lines.")
            else:
                g = QGroupBox("Triangulation")
                gl = QGridLayout(g)
                gl.addWidget(QLabel("Footprint:"), 0, 0)
                self.cb_bound.addItem("Outline of the points", "hull")
                gl.addWidget(self.cb_bound, 0, 1)
                gl.addWidget(QLabel("Max. edge length on the rim:"), 1, 0)
                gl.addWidget(self.sp_maxedge, 1, 1)
                gl.addWidget(self.lbl_grid, 2, 0, 1, 2)
                # quad grid (Output ▸ Quads)
                gl.addWidget(self.rb_cells, 3, 0)
                gl.addWidget(self.sp_cells, 3, 1)
                gl.addWidget(self.rb_size, 4, 0)
                gl.addWidget(self.sp_csize, 4, 1)
                gl.addWidget(QLabel("Quad grid direction:"), 5, 0)
                gl.addWidget(self.cb_angle, 5, 1)
            self.cb_bound.addItem("Rectangle — interpolated to the full box", "box")
            self.cb_bound.addItem("Rectangle — cut inside the data", "cut")
            lay.addWidget(g)
            # Output
            g = QGroupBox("Output")
            gl = QGridLayout(g)
            self.chk_quads = QCheckBox("Quads instead of triangles")
            if not contours:
                self.chk_quads.setText("Quads instead of triangles (regular grid)")
                self.chk_quads.setToolTip(
                    "A regular grid is laid over the points: clean quads, the "
                    "vertices numbered row by row.\nThe surface follows the "
                    "triangulation of the points, but the points themselves "
                    "are no longer vertices.")
            self.chk_soft = QCheckBox("Smooth shading (smoothing groups)")
            self.chk_skirt = QCheckBox("Skirt, depth below the lowest point:")
            self.sp_depth = dspin(0, 100000, 2, 0.5)
            self.chk_bottom = QCheckBox("Close the bottom (solid)")
            self.chk_cont = QCheckBox("Include the contours (child spline)")
            self.chk_map = QCheckBox("Include a contour map (flat, at the base)")
            r = 0
            gl.addWidget(self.chk_quads, r, 0, 1, 2)
            gl.addWidget(QLabel("Quads on the rim:"), r + 1, 0)
            gl.addWidget(self.cb_rim, r + 1, 1)
            self.chk_relax = QCheckBox("Relax the rim quads (no sharp corners)")
            self.chk_relax.setToolTip(
                "Snap to the outline: the nodes of the first two rows inside "
                "the rim move towards the middle of their neighbours, so the "
                "quads along the rim come out even. The outline stays exact.")
            gl.addWidget(self.chk_relax, r + 2, 0, 1, 2)
            r += 3
            gl.addWidget(self.chk_soft, r, 0, 1, 2)
            gl.addWidget(self.chk_skirt, r + 1, 0)
            gl.addWidget(self.sp_depth, r + 1, 1)
            gl.addWidget(self.chk_bottom, r + 2, 0, 1, 2)
            r += 3
            if contours:
                gl.addWidget(self.chk_cont, r, 0, 1, 2)
                gl.addWidget(self.chk_map, r + 1, 0, 1, 2)
            lay.addWidget(g)
            # Status + buttons
            self.lbl_status = QLabel("")
            self.lbl_status.setWordWrap(True)
            self.lbl_status.setMargin(6)
            lay.addWidget(self.lbl_status)
            hl = QHBoxLayout()
            self.btn_pv = QPushButton("● Live Preview ON")
            self.btn_pv.setCheckable(True)
            self.btn_pv.setChecked(True)
            self.btn_reset = QPushButton("Reset")
            self.btn_ok = QPushButton("OK")
            self.btn_ok.setDefault(True)
            self.btn_cancel = QPushButton("Cancel")
            hl.addWidget(self.btn_pv)
            hl.addWidget(self.btn_reset)
            hl.addStretch(1)
            hl.addWidget(self.btn_ok)
            hl.addWidget(self.btn_cancel)
            lay.addLayout(hl)
            # signals
            for w in (self.sp_simplify, self.sp_smooth_l, self.sp_minlen,
                      self.sp_cells, self.sp_csize, self.sp_sr,
                      self.sp_maxedge, self.sp_depth):
                w.valueChanged.connect(self._changed)
            for w in (self.cb_bound, self.cb_peaks, self.cb_angle, self.cb_rim):
                w.currentIndexChanged.connect(self._changed)
            for w in (self.rb_cells, self.chk_quads, self.chk_relax, self.chk_soft,
                      self.chk_skirt, self.chk_bottom, self.chk_cont,
                      self.chk_map, self.chk_follow):
                w.toggled.connect(self._changed)
            self.btn_read.clicked.connect(self._read_selection)
            self.btn_pv.toggled.connect(self._toggle_preview)
            self.btn_reset.clicked.connect(self._reset)
            self.btn_ok.clicked.connect(self._ok)
            self.btn_cancel.clicked.connect(self.reject)

        def _widgets(self):
            return (self.sp_simplify, self.sp_smooth_l, self.sp_minlen,
                    self.sp_cells, self.sp_csize, self.sp_sr, self.sp_maxedge,
                    self.sp_depth, self.cb_bound, self.cb_peaks, self.rb_cells,
                    self.rb_size, self.chk_quads, self.chk_soft,
                    self.chk_skirt, self.chk_bottom, self.chk_cont,
                    self.chk_map, self.chk_follow, self.cb_angle, self.cb_rim,
                    self.chk_relax)

        def _load_ui(self):
            p = self.params
            for w in self._widgets():
                w.blockSignals(True)
            self.sp_simplify.setValue(p["simplify"])
            self.sp_smooth_l.setValue(p["smooth"])
            self.sp_minlen.setValue(p["min_len"])
            self.rb_cells.setChecked(p["res_mode"] == "cells")
            self.rb_size.setChecked(p["res_mode"] == "size")
            self.sp_cells.setValue(p["cells"])
            self.sp_csize.setValue(p["cell_size"])
            self.sp_sr.setValue(p["smooth_r"])
            self.sp_maxedge.setValue(p["max_edge"])
            self.sp_depth.setValue(p["skirt_depth"])
            self.cb_bound.setCurrentIndex(max(0, self.cb_bound.findData(p["boundary"])))
            self.cb_peaks.setCurrentIndex(max(0, self.cb_peaks.findData(p["peaks"])))
            self.chk_quads.setChecked(p["quads"])
            self.cb_angle.setCurrentIndex(max(0, self.cb_angle.findData(p["grid_angle"])))
            self.cb_rim.setCurrentIndex(max(0, self.cb_rim.findData(p["quad_rim"])))
            self.chk_relax.setChecked(p["rim_relax"])
            self.chk_soft.setChecked(p["soft"])
            self.chk_skirt.setChecked(p["skirt"])
            self.chk_bottom.setChecked(p["bottom"])
            self.chk_cont.setChecked(p["contours"])
            self.chk_map.setChecked(p["map"])
            self.chk_follow.setChecked(p["follow"])
            for w in self._widgets():
                w.blockSignals(False)
            self._enable()
            self._style_pv()

        def _read_ui(self):
            return normalize_params({
                "res_mode": "cells" if self.rb_cells.isChecked() else "size",
                "cells": self.sp_cells.value(),
                "cell_size": self.sp_csize.value(),
                "boundary": self.cb_bound.currentData(),
                "peaks": self.cb_peaks.currentData(),
                "simplify": self.sp_simplify.value(),
                "smooth": self.sp_smooth_l.value(),
                "min_len": self.sp_minlen.value(),
                "max_edge": self.sp_maxedge.value(),
                "soft": self.chk_soft.isChecked(),
                "quads": self.chk_quads.isChecked(),
                "quad_rim": self.cb_rim.currentData(),
                "grid_angle": self.cb_angle.currentData(),
                "rim_relax": self.chk_relax.isChecked(),
                "smooth_r": self.sp_sr.value(),
                "skirt": self.chk_skirt.isChecked(),
                "skirt_depth": self.sp_depth.value(),
                "bottom": self.chk_bottom.isChecked(),
                "contours": self.chk_cont.isChecked(),
                "map": self.chk_map.isChecked(),
                "follow": self.chk_follow.isChecked(),
                "force": self.params.get("force", False),
            })

        def _enable(self):
            q = self.chk_quads.isChecked()
            grid = self.mode == "contours" or q      # points: grid only for quads
            self.rb_cells.setEnabled(grid)
            self.rb_size.setEnabled(grid)
            self.sp_cells.setEnabled(grid and self.rb_cells.isChecked())
            self.sp_csize.setEnabled(grid and self.rb_size.isChecked())
            self.cb_angle.setEnabled(q and self.cb_bound.currentData() == "hull")
            self.cb_rim.setEnabled(q)
            self.chk_relax.setEnabled(q and self.cb_rim.currentData() == "snap")
            sk = self.chk_skirt.isChecked()
            self.sp_depth.setEnabled(sk)
            self.chk_bottom.setEnabled(sk)
            self.sp_maxedge.setEnabled(self.cb_bound.currentData() == "hull")

        def _style_pv(self):
            on = self.btn_pv.isChecked()
            self.btn_pv.setText("● Live Preview ON" if on else "○ Live Preview OFF")
            self.btn_pv.setStyleSheet(self._PV_ON if on else self._PV_OFF)

        def _status(self, kind, text):
            self.lbl_status.setStyleSheet(self._ST[kind])
            self.lbl_status.setText(text)

        # ---------------- source ----------------
        def _update_source(self):
            import numpy as np
            p = self._read_ui()
            ps = solver_params(p)
            if self.mode == "contours":
                cset = self.data["cset"]
                cset.set_clean(ps["simplify"], ps["smooth"], ps["min_len"])
                n_on = sum(1 for i in range(len(cset)) if cset.active(i))
                segs = cset.segs()
                if not segs:
                    self.lbl_src.setText(f"{len(cset)} contour lines — none included.")
                    self.lbl_grid.setText("")
                    return
                S = np.asarray(segs)
                z = S[:, [2, 5]]
                x0, y0, x1, y1 = contour_bounds(segs)
                self.lbl_src.setText(
                    f"{n_on} of {len(cset)} contour lines · "
                    f"{fmt_len(x1 - x0, 1)} × {fmt_len(y1 - y0, 1)} · "
                    f"altitude {fmt_len(z.min())} … {fmt_len(z.max())}")
                b, a, short = cset.stats()
                txt = f"Vertices: {b:,}"
                if a != b:
                    txt += f" → <b>{a:,}</b> ({100 * (b - a) / max(b, 1):.0f} % fewer)"
                if short:
                    txt += f" · {short} short line(s) ignored"
                self.lbl_clean.setText(txt)
                try:
                    n, (h, nx, ny) = estimate_triangles(segs, ps)
                    unit = (f"≈ {n // 2:,} quads" if p["quads"]
                            else f"≈ {n:,} triangles")
                    self.lbl_grid.setText(f"Grid: {nx} × {ny} cells, "
                                          f"{fmt_len(h)} · {unit}")
                except Exception:  # noqa: BLE001
                    self.lbl_grid.setText("")
            else:
                pts = np.asarray(self.data["points"], dtype=float).reshape(-1, 3)
                if len(pts) == 0:
                    self.lbl_src.setText("No points.")
                    return
                ext = pts[:, :2].max(0) - pts[:, :2].min(0)
                self.lbl_src.setText(
                    f"{len(pts):,} points · {fmt_len(ext[0], 1)} × "
                    f"{fmt_len(ext[1], 1)} · altitude "
                    f"{fmt_len(pts[:, 2].min())} … {fmt_len(pts[:, 2].max())}")
                area = float(ext[0] * ext[1]) or 1.0
                sp = math.sqrt(area / max(len(pts), 1))
                if p["quads"]:
                    theta = 0.0
                    if p["grid_angle"] == "auto" and p["boundary"] == "hull":
                        theta = min_rect_angle(pts[:, :2])
                    c, s = math.cos(theta), math.sin(theta)
                    u = pts[:, 0] * c + pts[:, 1] * s
                    v = -pts[:, 0] * s + pts[:, 1] * c
                    h, nx, ny = grid_dims((u.min(), v.min(), u.max(), v.max()), ps)
                    turn = f", turned {math.degrees(theta):.1f}°" if theta else ""
                    self.lbl_grid.setText(
                        f"Point spacing ≈ {fmt_len(sp)} · quad grid {nx} × {ny} "
                        f"cells, {fmt_len(h)}{turn} · ≤ {nx * ny:,} quads")
                else:
                    self.lbl_grid.setText(
                        f"Typical point spacing ≈ {fmt_len(sp)} · ≈ "
                        f"{estimate_point_triangles(len(pts)):,} triangles")

        def _read_selection(self):
            nodes = [n for n in rt.selection if n not in self.preview]
            if self.mode == "contours":
                segs, _names = gather_contours(nodes)
                if not segs:
                    self._status("warn", "The selection holds no splines — "
                                 "select the contour lines.")
                    return
                self.data = {"mode": "contours",
                             "cset": ContourSet.from_segs(segs)}
            else:
                pts, _k = gather_points(nodes)
                if len(pts) < 3:
                    self._status("warn", "Select at least three points.")
                    return
                self.data = {"mode": "points", "points": pts}
            self._update_source()
            self._schedule()

        def _poll_selection(self):
            if not self.chk_follow.isChecked() or self._busy:
                return
            try:
                hs = tuple(sorted(int(rt.getHandleByAnim(n)) for n in rt.selection
                                  if n not in self.preview))
            except Exception:  # noqa: BLE001
                return
            if hs != self._last_sel:
                first = self._last_sel is None
                self._last_sel = hs
                if not first and hs:
                    self._read_selection()

        # ---------------- compute ----------------
        def _changed(self, *_):
            self._enable()
            self._update_source()
            self._schedule()

        def _schedule(self):
            self.result = None
            if self.btn_pv.isChecked():
                self._timer.start()
            else:
                self._status("off", "Live Preview is off — OK builds the terrain.")

        def _key(self, p):
            return json.dumps(p, sort_keys=True)

        def _recompute(self):
            if self._busy:
                return
            self._busy = True
            try:
                self._drop_preview()
                p = self._read_ui()
                ps = solver_params(p)
                try:
                    res = compute(self.data, ps)
                except TopoError as e:
                    self._status("err", str(e))
                    return
                except Exception as e:  # noqa: BLE001
                    self._status("err", f"Preview failed: {e}")
                    return
                self.result = (res, self._key(p))
                with pymxs.undo(False):
                    node, kids, A, failed = build_node(
                        res, ps, self.data, None, "Terrain (preview)")
                    self.preview = [node] + kids
                if self._frame:
                    self._frame = False
                    _zoom_to(node)
                rt.redrawViews()
                n = A["nfaces"]
                msg = (f"● LIVE PREVIEW — {n:,} {A['unit']} "
                       f"({res['seconds']:.1f} s) · steepest "
                       f"{slope_text(slope_max(res))} · changes apply instantly")
                if failed:
                    msg += f"\n{failed} bottom polygon(s) could not be closed"
                kind = "warn" if (len(res["T"]) > WARN_TRIANGLES or failed) else "ok"
                self._status(kind, msg)
            finally:
                self._busy = False

        def _drop_preview(self):
            if self.preview:
                with pymxs.undo(False):
                    for n in self.preview:
                        if not rt.isDeleted(n):
                            rt.delete(n)
                self.preview = []
                rt.redrawViews()

        def _toggle_preview(self, on):
            self._style_pv()
            if on:
                self._schedule()
            else:
                self._timer.stop()
                self._drop_preview()
                self.result = None
                self._status("off", "Live Preview is off — OK builds the terrain.")

        def _reset(self):
            self.params = default_params()
            self._load_ui()
            self._changed()

        # ---------------- finish ----------------
        def _ok(self):
            self._timer.stop()
            p = self._read_ui()
            ps = solver_params(p)
            try:
                if self.result is not None and self.result[1] == self._key(p):
                    res = self.result[0]
                else:
                    res = compute(self.data, ps)
            except TopoError as e:
                if "limit" in str(e):
                    r = QMessageBox.question(
                        self, TITLE, str(e) + "\n\nBuild anyway — at my own "
                        "risk? (Save your scene first.)")
                    if r == QMessageBox.Yes:
                        self.params = dict(p, force=True)
                        return self._ok()
                self._status("err", str(e))
                return
            self._drop_preview()
            old = self.old
            if old is not None and not rt.isDeleted(old):
                _set_hidden(old, False)
            commit(res, self.data, p, ps, old=old)
            self.old = None
            save_params(p)
            self.accept()

        def done(self, r):
            self._timer.stop()
            self._poll.stop()
            self._drop_preview()
            if self.old is not None and not rt.isDeleted(self.old):
                _set_hidden(self.old, False)
                rt.redrawViews()
            global _DLG
            _DLG = None
            super().done(r)

    return TopologyDialog


_DLG = None


def _max_main_window():
    try:
        import qtmax
        return qtmax.GetQMaxMainWindow()
    except Exception:  # noqa: BLE001
        return None


def _message(text):
    from PySide6.QtWidgets import QMessageBox
    QMessageBox.information(_max_main_window(), TITLE, text)


def _open(data, old=None):
    global _DLG
    if _DLG is not None:
        try:
            _DLG.close()
        except Exception:  # noqa: BLE001
            pass
    cls = _make_dialog_class()
    _DLG = cls(data, old, _max_main_window())
    _DLG.show()
    _DLG.raise_()
    return _DLG


def _numpy_ok():
    """numpy needed; offers the one-click install (shared with Grading)."""
    try:
        import numpy  # noqa: F401
        return True
    except ImportError:
        pass
    try:
        import pesi_grading
        return pesi_grading._numpy_ok()
    except ImportError:
        _message("Topology needs numpy in the 3ds Max Python.\n\n"
                 "In the 3ds Max Python folder run:\n"
                 "  python.exe -m ensurepip --upgrade --user\n"
                 "  python.exe -m pip install --user numpy scipy")
        return False


def show_contours():
    """Terrain from Contours… — selected splines."""
    if not _numpy_ok():
        return None
    segs, _n = gather_contours()
    if not segs:
        _message("Select the contour lines (splines at their altitudes), "
                 "then run Terrain from Contours.")
        return None
    return _open({"mode": "contours", "cset": ContourSet.from_segs(segs)})


def show_points():
    """Terrain from Points… — Point helpers, mesh vertices, spline knots."""
    if not _numpy_ok():
        return None
    pts, _k = gather_points()
    if len(pts) < 3:
        _message("Select at least three points: Point helpers, mesh/poly "
                 "objects (their vertices) or splines (their knots).")
        return None
    return _open({"mode": "points", "points": pts})


def show_edit():
    """Edit Terrain… — one selected terrain made by Topology."""
    if not _numpy_ok():
        return None
    node = selected_terrain()
    if node is None:
        _message("Select one terrain made by Topology, then run Edit Terrain.")
        return None
    return _open(data_from_record(terrain_record(node)), node)
