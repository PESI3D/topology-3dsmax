# PESI3D Tools für 3ds Max

Modellier-Helfer für Autodesk 3ds Max von [PESI3D](https://pesi3d.de) — das
3ds-Max-Gegenstück zu den PESI3D-Plugins für IngeTrazo.

> Stand: **0.3.0** – Grundgerüst, **Topology** (Gelände aus Höhenlinien, Punkten oder den
> Höhenpunkten eines Lageplan-PDFs) und das Vorlage-Plugin *Hello Box*.

Benötigt **3ds Max 2025 oder neuer**: Die Werkzeuge nutzen PySide6 (Qt 6, in 3ds Max
seit 2025) und das mit 3ds Max 2025 eingeführte Menüsystem. 3ds Max 2024 und älter
(Qt 5 / PySide2, alter Menü-Manager) werden nicht unterstützt.
Getestet mit 3ds Max 2027.

**Topology braucht numpy** im Python von 3ds Max (3ds Max liefert es nicht mit).
Beim ersten Start eines Topology-Werkzeugs bietet es an, numpy mit einem Klick zu
installieren (Internet nötig, keine Admin-Rechte; es ruft `pip install --user numpy`
mit dem Python von 3ds Max auf und zeigt den Fortschritt). Falls 3ds Max darum
bittet, danach einmal neu starten.

Von Hand geht es auch, in der Eingabeaufforderung (Jahreszahl anpassen):

```
"C:\Program Files\Autodesk\3ds Max 2027\Python\python.exe" -m ensurepip --upgrade --user
"C:\Program Files\Autodesk\3ds Max 2027\Python\python.exe" -m pip install --user numpy
```

## Installation

1. `PESI3D-Tools-<Version>.zip` von der Releases-Seite laden.
2. Nach `%APPDATA%\Autodesk\ApplicationPlugins\` entpacken
   (ergibt `...\ApplicationPlugins\PESI3D-Tools\PackageContents.xml`).
3. 3ds Max neu starten. In der Hauptmenüleiste erscheint das Menü **PESI3D**.

Alle Werkzeuge sind auch MacroScripts in der Kategorie **PESI3D** und lassen sich
über *Anpassen ▸ Hotkey-Editor / Menü-Editor* auf Werkzeugleisten, Quad-Menüs
oder Tastenkürzel legen.

Fehler landen in `%LOCALAPPDATA%\PESI3D\3dsMax\pesi3d.log`
(*PESI3D ▸ Open log folder*).

## Eigene Plugins

Ein Modul in `Contents/python/pesi3d_max/plugins/` anlegen — `hello.py` ist die
Vorlage. Werkzeuge mit Einstellungen erben von `pesi3d_max.preview.PreviewDialog`
und bekommen die PESI3D-Live-Vorschau geschenkt (nicht-modal, *Follow selection*,
**● Live Preview ON** / Reset / OK / Cancel, Statusbanner, Ergebnis als **ein**
Undo-Schritt).

## Lizenz

GPL-3.0 — siehe [LICENSE](LICENSE).

Topology enthält [pypdf](https://github.com/py-pdf/pypdf) (BSD-3-Clause, Lizenz in
`Contents/python/pesi3d_max/plugins/topology/_vendor/pypdf/LICENSE`) zum Lesen von PDF-Plänen.

Nicht mit Autodesk verbunden oder von Autodesk unterstützt. 3ds Max ist eine Marke von Autodesk, Inc.

Impressum: [pesi3d.de](https://pesi3d.de)
