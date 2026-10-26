r"""Smoothing-group audit for Topology - run INSIDE 3ds Max:
    python.ExecuteFile @"D:\PROJEKTE\3DSMAX\pesi3d-max\tools\audit_smoothing.py"

Builds a terrain for every source (contours, point cloud, the example site
plan) and option (triangles / quads whole, snap, cut; skirt, bottom; outline
/ rectangle; smooth shading on/off), checks every edge and deletes it again.
Result as JSON in the MAXScript global pesi3d_audit. A finding is an edge
smoothed over a fold > 45 deg, or a hard edge < 20 deg between two smoothed
top faces.
"""
import itertools
import json
import math

import numpy as np
import pymxs
from pymxs import runtime as rt

from pesi3d_max.plugins.topology import plan, survey_pdf
from pesi3d_max.plugins.topology import terrain as T

PDF = r"D:\PROJEKTE\INGETRAZO\ingetrazo-topology\examples\site_plan_spot_heights_1-200_A3.pdf"
f = T.units_per_metre()


def sources():
    segs = []
    for k, r in enumerate((50.0, 35.0, 20.0, 8.0)):
        for i in range(48):
            a0, a1 = 2 * math.pi * i / 48, 2 * math.pi * (i + 1) / 48
            segs.append(tuple(v * f for v in (r * math.cos(a0), r * math.sin(a0), 5.0 * k,
                                              r * math.cos(a1), r * math.sin(a1), 5.0 * k)))
    rng = np.random.default_rng(7)
    ang = rng.uniform(0, 2 * math.pi, 400)
    rad = 30 * np.sqrt(rng.uniform(0, 1, 400))
    x, y = rad * np.cos(ang) * 1.6, rad * np.sin(ang)
    cloud = [(a * f, b * f, (0.02 * (a * a + b * b)) * f) for a, b in zip(x, y)]
    d = survey_pdf.read_pdf(PDF, 0)
    pts, _o = plan.survey_to_local(plan.survey_from_pdf(d["recs"], d["scale"]))
    pts = [(a * f, b * f, c * f) for a, b, c in T.dedupe_points(pts)]
    return {"contours": lambda: {"mode": "contours", "cset": T.ContourSet.from_segs(segs)},
            "cloud": lambda: {"mode": "points", "points": cloud},
            "plan": lambda: {"mode": "points", "points": pts}}


def audit(node, soft):
    nf = rt.polyop.getNumFaces(node)
    N = np.array([[float(c) for c in (lambda v: (v.x, v.y, v.z))(rt.polyop.getFaceNormal(node, i))]
                  for i in range(1, nf + 1)])
    G = np.array([int(rt.polyop.getFaceSmoothGroup(node, i)) for i in range(1, nf + 1)])
    kind = np.where(N[:, 2] > 0.3, "top", np.where(N[:, 2] < -0.9, "bottom", "skirt"))
    bad_smooth, bad_hard, pairs = [], [], {}
    for e in range(1, rt.polyop.getNumEdges(node) + 1):
        fs = [int(x) - 1 for x in rt.polyop.getEdgeFaces(node, e)]
        if len(fs) != 2:
            continue
        a, b = fs
        cosang = float(np.clip(N[a] @ N[b], -1, 1))
        deg = math.degrees(math.acos(cosang))
        share = bool(G[a] & G[b])
        key = "-".join(sorted((kind[a], kind[b])))
        pairs.setdefault(key, [0, 0])[0 if share else 1] += 1
        if share and deg > 45:
            bad_smooth.append((key, round(deg, 1)))
        if soft and not share and kind[a] == kind[b] == "top" and deg < 20 and G[a] and G[b]:
            bad_hard.append((key, round(deg, 1)))       # hard between two smoothed faces
    groups = {k: sorted({int(g) for g in G[kind == k]}) for k in ("top", "skirt", "bottom")}
    return {"faces": nf, "groups(bits)": groups, "edge pairs [smooth, hard]": pairs,
            "smoothed over > 45 deg": len(bad_smooth), "worst": sorted(bad_smooth, key=lambda t: -t[1])[:3],
            "hard inside the top": len(bad_hard)}


def run():
    out = []
    srcs = sources()
    variants = [("tri", {"quads": False}), ("whole", {"quads": True, "quad_rim": "whole"}),
                ("snap", {"quads": True, "quad_rim": "snap"}), ("cut", {"quads": True, "quad_rim": "cut"})]
    skirts = [("no skirt", {"skirt": False}), ("skirt", {"skirt": True, "bottom": False}),
              ("skirt+bottom", {"skirt": True, "bottom": True}),
              ("depth0+bottom", {"skirt": True, "bottom": True, "skirt_depth": 0.0})]
    for (sname, mk), (vname, vp), (kname, kp), boundary, soft in itertools.product(
            srcs.items(), variants, skirts, ("hull", "box"), (True, False)):
        if vname == "cut" and sname != "contours":
            continue
        if not soft and (kname != "skirt+bottom" or boundary != "hull"):
            continue
        p = T.normalize_params(dict({"cells": 25, "peaks": "flat", "contours": False, "map": False,
                                     "boundary": boundary, "soft": soft}, **vp, **kp))
        ps = T.solver_params(p)
        data = mk()
        try:
            res = T.compute(data, ps)
            with pymxs.undo(False):
                node, kids, A, failed = T.build_node(res, ps, data, None, "SG audit")
                r = audit(node, soft)
                r["bottom polys failed"] = failed
                for k in [node] + list(kids):
                    rt.delete(k)
        except Exception as exc:  # noqa: BLE001
            r = {"error": repr(exc)}
        r["case"] = f"{sname} | {vname} | {kname} | {boundary} | soft={soft}"
        out.append(r)
    return out


rt.pesi3d_audit = json.dumps(run())
