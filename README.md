# PESI3D Tools for 3ds Max

Modelling helpers for Autodesk 3ds Max by [PESI3D](https://pesi3d.de) — the
3ds Max counterpart of the PESI3D plugins for IngeTrazo.

> Status: **0.1.0 – framework only.** It ships one template plugin (*Hello Box*).

Requires **3ds Max 2025 or newer** (Python 3 + PySide6, new menu system).
Tested on 3ds Max 2026 and 2027.

## Install

1. Download `PESI3D-Tools-<version>.zip` from the Releases page.
2. Unpack it into `%APPDATA%\Autodesk\ApplicationPlugins\`
   (you get `...\ApplicationPlugins\PESI3D-Tools\PackageContents.xml`).
3. Restart 3ds Max. A **PESI3D** menu appears in the main menu bar.

All tools are also MacroScripts in the category **PESI3D**, so you can put them on
toolbars, quad menus or hotkeys via *Customize ▸ Hotkey Editor / Menu Editor*.

Errors are written to `%LOCALAPPDATA%\PESI3D\3dsMax\pesi3d.log`
(*PESI3D ▸ Open log folder*).

## Writing a plugin

Add a module to `Contents/python/pesi3d_max/plugins/` — `hello.py` is the template:

```python
NAME = "Hello"

def setup(app):
    app.add_action("box", "Hello Box...", lambda: preview.show(HelloBoxDialog))
```

Tools with settings derive from `pesi3d_max.preview.PreviewDialog` and get the
PESI3D live preview for free: non-modal dialog, *Follow selection*,
**● Live Preview ON** / Reset / OK / Cancel, a status banner, and the result
as **one** undo step. Implement `build_controls`, `reset_controls` and
`build(targets)` (returns the new nodes).

Development: `tools\install_dev.ps1` links the working copy into
`ApplicationPlugins`; after a code change use *PESI3D ▸ Reload plugins*
(new menu entries need a restart). Tests without 3ds Max:
`python -m unittest discover -s tests`. Release zip: `tools\build_release.ps1`.

## License

GPL-3.0 — see [LICENSE](LICENSE).

Not affiliated with or endorsed by Autodesk. 3ds Max is a trademark of Autodesk, Inc.

Impressum: [pesi3d.de](https://pesi3d.de)
