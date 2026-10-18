# Builds dist\PESI3D-Tools-<version>.zip: one folder "PESI3D-Tools" that the
# user unpacks into %APPDATA%\Autodesk\ApplicationPlugins\.
#   powershell -ExecutionPolicy Bypass -File tools\build_release.ps1

$repo = Split-Path -Parent $PSScriptRoot
$init = Get-Content (Join-Path $repo "Contents\python\pesi3d_max\__init__.py") -Raw
if ($init -notmatch 'VERSION = "([^"]+)"') { throw "VERSION not found in __init__.py" }
$version = $Matches[1]

$xml = Get-Content (Join-Path $repo "PackageContents.xml") -Raw
if ($xml -notmatch "AppVersion=`"$([regex]::Escape($version))`"") {
    throw "AppVersion in PackageContents.xml does not match VERSION $version"
}

$dist = Join-Path $repo "dist"
$stage = Join-Path $dist "stage\PESI3D-Tools"
if (Test-Path (Join-Path $dist "stage")) { Remove-Item -Recurse -Force (Join-Path $dist "stage") }
New-Item -ItemType Directory -Force $stage | Out-Null

foreach ($f in "PackageContents.xml", "LICENSE", "README.md", "LIESMICH.md") {
    Copy-Item (Join-Path $repo $f) $stage
}
Copy-Item -Recurse (Join-Path $repo "Contents") $stage
Get-ChildItem $stage -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

$zip = Join-Path $dist "PESI3D-Tools-$version.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path $stage -DestinationPath $zip
Remove-Item -Recurse -Force (Join-Path $dist "stage")
Write-Host "Built $zip"
(Get-FileHash $zip -Algorithm SHA256).Hash
