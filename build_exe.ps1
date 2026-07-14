param(
  [ValidatePattern('^[A-Za-z0-9._-]+$')]
  [string]$ArtifactBaseName = "DingMailSender"
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$pythonCommand = "python"
$pythonPrefix = @()
$currentPythonVersion = (& python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null).Trim()
if ($LASTEXITCODE -ne 0 -or $currentPythonVersion -ne "3.12") {
  if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python 3.12 is required to build DingMailSender"
  }
  $pythonCommand = "py"
  $pythonPrefix = @("-3.12")
}

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
$venvPython = Join-Path $venvDir "Scripts\\python.exe"
$needsRecreate = $false

if (Test-Path $pyvenvCfg) {
  $cfgText = Get-Content $pyvenvCfg -Raw
  if (
    $cfgText -match "include-system-site-packages\s*=\s*false" -or
    $cfgText -notmatch "(?m)^version\s*=\s*3\.12\."
  ) {
    $needsRecreate = $true
  }
}

if ((Test-Path -LiteralPath $pyvenvCfg) -and -not $needsRecreate) {
  if (-not (Test-Path -LiteralPath $venvPython)) {
    $needsRecreate = $true
  } else {
    & $venvPython -m pip --version *> $null
    if ($LASTEXITCODE -ne 0) {
      $needsRecreate = $true
    }
  }
}

if ($needsRecreate -and (Test-Path $venvDir)) {
  $resolvedRoot = (Resolve-Path -LiteralPath $root).Path.TrimEnd('\')
  $resolvedVenv = (Resolve-Path -LiteralPath $venvDir).Path
  if (-not $resolvedVenv.StartsWith("$resolvedRoot\", [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to recreate virtual environment outside repository root: $resolvedVenv"
  }
  Remove-Item -LiteralPath $resolvedVenv -Recurse -Force
}

if (-not (Test-Path $venvDir)) {
  & $pythonCommand @pythonPrefix -m venv --system-site-packages $venvDir
  if ($LASTEXITCODE -ne 0) {
    throw "Unable to create Python 3.12 virtual environment"
  }
}

$py = Join-Path $venvDir "Scripts\\python.exe"
& $py -m pip --version *> $null
if ($LASTEXITCODE -ne 0) {
  & $py -m ensurepip --upgrade
}
& $py -m pip install -U pip
$constraints = Join-Path $root "constraints.txt"
if (Test-Path $constraints) {
  & $py -m pip install -r (Join-Path $root "requirements.txt") -c $constraints
} else {
  & $py -m pip install -r (Join-Path $root "requirements.txt")
}

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
$exePath = Join-Path $distDir "DingMailSender.exe"
$artifactPath = Join-Path $distDir "$ArtifactBaseName.exe"
if ($artifactPath -ne $exePath) {
  if (Test-Path -LiteralPath $artifactPath) {
    Remove-Item -LiteralPath $artifactPath -Force
  }
  Move-Item -LiteralPath $exePath -Destination $artifactPath
  $exePath = $artifactPath
}
$hashPath = "$exePath.sha256"
$hash = Get-FileHash -Algorithm SHA256 -LiteralPath $exePath
("{0}  {1}" -f $hash.Hash.ToLowerInvariant(), (Split-Path -Leaf $exePath)) |
  Set-Content -LiteralPath $hashPath -Encoding ascii

Write-Host ("Build OK: " + $exePath)
Write-Host ("SHA256: " + $hashPath)
