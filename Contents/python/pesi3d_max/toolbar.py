"""The shared, dockable "PESI3D" toolbar.

Same object name and button names as the stand-alone PESI3D scripts
(Grading: pesi_grading.install_toolbar), so all PESI3D tools share one bar.
Every action with an icon gets a button that runs its MacroScript.
"""

from .registry import CATEGORY

TOOLBAR_NAME = "PESI3D_Toolbar"


def install(actions):
    import qtmax
    from pymxs import runtime as rt
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QToolBar

    if not actions:
        return None
    mw = qtmax.GetQMaxMainWindow()
    tb = mw.findChild(QToolBar, TOOLBAR_NAME)
    if tb is None:
        tb = QToolBar("PESI3D", mw)
        tb.setObjectName(TOOLBAR_NAME)
        tb.setToolButtonStyle(Qt.ToolButtonIconOnly)
        main = mw.findChild(QToolBar, "Main Toolbar")
        if main is not None:
            tb.setIconSize(main.iconSize())
        mw.addToolBarBreak(Qt.TopToolBarArea)
        mw.addToolBar(Qt.TopToolBarArea, tb)
    have = {a.objectName() for a in tb.actions()}
    last_plugin = None
    for action in actions:
        name = "PESI3D_" + action.macro_name
        if name in have:
            continue
        if tb.actions() and action.plugin_id != last_plugin:
            tb.addSeparator()
        last_plugin = action.plugin_id
        icon = qtmax.LoadMaxMultiResIcon(action.icon.replace("\\", "/"))
        qa = QAction(icon, action.label, tb)
        qa.setObjectName(name)
        qa.setToolTip(action.label + ("\n" + action.tooltip if action.tooltip else ""))
        qa.triggered.connect(lambda _=False, m=action.macro_name: rt.macros.run(CATEGORY, m))
        tb.addAction(qa)
    tb.show()
    return tb
