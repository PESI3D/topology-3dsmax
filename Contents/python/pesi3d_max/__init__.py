"""PESI3D Tools for 3ds Max.

Start-up flow (see Contents/scripts/pesi3d_prestartup.ms):
    boot()  -> discover plugins, define their MacroScripts,
               hook #cuiRegisterMenus
    3ds Max builds its menus -> _on_register_menus() adds the PESI3D menu
    menu click -> MacroScript -> run(plugin_id, action_id)
"""

import os
import traceback

from . import registry as _registry
from .log import get_logger, log_dir

VERSION = "0.3.0"
MENU_TITLE = "PESI3D"
CORE_ID = "core"
SHARED_MENU_ID = "abd4e2a7-552b-42c8-8087-1d114c477063"   # same as PESI3D_Topology.ms
HELP_MENU_ID = "cee8f758-2199-411b-81e7-d3ff4a80d143"     # 3ds Max "Help" menu

log = get_logger()
REGISTRY = _registry.Registry()
_CORE_ACTIONS = []


def boot():
    """Called once by the pre-start-up script."""
    from pymxs import runtime as rt

    _discover()
    rt.callbacks.removeScripts(id=rt.Name("pesi3d_menus"))
    rt.callbacks.addScript(rt.Name("cuiRegisterMenus"), _on_register_menus,
                           id=rt.Name("pesi3d_menus"))
    rt.callbacks.removeScripts(id=rt.Name("pesi3d_toolbar"))
    rt.callbacks.addScript(rt.Name("postSystemStartup"), _on_startup,
                           id=rt.Name("pesi3d_toolbar"))
    log.info("PESI3D Tools %s booted, plugins: %s", VERSION, ", ".join(REGISTRY.plugins))


def run(plugin_id, action_id):
    """Entry point of every PESI3D MacroScript."""
    if plugin_id == CORE_ID:
        action = next((a for a in _CORE_ACTIONS if a.action_id == action_id), None)
    else:
        action = REGISTRY.find(plugin_id, action_id)
    if action is None:
        _message("PESI3D: unknown action %s/%s - restart 3ds Max after adding plugins."
                 % (plugin_id, action_id))
        return
    try:
        action.callback()
    except Exception:
        log.error("%s/%s failed:\n%s", plugin_id, action_id, traceback.format_exc())
        _message("%s failed - details in the MAXScript Listener and in\n%s"
                 % (action.text, log_dir() / "pesi3d.log"))


def reload_plugins():
    """Re-import all plugins (code changes without restarting 3ds Max).
    New actions only get a menu entry after a restart."""
    import importlib
    import sys
    for name in ("pesi3d_max.preview",):      # shared helpers the plugins import
        if name in sys.modules:
            importlib.reload(sys.modules[name])
    _discover(reload=True)
    broken = [p for p in REGISTRY.plugins.values() if p.error]
    msg = "PESI3D: %d plugin(s) reloaded" % len(REGISTRY.plugins)
    if broken:
        msg += ", %d with errors: %s" % (len(broken), ", ".join(p.plugin_id for p in broken))
    _prompt(msg)


# --- internals --------------------------------------------------------------

def _discover(reload=False):
    from pymxs import runtime as rt

    REGISTRY.discover(reload=reload)
    for plugin in REGISTRY.plugins.values():
        if plugin.error:
            log.error("plugin %s failed to load:\n%s", plugin.plugin_id, plugin.error)
    if not _CORE_ACTIONS:
        _CORE_ACTIONS.extend([
            _registry.Action(CORE_ID, "reload", "Reload plugins", reload_plugins,
                             "Re-import the PESI3D plugins after a code change"),
            _registry.Action(CORE_ID, "log", "Open log folder", _open_log_folder,
                             "Show pesi3d.log in Explorer"),
            _registry.Action(CORE_ID, "about", "About PESI3D Tools...", _about),
        ])
    for action in REGISTRY.actions() + _CORE_ACTIONS:
        rt.execute(action.macro_source())


def _on_register_menus():
    from pymxs import runtime as rt

    try:
        mgr = rt.callbacks.notificationParam()
        guid = _registry.stable_guid
        root = _shared_menu(mgr.mainMenuBar)
        if root.menuItems.count > 0:
            root.CreateSeparator(guid("sep/tools"))
        for plugin in REGISTRY.plugins.values():
            if plugin.error:
                continue
            if len(plugin.actions) == 1:
                a = plugin.actions[0]
                root.CreateAction(guid("item/" + a.macro_name), _registry.MACRO_TABLE_ID, a.macro_ref)
                continue
            sub = root.CreateSubMenu(guid("menu/" + plugin.plugin_id), plugin.name)
            for a in plugin.actions:
                sub.CreateAction(guid("item/" + a.macro_name), _registry.MACRO_TABLE_ID,
                                 a.macro_ref, title=a.text)
        root.CreateSeparator(guid("sep/core"))
        for a in _CORE_ACTIONS:
            root.CreateAction(guid("item/" + a.macro_name), _registry.MACRO_TABLE_ID, a.macro_ref)
    except Exception:
        log.error("menu registration failed:\n%s", traceback.format_exc())


def _on_startup():
    """After the main window exists: the shared PESI3D toolbar."""
    try:
        from . import toolbar
        toolbar.install([a for a in REGISTRY.actions() if a.icon])
    except Exception:
        log.error("toolbar failed:\n%s", traceback.format_exc())


def _shared_menu(bar):
    """The one "PESI3D" main menu, shared with the stand-alone PESI3D scripts
    (Topology, Grading: scripts\\startup\\PESI3D_*.ms use the same ids)."""
    for item in bar.menuItems:
        if item.isSubMenu and str(item.id) == SHARED_MENU_ID:
            return item.subMenu
    return bar.CreateSubMenu(SHARED_MENU_ID, MENU_TITLE, beforeId=HELP_MENU_ID)


def _open_log_folder():
    folder = log_dir()
    folder.mkdir(parents=True, exist_ok=True)
    os.startfile(str(folder))


def _about():
    lines = ["PESI3D Tools %s" % VERSION, "https://pesi3d.de", ""]
    for p in REGISTRY.plugins.values():
        lines.append("%s%s" % (p.name, "  (load error)" if p.error else ""))
    lines += ["", "Not affiliated with or endorsed by Autodesk.",
              "3ds Max is a trademark of Autodesk, Inc."]
    _message("\n".join(lines), title="About PESI3D Tools")


def _message(text, title="PESI3D Tools"):
    from pymxs import runtime as rt
    rt.messageBox(text, title=title)


def _prompt(text):
    from pymxs import runtime as rt
    rt.pushPrompt(text)
    print(text)
