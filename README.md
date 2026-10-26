# PESI3D Tools for 3ds Max

Modelling helpers for Autodesk 3ds Max by [PESI3D](https://pesi3d.de) — the
3ds Max counterpart of the PESI3D plugins for IngeTrazo.

> Status: **0.3.0** – framework, **Topology** (terrain from contour splines, points or
> the spot heights of a site plan PDF).

Requires **3ds Max 2025 or newer**: the tools use PySide6 (Qt 6, shipped since
3ds Max 2025) and the menu system introduced with 3ds Max 2025. 3ds Max 2024 and
older (Qt 5 / PySide2, old menu manager) are not supported.
Tested on 3ds Max 2027.

**Topology needs numpy** in the 3ds Max Python (3ds Max does not ship it). The first
time you start a Topology tool it offers to install numpy with one click (internet
needed, no admin rights; it runs `pip install --user numpy` with the Python of
3ds Max and shows the progress). If 3ds Max asks for it, restart once afterwards.

> **Note:** numpy is a **separate installation** — an open-source Python package
> (BSD licence), not part of 3ds Max and not inside the PESI3D Tools zip. It goes
> into your user folder (`%APPDATA%\Python\Python3xx\site-packages`), once **per
> Python version** of 3ds Max: 3ds Max 2025/2026 use Python 3.11, 3ds Max 2027
> uses Python 3.13. All plugins of that 3ds Max share it. Uninstalling PESI3D Tools
> leaves numpy in place; remove it with `python.exe -m pip uninstall numpy`.

To install it by hand instead, in a command prompt (adjust the year):

```
"C:\Program Files\Autodesk\3ds Max 2027\Python\python.exe" -m ensurepip --upgrade --user
"C:\Program Files\Autodesk\3ds Max 2027\Python\python.exe" -m pip install --user numpy
```

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

Add a module to `Contents/python/pesi3d_max/plugins/` — `examples/hello.py` is the
template (copy it there; it is not shipped):

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

Topology bundles [pypdf](https://github.com/py-pdf/pypdf) (BSD-3-Clause, licence in
`Contents/python/pesi3d_max/plugins/topology/_vendor/pypdf/LICENSE`) to read PDF plans.

Not affiliated with or endorsed by Autodesk. 3ds Max is a trademark of Autodesk, Inc.

Impressum: [pesi3d.de](https://pesi3d.de)
