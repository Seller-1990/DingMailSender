param(
  [string]$Tag = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

$previousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = Join-Path $root "src"
try {
  $version = (& python -c "from dingmail import __version__; print(__version__)" 2>&1).Trim()
  if ($LASTEXITCODE -ne 0) {
    throw "Unable to read dingmail.__version__: $version"
  }
} finally {
  $env:PYTHONPATH = $previousPythonPath
}

if ($version -notmatch '^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$') {
  throw "Invalid semantic version: $version"
}

if ($Tag) {
  $expectedTag = "v$version"
  if ($Tag -ne $expectedTag) {
    throw "Release tag/version mismatch. tag=$Tag expected=$expectedTag"
  }
}

Write-Host "Release version OK: $version"
if ($Tag) {
  Write-Host "Release tag OK: $Tag"
}
