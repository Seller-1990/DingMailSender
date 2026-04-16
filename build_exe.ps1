$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$cacheDir = Join-Path $root "build\\pip_cache"
$tmpDir = Join-Path $root "build\\tmp"
New-Item -ItemType Directory -Force $cacheDir, $tmpDir | Out-Null
$pyinstallerConfigDir = Join-Path $root "build\\pyinstaller_config"
New-Item -ItemType Directory -Force $pyinstallerConfigDir | Out-Null
$env:PIP_CACHE_DIR = $cacheDir
$env:TMP = $tmpDir
$env:TEMP = $tmpDir
$env:PYINSTALLER_CONFIG_DIR = $pyinstallerConfigDir

$venvDir = Join-Path $root ".venv"
$pyvenvCfg = Join-Path $venvDir "pyvenv.cfg"
$needsRecreate = $false

if (Test-Path $pyvenvCfg) {
  $cfgText = Get-Content $pyvenvCfg -Raw
  if ($cfgText -match "include-system-site-packages\s*=\s*true") {
    $needsRecreate = $true
  }
}

if ($needsRecreate -and (Test-Path $venvDir)) {
  Remove-Item -Path $venvDir -Recurse -Force
}

if (-not (Test-Path $venvDir)) {
  python -m venv $venvDir
}

$py = Join-Path $venvDir "Scripts\\python.exe"
& $py -m pip install -U pip
& $py -m pip install -r (Join-Path $root "requirements.txt")

$distDir = Join-Path $root "release"
$workDir = Join-Path $root "build\\pyinstaller"

& $py -m PyInstaller `
  -y `
  --noconsole `
  --onefile `
  --name DingMailSender `
  --distpath $distDir `
  --workpath $workDir `
  --paths (Join-Path $root "src") `
  .\\dingmail_gui.py

if ($LASTEXITCODE -ne 0) {
  throw "PyInstaller failed with exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host ("Build OK: " + (Join-Path $distDir "DingMailSender.exe"))
