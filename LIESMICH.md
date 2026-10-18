# PESI3D Tools für 3ds Max

Modellier-Helfer für Autodesk 3ds Max von [PESI3D](https://pesi3d.de) — das
3ds-Max-Gegenstück zu den PESI3D-Plugins für IngeTrazo.

> Stand: **0.1.0 – nur das Grundgerüst** mit einem Vorlage-Plugin (*Hello Box*).

Benötigt **3ds Max 2025 oder neuer** (Python 3 + PySide6, neues Menüsystem).
Getestet mit 3ds Max 2027.

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

Nicht mit Autodesk verbunden oder von Autodesk unterstützt. 3ds Max ist eine Marke von Autodesk, Inc.

Impressum: [pesi3d.de](https://pesi3d.de)
