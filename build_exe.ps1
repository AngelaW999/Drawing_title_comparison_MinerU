$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

python -m pip install --upgrade pyinstaller | Out-Host

if (Test-Path ".\build") { Remove-Item ".\build" -Recurse -Force }
if (Test-Path ".\dist")  { Remove-Item ".\dist"  -Recurse -Force }

python -m PyInstaller -y --noconfirm --clean ".\DrawingTitleComparison.spec"

Write-Host ""
Write-Host "Build done."
Write-Host "dist\DrawingTitleComparison\DrawingTitleComparison.exe"
