"""The PESI3D live-preview dialog (same look and behaviour as the IngeTrazo plugins).

Non-modal, the viewport stays usable. The objects selected on opening are the
targets; with "Follow selection" the targets follow the scene selection.
Bottom row: green checkable "Live Preview ON" + "Reset" on the left,
"OK" / "Cancel" on the right, a status banner above (live / busy / paused / error).

The preview is the real result in the scene, built with undo switched off and
removed again before every rebuild. OK removes it and builds once more inside
ONE undo record; Cancel (or closing the window) just removes it.

A subclass implements:
    TITLE, UNDO_LABEL
    build_controls(form)   add widgets to the QFormLayout, call self.changed()
                           whenever a value changes
    reset_controls()       put the widgets back to their defaults
    build(targets)         create the result; return the NEW nodes it made
and, only if it edits existing objects instead of creating new ones,
    revert()               undo what build() did (default: delete its nodes)
"""

import traceback

import pymxs
from pymxs import runtime as rt
from PySide6 import QtCore, QtGui, QtWidgets

from .log import get_logger

log = get_logger("preview")

ACCENT = (243, 115, 41)
_BANNER = {
    "live": ("#1f5f33", "Live preview - the result is shown in the scene"),
    "busy": ("#6b5a1e", "Updating..."),
    "paused": ("#4a4a4a", "Preview paused - OK builds the result"),
    "error": ("#7a2020", "Error"),
}
_open = {}  # dialog class -> instance (keeps it alive, one per tool)


def show(dialog_cls):
    """Open a dialog or bring the already open one to the front."""
    dlg = _open.get(dialog_cls)
    if dlg is not None:
        try:
            dlg.raise_()
            dlg.activateWindow()
            return dlg
        except RuntimeError:  # Qt object already gone
            _open.pop(dialog_cls, None)
    dlg = dialog_cls()
    _open[dialog_cls] = dlg
    dlg.show()
    return dlg


def max_main_window():
    try:
        from qtmax import GetQMaxMainWindow
        return GetQMaxMainWindow()
    except ImportError:
        return None


class PreviewDialog(QtWidgets.QDialog):
    TITLE = "PESI3D"
    UNDO_LABEL = "PESI3D"

    def __init__(self):
        super().__init__(max_main_window())
        self.setWindowTitle(self.TITLE)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.Tool)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)

        self.targets = [n for n in rt.selection]
        self._nodes = []          # preview nodes currently in the scene
        self._busy = False
        self._done = False
        self._cb_id = rt.Name("pesi3d_preview_%d" % id(self))

        self._timer = QtCore.QTimer(self, singleShot=True, interval=120)
        self._timer.timeout.connect(self._rebuild)

        lay = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        lay.addLayout(form)
        self.build_controls(form)

        self.follow = QtWidgets.QCheckBox("Follow selection")
        self.follow.toggled.connect(self._on_follow)
        lay.addWidget(self.follow)

        self.banner = QtWidgets.QLabel()
        self.banner.setWordWrap(True)
        self.banner.setContentsMargins(8, 4, 8, 4)
        lay.addWidget(self.banner)

        row = QtWidgets.QHBoxLayout()
        self.live = QtWidgets.QPushButton()
        self.live.setCheckable(True)
        self.live.setChecked(True)
        self.live.toggled.connect(self._on_live)
        reset = QtWidgets.QPushButton("Reset")
        reset.clicked.connect(self._on_reset)
        ok = QtWidgets.QPushButton("OK")
        ok.setDefault(True)
        ok.clicked.connect(self._on_ok)
        cancel = QtWidgets.QPushButton("Cancel")
        cancel.clicked.connect(self.close)
        row.addWidget(self.live)
        row.addWidget(reset)
        row.addStretch(1)
        row.addWidget(ok)
        row.addWidget(cancel)
        lay.addLayout(row)

        self._style_live()
        rt.callbacks.addScript(rt.Name("selectionSetChanged"), self._on_selection, id=self._cb_id)
        for event in ("systemPreReset", "systemPreNew", "filePreOpen"):
            rt.callbacks.addScript(rt.Name(event), self._on_scene_gone, id=self._cb_id)
        self.changed()

    # --- subclass API -------------------------------------------------------
    def build_controls(self, form):
        pass

    def reset_controls(self):
        pass

    def build(self, targets):
        return []

    def revert(self):
        for node in self._nodes:
            if rt.isValidNode(node):
                rt.delete(node)

    def changed(self):
        """Call on every value change: rebuilds the preview shortly after."""
        live = getattr(self, "live", None)   # None while build_controls() runs
        if live is not None and live.isChecked():
            self._timer.start()

    # --- preview ------------------------------------------------------------
    def _clear(self):
        with pymxs.undo(False):
            self.revert()
        self._nodes = []

    def _rebuild(self):
        if self._busy or self._done:
            return
        self._busy = True
        self._set_banner("busy")
        QtWidgets.QApplication.processEvents()
        try:
            self._clear()
            self.targets = [n for n in self.targets if rt.isValidNode(n)]
            with pymxs.undo(False):
                self._nodes = list(self.build(self.targets) or [])
            self._set_banner("live")
        except Exception as exc:
            log.error("%s preview failed:\n%s", self.TITLE, traceback.format_exc())
            self._set_banner("error", "Error: %s" % exc)
        finally:
            self._busy = False
            rt.redrawViews()

    def _set_banner(self, state, text=None):
        color, default = _BANNER[state]
        self.banner.setText(text or default)
        self.banner.setStyleSheet("background:%s; color:white; border-radius:3px;" % color)

    def _style_live(self):
        on = self.live.isChecked()
        self.live.setText("● Live Preview ON" if on else "○ Live Preview OFF")
        if self.live.styleSheet():
            return
        # explicit :checked rule - the 3ds Max style would paint it light blue
        self.live.setStyleSheet(
            "QPushButton:checked { background:#2e7d32; color:white; font-weight:bold;"
            " border:1px solid #1f5f33; border-radius:3px; padding:3px 8px; }")
        bold = QtGui.QFont(self.live.font())
        bold.setBold(True)
        metrics = QtGui.QFontMetrics(bold)
        self.live.setMinimumWidth(24 + max(
            metrics.horizontalAdvance(t) for t in ("● Live Preview ON", "○ Live Preview OFF")))

    # --- events -------------------------------------------------------------
    def _on_live(self, on):
        self._style_live()
        if on:
            self._rebuild()
        else:
            self._timer.stop()
            self._clear()
            self._set_banner("paused")
            rt.redrawViews()

    def _on_reset(self):
        self.reset_controls()
        self.changed()

    def _on_follow(self, on):
        if on:
            self._on_selection()

    def _on_selection(self):
        if self._busy or self._done or not self.follow.isChecked():
            return
        own = {rt.getHandleByAnim(n) for n in self._nodes if rt.isValidNode(n)}
        self.targets = [n for n in rt.selection if rt.getHandleByAnim(n) not in own]
        self.changed()

    def _on_scene_gone(self):
        self._nodes = []           # the scene is being thrown away anyway
        self._done = True
        self.close()

    def _on_ok(self):
        self._timer.stop()
        try:
            self._clear()
            self.targets = [n for n in self.targets if rt.isValidNode(n)]
            with pymxs.undo(True, self.UNDO_LABEL):
                nodes = list(self.build(self.targets) or [])
            if nodes:
                rt.select(nodes)
        except Exception as exc:
            log.error("%s failed:\n%s", self.TITLE, traceback.format_exc())
            self._set_banner("error", "Error: %s" % exc)
            return
        self._done = True
        rt.redrawViews()
        self.close()

    def closeEvent(self, event):
        self._timer.stop()
        rt.callbacks.removeScripts(id=self._cb_id)
        if not self._done:
            self._clear()
            rt.redrawViews()
        self._done = True
        _open.pop(type(self), None)
        super().closeEvent(event)
