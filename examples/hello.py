"""Hello - the template plugin (not shipped, not loaded).

Puts a box on top of every selected object (or one at the origin if nothing
is selected) and shows the PESI3D preview dialog. To start a new plugin, copy
this file to Contents/python/pesi3d_max/plugins/<name>.py and rename it; to
try it as it is, copy it there as hello.py and restart 3ds Max.
"""

from pymxs import runtime as rt
from PySide6 import QtWidgets

from .. import preview

NAME = "Hello"


def setup(app):
    app.add_action("box", "Hello Box...", lambda: preview.show(HelloBoxDialog),
                   tooltip="Put a box on top of the selected objects (template plugin)")


class HelloBoxDialog(preview.PreviewDialog):
    TITLE = "Hello Box"
    UNDO_LABEL = "Hello Box"
    DEFAULT_SIZE = 20.0
    DEFAULT_HEIGHT = 10.0

    def build_controls(self, form):
        self.size = QtWidgets.QDoubleSpinBox(decimals=2, minimum=0.01, maximum=1e6)
        self.height_ = QtWidgets.QDoubleSpinBox(decimals=2, minimum=0.01, maximum=1e6)
        for spin in (self.size, self.height_):
            spin.valueChanged.connect(self.changed)
        form.addRow("Size", self.size)
        form.addRow("Height", self.height_)
        self.reset_controls()

    def reset_controls(self):
        self.size.setValue(self.DEFAULT_SIZE)
        self.height_.setValue(self.DEFAULT_HEIGHT)

    def build(self, targets):
        size, height = self.size.value(), self.height_.value()
        spots = []
        for node in targets:
            lo, hi = node.min, node.max
            spots.append(rt.Point3((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, hi.z))
        if not spots:
            spots.append(rt.Point3(0, 0, 0))
        nodes = []
        for pos in spots:
            box = rt.Box(length=size, width=size, height=height, pos=pos)
            box.name = rt.uniqueName("HelloBox")
            box.wirecolor = rt.Color(*preview.ACCENT)
            nodes.append(box)
        return nodes
