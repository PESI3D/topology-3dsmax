-- PESI3D Tools - pre-start-up bootstrap.
-- Runs before 3ds Max builds its menus: adds Contents\python to sys.path
-- and lets pesi3d_max.boot() hook #cuiRegisterMenus. Everything else is Python.
(
	local contentsDir = pathConfig.removePathLeaf (pathConfig.removePathLeaf (getThisScriptFilename()))
	global pesi3d_python_dir = pathConfig.appendPath contentsDir "python"
	try
	(
		python.Execute "import sys\nfrom pymxs import runtime as rt\np = str(rt.pesi3d_python_dir)\nif p not in sys.path: sys.path.insert(0, p)\nimport pesi3d_max\npesi3d_max.boot()"
	)
	catch
	(
		format "PESI3D Tools: start failed: %\n" (getCurrentException())
	)
)
