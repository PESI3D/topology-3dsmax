"""Registry tests - run without 3ds Max:
    python -m unittest discover -s tests
"""

import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Contents" / "python"))

from pesi3d_max import registry  # noqa: E402


class RegistryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        pkg = root / "fakeplugins"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "good.py").write_text(textwrap.dedent('''
            NAME = "Good One"
            def setup(app):
                app.add_action("run", 'Say "hi"', lambda: None, tooltip="tip")
                app.add_action("other", "Other", lambda: None)
        '''))
        (pkg / "broken.py").write_text("raise RuntimeError('boom')\n")
        (pkg / "_private.py").write_text("raise AssertionError('must be skipped')\n")
        sys.path.insert(0, str(root))
        self.reg = registry.Registry("fakeplugins")
        self.reg.discover()

    def tearDown(self):
        sys.path.remove(self.tmp.name)
        for name in [n for n in sys.modules if n.startswith("fakeplugins")]:
            del sys.modules[name]
        self.tmp.cleanup()

    def test_discovery(self):
        self.assertEqual(sorted(self.reg.plugins), ["broken", "good"])
        self.assertIn("boom", self.reg.plugins["broken"].error)
        self.assertEqual(self.reg.plugins["good"].name, "Good One")
        self.assertEqual([a.action_id for a in self.reg.actions()], ["run", "other"])

    def test_macro(self):
        a = self.reg.find("good", "run")
        self.assertEqual(a.macro_ref, "pesi3d_good_run`PESI3D")
        src = a.macro_source()
        self.assertIn('buttonText:"Good One: Say \\"hi\\""', src)
        self.assertIn("pesi3d_max.run('good', 'run')", src)

    def test_reload(self):
        self.reg.discover(reload=True)
        self.assertIsNotNone(self.reg.find("good", "other"))

    def test_bad_ids(self):
        api = registry.PluginApi(registry.Plugin("x", "X"))
        api.add_action("ok_1", "OK", None)
        with self.assertRaises(ValueError):
            api.add_action("ok_1", "dup", None)
        with self.assertRaises(ValueError):
            api.add_action("Bad-Id", "bad", None)

    def test_custom_macro_and_icon(self):
        api = registry.PluginApi(registry.Plugin("topo", "Topology"))
        api.add_action("contours", "Terrain from Contours", None,
                       macro="Topology_Contours", icon="PESI3D\\Topology_Contours")
        a = api._plugin.actions[0]
        self.assertEqual(a.macro_ref, "Topology_Contours`PESI3D")
        self.assertEqual(a.label, "Topology: Terrain from Contours")
        src = a.macro_source()
        self.assertIn('buttonText:"Topology: Terrain from Contours"', src)
        self.assertIn('iconName:"PESI3D\\\\Topology_Contours"', src)
        with self.assertRaises(ValueError):
            api.add_action("x", "X", None, macro="bad name")

    def test_real_plugins_load(self):
        reg = registry.Registry()          # pesi3d_max.plugins
        reg.discover()
        self.assertEqual(reg.plugins["topology"].error, "")
        # the template lives in examples/, it is not shipped or loaded
        self.assertNotIn("hello", reg.plugins)
        macros = [a.macro_name for a in reg.actions()]
        self.assertIn("Topology_Contours", macros)
        self.assertEqual(len(macros), len(set(macros)))

    def test_stable_guid(self):
        self.assertEqual(registry.stable_guid("a"), registry.stable_guid("a"))
        self.assertNotEqual(registry.stable_guid("a"), registry.stable_guid("b"))


if __name__ == "__main__":
    unittest.main()
