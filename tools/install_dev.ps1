# Developer install: links this working copy into the per-user
# ApplicationPlugins folder, so 3ds Max loads the code straight from the repo.
# After a code change: PESI3D > Reload plugins (or restart 3ds Max for new menu entries).
#   powershell -ExecutionPolicy Bypass -File tools\install_dev.ps1
#   powershell -ExecutionPolicy Bypass -File tools\install_dev.ps1 -Uninstall

param([switch]$Uninstall)

$repo = Split-Path -Parent $PSScriptRoot
$plugins = Join-Path $env:APPDATA "Autodesk\ApplicationPlugins"
$link = Join-Path $plugins "PESI3D-Tools"

if ($Uninstall) {
    if (Test-Path $link) {
        $item = Get-Item $link -Force
        if ($item.LinkType -ne "Junction") { throw "$link is not a junction - left alone." }
        $item.Delete()   # removes only the link, never the repo
        Write-Host "Removed $link"
    }
    return
}

New-Item -ItemType Directory -Force $plugins | Out-Null
if (Test-Path $link) {
    $item = Get-Item $link -Force
    if ($item.LinkType -eq "Junction" -and $item.Target -contains $repo) {
        Write-Host "Already linked: $link -> $repo"
        return
    }
    throw "$link already exists - remove it first (install_dev.ps1 -Uninstall)."
}
New-Item -ItemType Junction -Path $link -Target $repo | Out-Null
Write-Host "Linked $link -> $repo"
Write-Host "Restart 3ds Max: the PESI3D menu appears in the main menu bar."
