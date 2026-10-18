"""Topology - terrain from contour splines or from points.

The terrain code and its dialog live in terrain.py (the former stand-alone
pesi_topology.py 1.0). The MacroScript names stay Topology_Contours /
Topology_Points / Topology_Edit, so existing hotkeys and toolbar buttons keep
working.
"""

NAME = "Topology"


def setup(app):
    from . import terrain

    app.add_action("contours", "Terrain from Contours…", terrain.show_contours,
                   tooltip="Topology — terrain from the selected contour splines",
                   macro="Topology_Contours", icon="PESI3D\\Topology_Contours")
    app.add_action("points", "Terrain from Points…", terrain.show_points,
                   tooltip="Topology — terrain through Point helpers, mesh vertices or spline knots",
                   macro="Topology_Points", icon="PESI3D\\Topology_Points")
    app.add_action("edit", "Edit Terrain…", terrain.show_edit,
                   tooltip="Topology — change the selected terrain made by Topology",
                   macro="Topology_Edit", icon="PESI3D\\Topology_Edit")
