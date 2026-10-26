# Topology — Gelände für 3ds Max

![Topology](screenshot.webp)

Erzeugt ein Gelände aus **Höhenlinien (Splines)**, aus **Punkten** oder aus den
**Höhenpunkten eines Lageplans (PDF)** — für Lagepläne, Landschafts- und
Stadtplanung, bereit zum Rendern und Scattern. Auf Wunsch mit sauberen Quads.

[English → README.md](README.md)

## Voraussetzungen
- **3ds Max 2025 oder neuer** (getestet mit 3ds Max 2027). Das Werkzeug nutzt PySide6
  (Qt 6) und das Menüsystem, das mit 3ds Max 2025 kam; 3ds Max 2024 und älter werden
  nicht unterstützt.
- **numpy** im Python von 3ds Max — siehe [numpy](#numpy) unten. Topology bietet beim
  ersten Start an, es mit einem Klick zu installieren.

## Installation
1. `Topology-3dsMax-<Version>.zip` vom [neuesten Release](../../releases/latest) laden.
2. Nach `%APPDATA%\Autodesk\ApplicationPlugins\` entpacken — ergibt
   `...\ApplicationPlugins\PESI3D-Tools\PackageContents.xml`.
3. 3ds Max neu starten → Menü **PESI3D ▸ Topology ▸** *Terrain from Contours… · Terrain
   from Points… · Terrain from Plan… · Edit Terrain…* und die andockbare
   Werkzeugleiste **PESI3D**.

Alle Befehle sind auch MacroScripts in der Kategorie **PESI3D** (Hotkey-Editor,
Menü-Editor, Quad-Menüs). Deinstallieren: den Ordner `PESI3D-Tools` löschen.

**Update vom eigenständigen Topology 1.0 (.mzp):** zuerst dessen Dateien in
`%LOCALAPPDATA%\Autodesk\3dsMax\<Jahr> - 64bit\ENU\` löschen:
`scripts\startup\PESI3D_Topology.ms`, `scripts\PESI3D\pesi_topology.py` und
`usermacros\PESI3D-Topology_*.mcr`. Tastenkürzel und Werkzeugleisten-Knöpfe bleiben
(gleiche MacroScript-Namen); mit 1.0 erzeugte Gelände lassen sich mit
*Edit Terrain…* bearbeiten.

## Funktionen
- **Terrain from Contours…** — Höhenlinien-Splines auf ihrer Höhe auswählen. Ein
  regelmäßiges Gitter mit weicher Interpolation zwischen den Linien (keine Terrassen);
  runde oder flache **Kuppen & Senken**; **Smooth surface (radius)** nimmt die Knicke
  an den Linien heraus. **Clean up lines**: Vereinfachen, Glätten, kurze Linien
  ignorieren — zerstörungsfrei.
- **Terrain from Points…** — Point-Helfer, Mesh/Poly-Vertices oder Spline-Knoten. Ein
  Delaunay-Dreiecksnetz exakt durch jeden Punkt; lange Randdreiecke lassen sich kappen.
- **Terrain from Plan…** — liest die **Höhenpunkte eines Lageplans** (Vektor-PDF:
  +402,35 · 403.120 · KD …) samt Punktsymbol. Maßstab aus dem Plan oder **mit zwei
  Klicks gemessen**; Punkte auf dem Blatt prüfen (grün = genutzt, orange =
  weggelassen), Codes wie Fußbodenhöhen oder Kanalsohlen an/aus, echte Höhen behalten
  oder bei 0 beginnen. Die Ansicht zoomt auf das neue Gelände.
- **Footprint** — Umriss · Rechteck, auf die ganze Box interpoliert · Rechteck innerhalb
  der Daten.
- **Quads statt Dreiecke** — ein regelmäßiges Gitter, jede Fläche ein Quad, die
  Vertices zeilenweise nummeriert. Bei Punkten/Plänen dreht sich das Gitter zum
  Gelände. **Quads am Rand**: *Whole cells only* (treppiger Rand) · *Snap to the
  outline* (ein Ring Quads genau auf dem Umriss, Ecken inklusive) · *Cut to the
  outline* (Höhenlinien, n-Ecke am Rand). **Relax the rim quads** glättet den Ring.
- **Schürze** und **geschlossener Boden** — ein dichter Körper; mit Quads ist auch der
  Boden ein Quad-Gitter. Höhenlinien und eine flache Höhenlinienkarte als Kind-Splines.
- **Glättungsgruppen** richtig gesetzt: weiche Hänge, scharfe Knicke (> 45°), scharfe
  Schürzen-Ecken.
- **Live-Vorschau** — das echte Ergebnis in der Szene, während du Werte änderst
  (**● Live Preview ON**, Statuszeile, Reset); der Dialog blockiert das Viewport nicht.
  **OK** ist ein Undo-Schritt, **Cancel** hinterlässt nichts.
- **Edit Terrain…** — das Gelände merkt sich Quelle und Einstellungen; anwählen und
  später alles ändern.
- Längen in Metern, funktioniert mit jeder Systemeinheit. Sicherheitsgrenze bei
  1.000.000 Dreiecken (auf eigene Gefahr übergehbar).

Beispielplan: [site_plan_spot_heights_1-200_A3.pdf](https://github.com/PESI3D/ingetrazo-topology/blob/main/examples/site_plan_spot_heights_1-200_A3.pdf)
(ein erfundener Lageplan, aus der IngeTrazo-Version von Topology).

## numpy
numpy ist eine **separate Installation** — ein freies Python-Paket (BSD-Lizenz), weder
Teil von 3ds Max noch in diesem Zip enthalten. Beim ersten Start eines
Topology-Werkzeugs fragt es nach und installiert numpy mit einem Klick (Internet
nötig, keine Admin-Rechte; `pip install --user numpy` mit dem Python von 3ds Max, mit
Fortschrittsfenster). Falls 3ds Max darum bittet, danach einmal neu starten.

Es landet in deinem Benutzerordner (`%APPDATA%\Python\Python3xx\site-packages`), einmal
**je Python-Version** von 3ds Max: 3ds Max 2025/2026 nutzen Python 3.11, 3ds Max 2027
nutzt Python 3.13. Alle Plugins dieser 3ds-Max-Version teilen es sich; wer Topology
entfernt, behält numpy (`python.exe -m pip uninstall numpy` entfernt es). Von Hand
(Jahreszahl anpassen):

```
"C:\Program Files\Autodesk\3ds Max 2027\Python\python.exe" -m ensurepip --upgrade --user
"C:\Program Files\Autodesk\3ds Max 2027\Python\python.exe" -m pip install --user numpy
```

## Probleme?
Fehler landen in `%LOCALAPPDATA%\PESI3D\3dsMax\pesi3d.log` (**PESI3D ▸ Open log
folder**). Bitte ein [Issue](../../issues) mit dem Log und, wenn möglich, einer kleinen
Beispieldatei anlegen.

## Änderungen
- **1.2** — erstes Release der 3ds-Max-Version als Teil der **PESI3D Tools** (ein
  PESI3D-Menü und eine Werkzeugleiste für alle PESI3D-Werkzeuge): **Terrain from
  Plan…** (Höhenpunkte aus einem Lageplan-PDF); **saubere Quads** für Höhenlinien,
  Punkte und Pläne mit wählbarem Rand (ganze Zellen · an den Umriss · beschnitten) und
  geglätteten Rand-Quads; Quad-Boden; Glättungsgruppen wie Auto Smooth 45° und scharfe
  Schürzen-Ecken; Splitter-Dreiecke am Rand entfernt; die Plan-Vorschau zoomt aufs
  Gelände; numpy per Klick.
- **1.0** — eigenständiges Skript (.mzp): Gelände aus Höhenlinien oder Punkten,
  Live-Vorschau, Edit Terrain.

## Für Entwickler
Topology baut auf einem kleinen Gerüst auf (`Contents/python/pesi3d_max/`): Plugins sind
Module in `pesi3d_max/plugins/` mit `NAME` und `setup(app)`; `pesi3d_max.preview` liefert
den PESI3D-Vorschau-Dialog; `examples/hello.py` ist eine Vorlage.
`tools/install_dev.ps1` verlinkt eine Arbeitskopie nach `ApplicationPlugins`; Tests ohne
3ds Max: `python -m unittest discover -s tests`; Release-Zip:
`tools/build_release.ps1`; Glättungs-Prüfung in 3ds Max: `tools/audit_smoothing.py`.

## Lizenz
GPL-3.0-or-later · © 2026 Pesi (pesi3d.de) · [Impressum](https://pesi3d.de) — siehe
[LICENSE](LICENSE).

Enthält [pypdf](https://github.com/py-pdf/pypdf) 6.19 (BSD-3-Clause, Lizenz in
`Contents/python/pesi3d_max/plugins/topology/_vendor/pypdf/LICENSE`) zum Lesen von
PDF-Plänen.

Nicht mit Autodesk verbunden oder von Autodesk unterstützt. 3ds Max ist eine Marke von
Autodesk, Inc.
