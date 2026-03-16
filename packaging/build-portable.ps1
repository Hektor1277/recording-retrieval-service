$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$spec = Join-Path $root "packaging\recording-retrieval-service.spec"
$dist = Join-Path $root "dist"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$releaseDir = Join-Path $dist "releases"
$bundle = Join-Path $releaseDir "recording-retrieval-service-portable-$timestamp"
$zipPath = Join-Path $dist "recording-retrieval-service-portable-$timestamp.zip"

if (-not (Test-Path $python)) {
  throw "Missing local virtual environment: $python"
}

& $python -m PyInstaller --noconfirm --distpath $dist --workpath (Join-Path $root "build\pyinstaller") $spec
if ($LASTEXITCODE -ne 0) {
  throw "PyInstaller build failed with exit code $LASTEXITCODE"
}

New-Item -ItemType Directory -Force -Path $bundle | Out-Null
Copy-Item -Recurse -Force (Join-Path $dist "recording-retrieval-service\*") $bundle
Copy-Item -Force (Join-Path $root "packaging\portable-start-service.cmd") (Join-Path $bundle "start-service.cmd")
Copy-Item -Force (Join-Path $root "packaging\portable-start-ui.cmd") (Join-Path $bundle "start-ui.cmd")
if (Test-Path $zipPath) {
  Remove-Item -Force $zipPath
}
Compress-Archive -Path (Join-Path $bundle '*') -DestinationPath $zipPath
Write-Host "Portable directory: $bundle"
Write-Host "Portable zip: $zipPath"
