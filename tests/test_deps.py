"""deps tests (numpy installer decision logic) - run without 3ds Max:
    python -m unittest discover -s tests
numpy is never really uninstalled: the import is mocked.
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Contents" / "python"))

from pesi3d_max import deps  # noqa: E402


class FakeImport:
    """import_module stand-in: names in `absent` raise ImportError until
    install() 'installs' them (unless sticky = needs a restart)."""

    def __init__(self, absent, sticky=False):
        self.absent = set(absent)
        self.sticky = sticky

    def __call__(self, name):
        if name in self.absent:
            raise ImportError(name)
        return object()

    def install(self, packages):
        if not self.sticky:
            self.absent -= set(packages)
        return True, "ok"


class EnsureTest(unittest.TestCase):
    def run_ensure(self, imp, answer=True, install=None):
        self.asked, self.told, self.installed = [], [], []

        def ask(text):
            self.asked.append(text)
            return answer

        def do_install(pk):
            self.installed.append(list(pk))
            return (install or imp.install)(pk)

        return deps.ensure(("numpy",), "Topology", ask=ask, install=do_install,
                           tell=self.told.append, importer=imp)

    def test_present_asks_nothing(self):
        self.assertTrue(self.run_ensure(FakeImport([])))
        self.assertEqual((self.asked, self.installed, self.told), ([], [], []))

    def test_declined(self):
        self.assertFalse(self.run_ensure(FakeImport(["numpy"]), answer=False))
        self.assertEqual(len(self.asked), 1)
        self.assertIn("Topology needs the Python package numpy", self.asked[0])
        self.assertEqual(self.installed, [])

    def test_install_ok_imports_in_session(self):
        self.assertTrue(self.run_ensure(FakeImport(["numpy"])))
        self.assertEqual(self.installed, [["numpy"]])
        self.assertIn("ready", self.told[-1])

    def test_installed_but_needs_restart(self):
        self.assertFalse(self.run_ensure(FakeImport(["numpy"], sticky=True)))
        self.assertIn("restart 3ds Max", self.told[-1])

    def test_install_failed_shows_log(self):
        ok = self.run_ensure(FakeImport(["numpy"]),
                             install=lambda pk: (False, "ERROR: no network"))
        self.assertFalse(ok)
        self.assertIn("no network", self.told[-1])

    def test_cancel_is_silent(self):
        ok = self.run_ensure(FakeImport(["numpy"]),
                             install=lambda pk: (False, "cancelled"))
        self.assertFalse(ok)
        self.assertEqual(self.told, [])

    def test_only_missing_packages_installed(self):
        imp = FakeImport(["scipy"])
        self.installed = []
        ok = deps.ensure(("numpy", "scipy"), "X", ask=lambda t: True,
                         install=lambda pk: (self.installed.append(list(pk)),
                                             imp.install(pk))[1],
                         tell=lambda t: None, importer=imp)
        self.assertTrue(ok)
        self.assertEqual(self.installed, [["scipy"]])


class PythonExeTest(unittest.TestCase):
    MAX = os.path.join("C:\\", "Program Files", "Autodesk", "3ds Max 2027")

    def test_inside_max(self):
        want = os.path.join(self.MAX, "Python", "python.exe")
        exe = deps.python_exe(os.path.join(self.MAX, "3dsmax.exe"), prefixes=(),
                              isfile=lambda p: p == want)
        self.assertEqual(exe, want)

    def test_from_prefix(self):
        want = os.path.join("D:\\", "py", "python.exe")
        exe = deps.python_exe(os.path.join(self.MAX, "3dsmax.exe"),
                              prefixes=(os.path.join("D:\\", "py"),),
                              isfile=lambda p: p == want)
        self.assertEqual(exe, want)

    def test_plain_python(self):
        exe = os.path.join("D:\\", "py", "python.exe")
        self.assertEqual(deps.python_exe(exe, prefixes=(), isfile=lambda p: p == exe), exe)

    def test_not_found(self):
        self.assertIsNone(deps.python_exe(os.path.join(self.MAX, "3dsmax.exe"),
                                          prefixes=(), isfile=lambda p: False))

    def test_this_python(self):
        self.assertIsNotNone(deps.python_exe())


class CommandsTest(unittest.TestCase):
    def test_commands(self):
        steps = deps.install_commands(["numpy"])
        self.assertEqual(steps[0], (["-m", "ensurepip", "--upgrade", "--user"], False))
        args, must = steps[1]
        self.assertTrue(must)
        self.assertEqual(args[:4], ["-m", "pip", "install", "--user"])
        self.assertEqual(args[-1], "numpy")


if __name__ == "__main__":
    unittest.main()
