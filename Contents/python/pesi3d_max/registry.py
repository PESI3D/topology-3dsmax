"""Plugin discovery and the action registry - no 3ds Max needed here.

A plugin is a module (or package) inside ``pesi3d_max.plugins`` with

    NAME = "Hello"                      # menu title
    def setup(app):                     # app is a PluginApi
        app.add_action("box", "Hello Box...", open_dialog, tooltip="...")

Each action becomes a MacroScript ``pesi3d_<plugin>_<action>`` in the
category "PESI3D" (so it can go on toolbars, quad menus and hotkeys via
Customize UI) and an entry in the PESI3D main menu.
"""

import importlib
import pkgutil
import re
import sys
import traceback
import uuid
from dataclasses import dataclass, field

CATEGORY = "PESI3D"
MACRO_TABLE_ID = 647394          # action table of all MacroScripts
_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_NS = uuid.UUID("110cc5c3-290a-470f-87d8-4daeab431dec")


def stable_guid(key):
    """Same key -> same GUID on every start (menu items need stable ids)."""
    return str(uuid.uuid5(_NS, key))


@dataclass
class Action:
    plugin_id: str
    action_id: str
    text: str
    callback: object
    tooltip: str = ""

    @property
    def macro_name(self):
        return "pesi3d_%s_%s" % (self.plugin_id, self.action_id)

    @property
    def macro_ref(self):
        """actionID for menu.CreateAction: "<macro>`<category>"."""
        return "%s`%s" % (self.macro_name, CATEGORY)

    def macro_source(self):
        call = "import pesi3d_max; pesi3d_max.run('%s', '%s')" % (self.plugin_id, self.action_id)
        return (
            'macroScript %s category:"%s" buttonText:"%s" toolTip:"%s"\n'
            '(\n\ton execute do python.Execute "%s"\n)\n'
            % (self.macro_name, CATEGORY, _ms_str(self.text),
               _ms_str(self.tooltip or self.text), call)
        )


@dataclass
class Plugin:
    plugin_id: str
    name: str
    module: object = None
    actions: list = field(default_factory=list)
    error: str = ""


class PluginApi:
    """What a plugin's setup(app) gets to see."""

    def __init__(self, plugin):
        self._plugin = plugin

    def add_action(self, action_id, text, callback, tooltip=""):
        if not _ID_RE.match(action_id):
            raise ValueError("action id must be lower_snake_case: %r" % action_id)
        if any(a.action_id == action_id for a in self._plugin.actions):
            raise ValueError("duplicate action id: %r" % action_id)
        self._plugin.actions.append(
            Action(self._plugin.plugin_id, action_id, text, callback, tooltip))


class Registry:
    def __init__(self, package="pesi3d_max.plugins"):
        self.package = package
        self.plugins = {}

    def discover(self, reload=False):
        """Import every plugin module and run its setup(). A broken plugin
        never stops the others: it is kept with .error set."""
        if reload:
            prefix = self.package + "."
            for name in [n for n in sys.modules if n.startswith(prefix)]:
                del sys.modules[name]
        pkg = importlib.import_module(self.package)
        self.plugins = {}
        for info in sorted(pkgutil.iter_modules(pkg.__path__), key=lambda i: i.name):
            if info.name.startswith("_") or not _ID_RE.match(info.name):
                continue
            plugin = Plugin(info.name, info.name)
            try:
                module = importlib.import_module(self.package + "." + info.name)
                plugin.module = module
                plugin.name = getattr(module, "NAME", info.name)
                module.setup(PluginApi(plugin))
            except Exception:
                plugin.error = traceback.format_exc()
                plugin.actions = []
            self.plugins[plugin.plugin_id] = plugin
        return self.plugins

    def actions(self):
        return [a for p in self.plugins.values() for a in p.actions]

    def find(self, plugin_id, action_id):
        plugin = self.plugins.get(plugin_id)
        if plugin:
            for a in plugin.actions:
                if a.action_id == action_id:
                    return a
        return None


def _ms_str(text):
    """Escape for a MAXScript string literal."""
    return text.replace("\\", "\\\\").replace('"', '\\"')
