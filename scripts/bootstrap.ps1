#Requires -Version 5.1
<#
One-command local setup for Windows PowerShell: hash-verified dependencies, a health check, then the demo.

  powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1            # set up, check, open the demo
  powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1 -NoDemo    # set up and check only

Needs Python 3.12+ (the `py` launcher) or `uv`. Nothing is installed outside .\.venv.
Written from the macOS/Linux script; exercised less often, so please report problems.
#>
param([switch]$NoDemo)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$py = ".venv\Scripts\python.exe"
$useUv = [bool](Get-Command uv -ErrorAction SilentlyContinue)
if (-not (Test-Path $py)) {
  if ($useUv) { Write-Host "==> creating .venv with uv"; uv venv --python 3.12 .venv }
  else { Write-Host "==> creating .venv with py -3.12"; py -3.12 -m venv .venv }
}

Write-Host "==> installing hash-pinned dependencies (requirements.lock.txt)"
if ($useUv) {
  uv pip install --python $py --require-hashes -r requirements.lock.txt
  uv pip install --python $py --no-deps -e .
} else {
  & $py -m pip install --quiet --upgrade pip
  & $py -m pip install --require-hashes -r requirements.lock.txt
  & $py -m pip install --no-deps -e .
}

Write-Host "==> health check"
& $py -m aero_audit.cli doctor
if ($LASTEXITCODE -ne 0) { Write-Host "(doctor reported failures; the offline demo may still work)" }

if ($NoDemo) { Write-Host "==> ready. Next: .venv\Scripts\aero demo" }
else { Write-Host "==> starting the demo (Ctrl+C to stop)"; & $py -m aero_audit.cli demo }
