"""Logging for PESI3D Tools.

Everything goes to %LOCALAPPDATA%\\PESI3D\\3dsMax\\pesi3d.log (rotating) and,
for warnings and errors, also to the MAXScript Listener via print().
"""

import logging
import logging.handlers
import os
from pathlib import Path

_LOGGER_NAME = "pesi3d_max"


def log_dir():
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "PESI3D" / "3dsMax"


class _ListenerHandler(logging.Handler):
    def emit(self, record):
        try:
            print("PESI3D: " + self.format(record))
        except Exception:
            pass


def get_logger(name=None):
    root = logging.getLogger(_LOGGER_NAME)
    if not root.handlers:
        root.setLevel(logging.DEBUG)
        root.propagate = False
        try:
            folder = log_dir()
            folder.mkdir(parents=True, exist_ok=True)
            fh = logging.handlers.RotatingFileHandler(
                folder / "pesi3d.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
            fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
            root.addHandler(fh)
        except OSError:
            pass
        lh = _ListenerHandler(logging.WARNING)
        lh.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        root.addHandler(lh)
    return root.getChild(name) if name else root
