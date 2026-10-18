# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Pesi (pesi3d.de)
"""Topology - Terrain from Plan: spot heights read from a site plan (PDF).

survey_pdf finds the height texts and their point symbols on the sheet;
here they become point records (metres via the plan scale), get checked,
and the dialog lets the user correct them before the terrain is built.

The functions below are copied unchanged from the IngeTrazo plugin
Topology 1.2 (topology_tool/__init__.py, "Terrain from Plan"); keep them in
sync. pdf_vectors.py, survey_pdf.py, page_view.py and _vendor/pypdf are
copied unchanged from there too.
"""
from __future__ import annotations

from .terrain import TITLE, VERSION, dedupe_points


def _survey_checks(recs):
    """Switch off suspicious points and write the reason into ``note``."""
    good = [r for r in recs if r["use"]]
    if not good:
        return
    hs = sorted(r["h"] for r in good)
    med = hs[len(hs) // 2]
    mad = sorted(abs(h - med) for h in hs)[len(hs) // 2] or 0.1
    lim = max(15 * mad, 25.0)
    seen_xy = {}
    for r in recs:
        if not r["use"]:
            continue
        notes = []
        if abs(r["h"]) < 1e-9 and abs(med) > 5:
            notes.append("height 0")
            r["use"] = False
            r["hard"] = True
        elif r["h"] <= -999 or r["h"] >= 9000:
            notes.append("no height")
            r["use"] = False
            r["hard"] = True
        elif abs(r["h"] - med) > lim:
            notes.append("height far off")
            r["use"] = False
            r["hard"] = True
        k = (round(r["e"], 2), round(r["n"], 2))
        if k in seen_xy and r["use"]:
            o = recs[seen_xy[k]]
            if r["h"] > o["h"] + 0.05:
                # same spot, higher: a roof / top point over a ground point
                notes.append(f"same spot as row {o['row'] + 1}, higher")
                r["use"] = False
                r["hard"] = True
            elif o["h"] > r["h"] + 0.05:
                o["use"] = False
                o["hard"] = True
                o["note"] = ", ".join(x for x in (
                    o["note"], f"same spot as row {r['row'] + 1}, higher") if x)
                seen_xy[k] = r["row"]
            else:
                notes.append(f"duplicate of row {o['row'] + 1}")
                r["use"] = False
                r["hard"] = True
        elif r["use"]:
            seen_xy[k] = r["row"]
        r["note"] = ", ".join(x for x in (r["note"], *notes) if x)


def survey_codes(recs):
    """Code → (count, used count), sorted by count."""
    out = {}
    for r in recs:
        c = r["code"] or "(none)"
        n, u = out.get(c, (0, 0))
        out[c] = (n + 1, u + (1 if r["use"] else 0))
    return dict(sorted(out.items(), key=lambda kv: -kv[1][0]))


def survey_to_local(recs, origin="min", keep_height=False):
    """Used records → local points ``[(x, y, z)]`` and the offset
    ``(e0, n0, h0)`` that was subtracted. origin: "min" (south-west corner
    of the points, lowest point at z 0) or a tuple (e0, n0, h0)."""
    use = [r for r in recs if r["use"]]
    if isinstance(origin, tuple):
        e0, n0, h0 = origin
    else:
        e0 = min(r["e"] for r in use)
        n0 = min(r["n"] for r in use)
        h0 = min(r["h"] for r in use)
    if keep_height:
        h0 = 0.0
    pts = [(r["e"] - e0, r["n"] - n0, r["h"] - h0) for r in use]
    return pts, (e0, n0, h0)


def survey_from_pdf(precs, scale):
    """Spot heights read from a plan (paper points, see survey_pdf) →
    survey records in metres. ``scale`` = the plan scale number (200 for
    1:200)."""
    from .survey_pdf import NOT_GROUND_CODES, PT_TO_MM
    k = PT_TO_MM / 1000.0 * float(scale)
    ng = {c.upper() for c in NOT_GROUND_CODES}
    recs = []
    for i, p in enumerate(sorted(precs, key=lambda q: (-q["py"], q["px"]))):
        r = {"row": i, "no": str(i + 1), "e": p["px"] * k, "n": p["py"] * k,
             "h": p["value"], "code": p["code"], "use": True, "note": "",
             "hard": False, "code_off": False, "manual": None,
             "label": p["label"], "px": p["px"], "py": p["py"],
             "symbol": p["symbol"]}
        if p["code"].upper() in ng:
            r["code_off"] = True
            r["use"] = False
            r["note"] = ("floor level — not the ground"
                         if p["code"] == "Floor level" else
                         f"«{p['code']}» — not the ground?")
        if not p["symbol"]:
            r["note"] = ", ".join(x for x in (
                r["note"], "no point symbol found — text position used") if x)
        recs.append(r)
    _survey_checks(recs)
    return recs


def survey_rescale(recs, scale):
    from .survey_pdf import PT_TO_MM
    k = PT_TO_MM / 1000.0 * float(scale)
    for r in recs:
        if "px" in r:
            r["e"], r["n"] = r["px"] * k, r["py"] * k


def survey_apply(recs, codes_on):
    """Recompute ``use`` from the checks, the codes switched on and the
    user's own ticks (``manual`` wins)."""
    for r in recs:
        if r["manual"] is not None:
            r["use"] = bool(r["manual"])
        else:
            r["use"] = (not r["hard"]) and codes_on.get(r["code"] or "(none)", True)
    return sum(1 for r in recs if r["use"])


_SURVEY = None
_SURVEY_OPEN = None
SURVEY_DIR_KEY = "plan_dir"


def _make_survey_view_class():
    """The sheet (Plan Import's page view) with the found points on it:
    green = used, orange = left out; a click selects the point."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QPainter, QPen
    from .page_view import make_page_view_class

    Base = make_page_view_class()

    class SurveyView(Base):
        def __init__(self, parent=None):
            super().__init__(parent)
            self._marks = []          # [(x_pt, y_pt, used, label)]
            self._sel = -1
            self.on_pick = None

        def set_marks(self, marks, sel=-1):
            self._marks = list(marks)
            self._sel = sel
            self.update()

        def set_selected(self, i):
            self._sel = i
            self.update()

        def paintEvent(self, ev):
            super().paintEvent(ev)
            if self._img is None or self._page is None or not self._marks:
                return
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            green, orange = QColor(40, 170, 70), QColor(240, 140, 30)
            for i, (x, y, used, _lab) in enumerate(self._marks):
                c = self._to_screen(x, y)
                col = green if used else orange
                p.setPen(QPen(QColor(255, 255, 255), 1.5))
                p.setBrush(col if used else Qt.BrushStyle.NoBrush)
                if not used:
                    p.setPen(QPen(col, 2.5))
                p.drawEllipse(c, 5.5, 5.5)
            if 0 <= self._sel < len(self._marks):
                x, y, used, lab = self._marks[self._sel]
                c = self._to_screen(x, y)
                p.setPen(QPen(QColor(40, 110, 230), 3))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(c, 11, 11)
                if lab:
                    r = p.fontMetrics().boundingRect(lab)
                    box = QRectF(c.x() + 14, c.y() - 10 - r.height(),
                                 r.width() + 10, r.height() + 6)
                    p.fillRect(box, QColor(40, 110, 230))
                    p.setPen(QColor(255, 255, 255))
                    p.drawText(box, Qt.AlignmentFlag.AlignCenter, lab)
            p.end()

        def mouseReleaseEvent(self, ev):
            drag = self._drag
            busy = self.measuring() or self.drawing_rect()
            super().mouseReleaseEvent(ev)
            if busy or (drag is not None and drag[2]) or self.on_pick is None:
                return
            if ev.button() != Qt.MouseButton.LeftButton or self._img is None:
                return
            pos = ev.position()
            best, bd = -1, 14.0
            for i, (x, y, _u, _l) in enumerate(self._marks):
                c = self._to_screen(x, y)
                d = ((c.x() - pos.x()) ** 2 + (c.y() - pos.y()) ** 2) ** 0.5
                if d < bd:
                    best, bd = i, d
            if best >= 0:
                self.on_pick(best)

    return SurveyView


def _make_survey_class():
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QBrush, QColor
    from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox,
                                   QDialog, QDoubleSpinBox,
                                   QGroupBox, QHBoxLayout, QHeaderView,
                                   QInputDialog, QLabel, QListWidget,
                                   QListWidgetItem, QPushButton,
                                   QSplitter, QTableWidget,
                                   QTableWidgetItem, QVBoxLayout, QWidget)
    SurveyView = _make_survey_view_class()

    MAX_ROWS = 20000          # rows shown in the table (all are imported)

    class SurveyDialog(QDialog):
        """Step 1 of «Terrain from Plan»: read the spot heights of a plan
        (PDF), show them on the sheet and in a table (codes, suspicious
        ones in orange) and let the user correct them and the scale.
        «Build Terrain ▸» hands the points to the Terrain from Points
        dialog with its live preview."""

        def __init__(self, path, parent=None):
            super().__init__(parent)
            self.path = path
            self.recs = []
            self.info = {}
            self.codes_on = {}
            self._busy = False
            self.pdf = None            # PDF mode: what survey_pdf read
            self.scale = None
            self._notes = []
            self._found_bits = []
            self.setWindowTitle(f"{TITLE} {VERSION} — Terrain from Plan")
            self.setModal(False)
            self.setAttribute(Qt.WA_DeleteOnClose, True)
            self._build_ui()
            self.resize(860, 640)
            self.load(path)

        # ---- UI ------------------------------------------------------------
        def _build_ui(self):
            lay = QVBoxLayout(self)
            top = QHBoxLayout()
            self.l_file = QLabel(self)
            self.l_file.setTextInteractionFlags(Qt.TextSelectableByMouse)
            b_open = QPushButton("Open…", self)
            b_open.clicked.connect(self._open_other)
            top.addWidget(self.l_file, 1)
            top.addWidget(b_open)
            lay.addLayout(top)
            self.l_found = QLabel(self)
            self.l_found.setWordWrap(True)
            lay.addWidget(self.l_found)

            # plan scale (PDF)
            gs = QGroupBox("Plan", self)
            self.g_scale = gs
            sl = QHBoxLayout(gs)
            self.c_sheet = QComboBox(gs)
            self.c_sheet.currentIndexChanged.connect(self._sheet_changed)
            self.l_sheet = QLabel("Sheet:", gs)
            sl.addWidget(self.l_sheet)
            sl.addWidget(self.c_sheet)
            sl.addSpacing(12)
            sl.addWidget(QLabel("Scale  1 :", gs))
            self.s_scale = QDoubleSpinBox(gs)
            self.s_scale.setRange(1.0, 100000.0)
            self.s_scale.setDecimals(1)
            self.s_scale.setValue(200.0)
            self.s_scale.setKeyboardTracking(False)
            self.s_scale.valueChanged.connect(self._scale_changed)
            sl.addWidget(self.s_scale)
            self.l_scale = QLabel(gs)
            sl.addWidget(self.l_scale, 1)
            self.b_measure = QPushButton("Measure scale…", gs)
            self.b_measure.setToolTip(
                "Click two points on the sheet whose real distance you know "
                "and type that distance.")
            self.b_measure.clicked.connect(self._measure)
            sl.addWidget(self.b_measure)
            lay.addWidget(gs)

            # table | codes
            self.c_notes = QCheckBox("Show only points with a note", self)
            self.c_notes.toggled.connect(self._filter_rows)
            lay.addWidget(self.c_notes)
            split = QSplitter(Qt.Horizontal, self)
            self.table = QTableWidget(0, 7, split)
            self.table.setHorizontalHeaderLabels(
                ["Use", "Point / text", "Easting", "Northing", "Height",
                 "Code", "Note"])
            self.table.verticalHeader().setVisible(False)
            self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            hh = self.table.horizontalHeader()
            for c in range(6):
                hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
            hh.setSectionResizeMode(6, QHeaderView.Stretch)
            self.table.itemChanged.connect(self._item_changed)
            cw = QWidget(split)
            cl = QVBoxLayout(cw)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.addWidget(QLabel("Codes (untick = leave out):", cw))
            self.codes = QListWidget(cw)
            self.codes.itemChanged.connect(self._code_changed)
            cl.addWidget(self.codes, 1)
            self.view = SurveyView(split)
            self.view.on_pick = self._picked
            split.insertWidget(0, self.view)
            split.addWidget(self.table)
            split.addWidget(cw)
            split.setStretchFactor(0, 5)
            split.setStretchFactor(1, 4)
            split.setStretchFactor(2, 1)
            self.split = split
            self.table.itemSelectionChanged.connect(self._row_selected)
            lay.addWidget(split, 1)

            # placement
            gp = QGroupBox("Placement", self)
            pl = QVBoxLayout(gp)
            self.r_origin = QLabel(
                "The south-west corner of the heights goes to x 0 / y 0, "
                "the lowest height to z 0.", gp)
            self.c_real = QCheckBox("Keep real heights (z = height above "
                                    "sea level)", gp)
            pl.addWidget(self.r_origin)
            pl.addWidget(self.c_real)
            lay.addWidget(gp)

            self.banner = QLabel(self)
            self.banner.setWordWrap(True)
            lay.addWidget(self.banner)
            row = QHBoxLayout()
            row.addStretch(1)
            self.b_build = QPushButton("Build Terrain ▸", self)
            self.b_build.setDefault(True)
            self.b_build.clicked.connect(self._build)
            b_cancel = QPushButton("Cancel", self)
            b_cancel.clicked.connect(self.reject)
            row.addWidget(self.b_build)
            row.addWidget(b_cancel)
            lay.addLayout(row)

        def _banner(self, kind, text):
            # the colours of the terrain dialog's preview banner
            css = {"ok": "background: #1f5f33; color: #e8ffe9;",
                   "warn": "background: #5c4a1a; color: #ffe9b8;",
                   "error": "background: #7a1f1f; color: #ffecec;"}[kind]
            self.banner.setText(text)
            self.banner.setStyleSheet(css + " padding: 6px 8px; border-radius: 3px;")

        # ---- file ------------------------------------------------------------
        def _open_other(self):
            p = survey_ask_file(self)
            if p:
                self.load(p)

        def load(self, path):
            import os
            self.path = path
            self.l_file.setText(f"<b>{os.path.basename(path)}</b> "
                                f"<span style='color:gray'>{os.path.dirname(path)}</span>")
            self.resize(max(self.width(), 1280), max(self.height(), 760))
            self._load_pdf(path, 0)

        # ---- PDF plans -----------------------------------------------------
        def _load_pdf(self, path, page):
            from PySide6.QtWidgets import QApplication
            from .survey_pdf import read_pdf
            self._banner("warn", "Reading the plan…")
            QApplication.processEvents()
            try:
                self.pdf = read_pdf(path, page)
            except Exception as exc:                       # noqa: BLE001
                self.pdf = None
                self.recs = []
                self.table.setRowCount(0)
                self.codes.clear()
                self.view.set_message("Could not read the PDF.")
                self._banner("error", f"Could not read the PDF: {exc}")
                self.b_build.setEnabled(False)
                return
            d = self.pdf
            self._busy = True
            if self.c_sheet.count() != d["pages"]:
                self.c_sheet.clear()
                for i in range(d["pages"]):
                    self.c_sheet.addItem(f"{i + 1} / {d['pages']}", i)
            self.c_sheet.setCurrentIndex(page)
            self.c_sheet.setVisible(d["pages"] > 1)
            self.l_sheet.setVisible(d["pages"] > 1)
            if d["scale"]:
                self.scale = float(d["scale"])
                self.s_scale.setValue(self.scale)
                self._scale_src = ("green", f"read from the plan: «1:{d['scale']}»")
            else:
                self.scale = float(self.s_scale.value())
                self._scale_src = ("orange", "not found on the plan — "
                                   "check it or use Measure scale")
            self._busy = False
            self._show_scale_src()
            from .page_view import page_points, render_page
            img = render_page(d["vec"], d["texts"])
            self.view.set_image(img, d["info"].get("name") or "",
                                page=(d["vec"].width, d["vec"].height))
            self._snap = page_points(d["vec"])
            n = len(d["recs"])
            nsym = sum(1 for r in d["recs"] if r["symbol"])
            self._found_bits = [f"{n} height texts on the sheet",
                                f"{nsym} with a point symbol",
                                "heights above sea level" if d["info"].get("absolute")
                                else "relative heights (±0.00 system)"]
            self._notes = []
            if n < 3:
                self.recs = []
                self.table.setRowCount(0)
                self.codes.clear()
                self.view.set_marks([])
                self._show_found()
                self._banner("error", "Fewer than three heights found on "
                             "this sheet — is it a vector PDF (not a scan)?")
                self.b_build.setEnabled(False)
                return
            self.recs = survey_from_pdf(d["recs"], self.scale)
            xs = [r["e"] for r in self.recs]
            ys = [r["n"] for r in self.recs]
            self.info = {"zone": None, "grid": "local",
                         "extent": (max(xs) - min(xs), max(ys) - min(ys))}
            self.codes_on = {}
            for r in self.recs:
                c = r["code"] or "(none)"
                self.codes_on[c] = self.codes_on.get(c, False) or not r["code_off"]
            survey_apply(self.recs, self.codes_on)
            self._fill_codes()
            self._busy = True
            self.c_notes.setChecked(False)
            self._busy = False
            self._fill_table()
            self._show_found()
            self._update_summary()

        def _show_scale_src(self):
            col, txt = self._scale_src
            c = {"green": "#2e9d4a", "orange": "#e8912d", "blue": "#3a7bd5"}[col]
            self.l_scale.setText(f"<span style='color:{c}'>{txt}</span>")

        def _sheet_changed(self, i):
            if self._busy or self.pdf is None or i < 0:
                return
            self._load_pdf(self.path, int(self.c_sheet.itemData(i)))

        def _scale_changed(self, v):
            if self._busy or self.pdf is None or not self.recs:
                return
            self.scale = float(v)
            if self._scale_src[0] != "blue" or abs(v - getattr(self, "_measured", -1)) > 0.05:
                self._scale_src = ("orange", "typed in")
            self._show_scale_src()
            survey_rescale(self.recs, self.scale)
            xs = [r["e"] for r in self.recs]
            ys = [r["n"] for r in self.recs]
            self.info["extent"] = (max(xs) - min(xs), max(ys) - min(ys))
            self._fill_table()
            self._update_summary()

        def _measure(self):
            if self.pdf is None:
                return

            def done(d_pt, _a, _b):
                from .survey_pdf import PT_TO_MM
                mm = d_pt * PT_TO_MM
                real, ok = QInputDialog.getDouble(
                    self, "Measure scale",
                    f"The two points are {mm:.1f} mm apart on paper.\n"
                    "Real distance between them (m):", 10.0, 0.001,
                    1_000_000.0, 3)
                if not ok or real <= 0:
                    return
                n = real * 1000.0 / mm
                self._measured = round(n, 1)
                self._scale_src = ("blue", f"measured: {mm:.1f} mm on paper = "
                                   f"{real:g} m")
                self.s_scale.setValue(self._measured)
                self._show_scale_src()

            self.view.start_measure(self._snap, done)

        def _marks(self):
            return [(r["px"], r["py"], r["use"],
                     f"{r.get('label') or r['h']}  ·  {r['code']}")
                    for r in self.recs if "px" in r]

        def _picked(self, i):
            if 0 <= i < self.table.rowCount():
                if self.table.isRowHidden(i):
                    self.c_notes.setChecked(False)
                self.table.selectRow(i)
                self.table.scrollToItem(self.table.item(i, 1))

        def _row_selected(self):
            rows = sorted({ix.row() for ix in self.table.selectedIndexes()})
            if self.pdf is not None:
                self.view.set_selected(rows[0] if rows else -1)

        def _show_found(self):
            bits = list(self._found_bits)
            txt = "Recognised: " + " · ".join(bits)
            if self._notes:
                txt += "<br><span style='color:#e8912d'>" + \
                    "<br>".join(self._notes) + "</span>"
            self.l_found.setText(txt)

        def _fill_codes(self):
            self._busy = True
            self.codes.clear()
            for c, (n, _u) in survey_codes(self.recs).items():
                it = QListWidgetItem(f"{c}  ({n})", self.codes)
                it.setData(Qt.UserRole, c)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked if self.codes_on.get(c, True)
                                 else Qt.Unchecked)
                if not self.codes_on.get(c, True):
                    it.setToolTip("Not the ground (floor level, pipe "
                                  "invert …) — left out. Tick to use.")
                    it.setForeground(QBrush(QColor("#e8912d")))
            self._busy = False

        def _fill_table(self):
            self._busy = True
            t = self.table
            t.setUpdatesEnabled(False)
            recs = self.recs[:MAX_ROWS]
            t.setRowCount(len(recs))
            orange = QBrush(QColor("#e8912d"))
            gray = QBrush(QColor(128, 128, 128))
            for i, r in enumerate(recs):
                it = QTableWidgetItem()
                it.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled |
                            Qt.ItemIsSelectable)
                it.setCheckState(Qt.Checked if r["use"] else Qt.Unchecked)
                t.setItem(i, 0, it)
                vals = [r.get("label") or r["no"],
                        "" if r["e"] is None else f"{r['e']:.3f}",
                        "" if r["n"] is None else f"{r['n']:.3f}",
                        "" if r["h"] is None else f"{r['h']:.3f}",
                        r["code"], r["note"]]
                for c, v in enumerate(vals, start=1):
                    cell = QTableWidgetItem(v)
                    if c in (2, 3, 4):
                        cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    if r["note"] and not r["use"]:
                        cell.setForeground(orange)
                    elif not r["use"]:
                        cell.setForeground(gray)
                    t.setItem(i, c, cell)
            t.setUpdatesEnabled(True)
            self._busy = False
            self._filter_rows()
            if self.pdf is not None:
                self.view.set_marks(self._marks(), self.view._sel)

        def _filter_rows(self, *_a):
            only = self.c_notes.isChecked()
            n = sum(1 for r in self.recs if r["note"])
            self.c_notes.setText(f"Show only points with a note ({n})")
            for i, r in enumerate(self.recs[:MAX_ROWS]):
                self.table.setRowHidden(i, only and not r["note"])

        def _restyle_row(self, i):
            r = self.recs[i]
            orange = QBrush(QColor("#e8912d"))
            gray = QBrush(QColor(128, 128, 128))
            normal = QBrush(self.palette().text().color())
            for c in range(1, 7):
                cell = self.table.item(i, c)
                if cell is None:
                    continue
                cell.setForeground(orange if (r["note"] and not r["use"])
                                   else gray if not r["use"] else normal)

        def _item_changed(self, item):
            if self._busy or item.column() != 0:
                return
            i = item.row()
            if not 0 <= i < len(self.recs):
                return
            self.recs[i]["manual"] = item.checkState() == Qt.Checked
            survey_apply(self.recs, self.codes_on)
            self._restyle_row(i)
            if self.pdf is not None:
                self.view.set_marks(self._marks(), self.view._sel)
            self._update_summary()

        def _code_changed(self, item):
            if self._busy:
                return
            c = item.data(Qt.UserRole)
            self.codes_on[c] = item.checkState() == Qt.Checked
            for r in self.recs:
                if (r["code"] or "(none)") == c:
                    r["manual"] = None
            survey_apply(self.recs, self.codes_on)
            self._fill_table()
            self._update_summary()

        def _update_summary(self, *_a):
            if not self.recs:
                return
            used = sum(1 for r in self.recs if r["use"])
            off = len(self.recs) - used
            ex = self.info.get("extent", (0, 0))
            if used < 3:
                self._banner("error", f"Only {used} points ticked — "
                             "a terrain needs at least three.")
                self.b_build.setEnabled(False)
                return
            txt = (f"<b>{used:,} of {len(self.recs):,} heights</b> go into "
                   f"the terrain · area {ex[0]:,.0f} × {ex[1]:,.0f} m")
            if off:
                txt += f" · {off} left out (orange — see Note)"
            if len(self.recs) > MAX_ROWS:
                txt += f" · table shows the first {MAX_ROWS:,} rows"
            if self._scale_src[0] == "orange":
                txt += " · <b>check the scale</b>"
            self._banner("warn" if self._scale_src[0] == "orange" else "ok", txt)
            self.b_build.setEnabled(True)

        # ---- hand over ---------------------------------------------------------
        def points(self):
            """Local points and a description of the placement."""
            pts, origin = survey_to_local(self.recs,
                                          keep_height=self.c_real.isChecked())
            return pts, origin, "origin"

        def _build(self):
            import os
            pts, origin, how = self.points()
            if len(pts) < 3:
                return
            pts = dedupe_points(pts)
            data = {"mode": "points", "points": pts,
                    "label": f"plan {os.path.basename(self.path)}",
                    "source": {"file": os.path.basename(self.path),
                               "placement": how,
                               "origin": list(origin) if origin else None,
                               "scale": self.scale}}
            # the plan is read in metres, the terrain works in system units
            from pymxs import runtime as rt
            from . import terrain
            f = terrain.units_per_metre()
            data["points"] = [(x * f, y * f, z * f) for x, y, z in pts]
            self.accept()
            terrain._open(data)
            if origin is not None:
                _e0, _n0, h0 = origin
                rt.pushPrompt(
                    f"{TITLE}: lowest height {h0:,.2f} m is at z 0." if h0 else
                    f"{TITLE}: heights kept above sea level.")

        def done(self, r):
            global _SURVEY_OPEN
            if _SURVEY_OPEN is self:
                _SURVEY_OPEN = None
            super().done(r)

    return SurveyDialog


def survey_ask_file(parent):
    from PySide6.QtWidgets import QFileDialog
    from .terrain import _qsettings
    st = _qsettings()
    start = str(st.value(SURVEY_DIR_KEY, "") or "")
    path, _ = QFileDialog.getOpenFileName(
        parent, f"{TITLE} — Open a plan with spot heights", start,
        "Plan with spot heights (*.pdf);;All files (*)")
    if path:
        import os
        st.setValue(SURVEY_DIR_KEY, os.path.dirname(path))
    return path


def show_plan(path=None):
    """PESI3D ▸ Topology ▸ Terrain from Plan…"""
    global _SURVEY, _SURVEY_OPEN
    from .terrain import _max_main_window, _numpy_ok
    if not _numpy_ok():
        return None
    parent = _max_main_window()
    if path is None:
        path = survey_ask_file(parent)
    if not path:
        return None
    if _SURVEY is None:
        _SURVEY = _make_survey_class()
    if _SURVEY_OPEN is not None:
        try:
            _SURVEY_OPEN.reject()
        except RuntimeError:
            pass
    dlg = _SURVEY(path, parent)
    _SURVEY_OPEN = dlg
    dlg.show()
    dlg.raise_()
    from PySide6.QtCore import QTimer
    QTimer.singleShot(0, dlg.view.fit)          # whole sheet once laid out
    return dlg
