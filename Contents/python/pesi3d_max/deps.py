"""Python packages the plugins need but 3ds Max does not ship (numpy).

    from pesi3d_max import deps
    if not deps.ensure(("numpy",), "Topology"):
        return

ensure() imports the packages; if one is missing it asks the user and installs
it with one click: the Python of 3ds Max runs

    python.exe -m ensurepip --upgrade --user
    python.exe -m pip install --user <packages>

in a QProcess with a small progress dialog (3ds Max stays responsive, no admin
rights needed, the packages land in %APPDATA%\\Python\\PythonXYZ). Afterwards
the user site is put on sys.path so the running session can import them; if
that still fails the user is told to restart 3ds Max.

The decision logic takes plain callables, so it is tested without 3ds Max/Qt
(tests/test_deps.py).
"""

import importlib
import os
import site
import sys

from .log import get_logger

log = get_logger("deps")


def add_user_site():
    """Put the pip --user folder on sys.path (3ds Max may start without it)."""
    try:
        us = site.getusersitepackages()
    except Exception:  # noqa: BLE001
        return None
    if us and us not in sys.path:
        sys.path.append(us)
    importlib.invalidate_caches()
    return us


def missing(packages, importer=importlib.import_module):
    """The packages that cannot be imported."""
    out = []
    for name in packages:
        try:
            importer(name)
        except ImportError:
            out.append(name)
    return out


def python_exe(executable=None, prefixes=None, isfile=os.path.isfile):
    """The python.exe of the running 3ds Max.

    In 3ds Max sys.executable is 3dsmax.exe; its Python lives in
    <3ds Max>\\Python\\python.exe (= sys.prefix). Outside Max sys.executable
    is python.exe itself. Returns None if nothing is found."""
    if executable is None:
        executable = sys.executable or ""
    if prefixes is None:
        prefixes = (sys.prefix, sys.base_prefix, sys.exec_prefix)
    names = ("python.exe", "python") if os.name == "nt" else ("python3", "python")
    candidates = []
    if os.path.basename(executable).lower().startswith("python"):
        candidates.append(executable)
    folder = os.path.dirname(executable)
    for base in (folder, os.path.join(folder, "Python"), *prefixes):
        if base:
            candidates += [os.path.join(base, n) for n in names]
    seen = set()
    for c in candidates:
        key = os.path.normcase(os.path.abspath(c))
        if key in seen:
            continue
        seen.add(key)
        if isfile(c):
            return c
    return None


def install_commands(packages):
    """The argument lists for python.exe, in order. Only the pip step must
    succeed (ensurepip fails harmlessly when pip is already there)."""
    return [(["-m", "ensurepip", "--upgrade", "--user"], False),
            (["-m", "pip", "install", "--user", "--no-input",
              "--disable-pip-version-check", *packages], True)]


def ensure(packages, tool, ask=None, install=None, tell=None,
           importer=importlib.import_module):
    """True when all packages import (installing them first if the user
    agrees). ask(text) -> bool, install(packages) -> (ok, log),
    tell(text) -> None; the defaults are the Qt dialogs below."""
    packages = tuple(packages)
    if not missing(packages, importer):
        return True
    add_user_site()                     # installed earlier, not on sys.path yet
    todo = missing(packages, importer)
    if not todo:
        return True
    ask = ask or _ask
    install = install or _install
    tell = tell or _tell
    names = " and ".join(todo)
    if not ask("%s needs the Python package%s %s, which 3ds Max does not "
               "include.\n\nInstall %s now? (one time, internet needed, "
               "no admin rights needed)"
               % (tool, "s" if len(todo) > 1 else "", names,
                  "them" if len(todo) > 1 else "it")):
        return False
    log.info("installing %s", " ".join(todo))
    ok, out = install(todo)
    if not ok:
        if out == "cancelled":
            log.info("install of %s cancelled", names)
        else:
            log.error("install of %s failed:\n%s", names, out)
            tell("Installing %s failed.\n\n%s\n\nCheck the internet "
                 "connection and try again, or see README (numpy)."
                 % (names, (out or "")[-1200:]))
        return False
    add_user_site()
    still = missing(todo, importer)
    if still:
        log.warning("installed, but %s does not import yet", " ".join(still))
        tell("%s is installed. Please restart 3ds Max, then run %s again."
             % (" and ".join(still), tool))
        return False
    log.info("%s installed and imported", names)
    tell("%s installed. %s is ready." % (names, tool))
    return True


# --- Qt side ------------------------------------------------------------------

TITLE = "PESI3D Tools"


def _main_window():
    try:
        import qtmax
        return qtmax.GetQMaxMainWindow()
    except Exception:  # noqa: BLE001
        return None


def _ask(text):
    from PySide6.QtWidgets import QMessageBox
    r = QMessageBox.question(_main_window(), TITLE, text,
                             QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
    return r == QMessageBox.Yes


def _tell(text):
    from PySide6.QtWidgets import QMessageBox
    QMessageBox.information(_main_window(), TITLE, text)


def _install(packages):
    """Run the install commands in a modal progress dialog. (ok, log)."""
    exe = python_exe()
    if exe is None:
        return False, ("The Python of 3ds Max was not found (looked next to %s "
                       "and in %s)." % (sys.executable, sys.prefix))
    log.info("python: %s", exe)
    dlg = _make_dialog_class()(exe, packages, _main_window())
    dlg.exec()
    return dlg.ok, dlg.output()


def _make_dialog_class():
    from PySide6 import QtCore, QtWidgets

    class InstallDialog(QtWidgets.QDialog):
        def __init__(self, exe, packages, parent=None):
            super().__init__(parent)
            self.setWindowTitle("%s - installing %s" % (TITLE, ", ".join(packages)))
            self.setMinimumWidth(520)
            self.exe = exe
            self.steps = install_commands(packages)
            self.ok = False
            self.cancelled = False
            self._chunks = []

            lay = QtWidgets.QVBoxLayout(self)
            self.label = QtWidgets.QLabel("Installing %s into the Python of 3ds Max..."
                                          % ", ".join(packages))
            lay.addWidget(self.label)
            bar = QtWidgets.QProgressBar()
            bar.setRange(0, 0)              # busy
            lay.addWidget(bar)
            self.text = QtWidgets.QPlainTextEdit()
            self.text.setReadOnly(True)
            self.text.setMinimumHeight(140)
            lay.addWidget(self.text)
            row = QtWidgets.QHBoxLayout()
            row.addStretch(1)
            self.cancel = QtWidgets.QPushButton("Cancel")
            self.cancel.clicked.connect(self.reject)
            row.addWidget(self.cancel)
            lay.addLayout(row)

            self.proc = QtCore.QProcess(self)
            self.proc.setProcessChannelMode(QtCore.QProcess.MergedChannels)
            env = QtCore.QProcessEnvironment.systemEnvironment()
            env.insert("PYTHONIOENCODING", "utf-8")
            env.insert("PIP_NO_INPUT", "1")
            self.proc.setProcessEnvironment(env)
            self.proc.readyReadStandardOutput.connect(self._read)
            self.proc.finished.connect(self._finished)
            self.proc.errorOccurred.connect(self._error)
            QtCore.QTimer.singleShot(0, self._next)

        def output(self):
            return "cancelled" if self.cancelled else "".join(self._chunks)

        def _append(self, s):
            self._chunks.append(s)
            self.text.moveCursor(self.text.textCursor().MoveOperation.End)
            self.text.insertPlainText(s)
            self.text.ensureCursorVisible()

        def _next(self):
            if not self.steps:
                self.ok = True
                self.accept()
                return
            args, self._must = self.steps[0]
            self.steps = self.steps[1:]
            self._append("> python %s\n" % " ".join(args))
            self.proc.start(self.exe, args)

        def _read(self):
            data = bytes(self.proc.readAllStandardOutput())
            self._append(data.decode("utf-8", "replace"))

        def _finished(self, code, status):
            if self.cancelled:
                return
            if (code != 0 or status != QtCore.QProcess.NormalExit) and self._must:
                self._append("\nexit code %s\n" % code)
                self.label.setText("Installation failed.")
                self.reject()
                return
            self._next()

        def _error(self, err):
            if err == QtCore.QProcess.FailedToStart and not self.cancelled:
                self._append("\ncould not start %s\n" % self.exe)
                self.reject()

        def reject(self):
            if self.proc.state() != QtCore.QProcess.NotRunning:
                self.cancelled = True
                self.proc.kill()
                self.proc.waitForFinished(3000)
            super().reject()

    return InstallDialog
