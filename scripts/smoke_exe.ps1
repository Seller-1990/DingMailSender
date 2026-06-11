$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

$exePath = Join-Path $root "release\DingMailSender.exe"
if (-not (Test-Path -LiteralPath $exePath)) {
  throw "Missing release executable: $exePath"
}

$smokeHome = Join-Path $root "build\smoke_home"
if (Test-Path -LiteralPath $smokeHome) {
  Remove-Item -LiteralPath $smokeHome -Recurse -Force
}
New-Item -ItemType Directory -Force $smokeHome | Out-Null

$env:DINGMAIL_HOME = $smokeHome
$env:QT_QPA_PLATFORM = "offscreen"

$proc = Start-Process -FilePath $exePath -PassThru
try {
  # onefile EXE needs several seconds to unpack before the GUI event loop starts.
  Start-Sleep -Seconds 15
  if ($proc.HasExited) {
    throw "EXE exited prematurely with code $($proc.ExitCode)"
  }
  if (-not (Test-Path (Join-Path $smokeHome "packages"))) {
    throw "EXE is running but did not initialize the working directory layout"
  }
  Write-Host "Launch smoke OK: process alive after 15s and workspace initialized."
} finally {
  if (-not $proc.HasExited) {
    Stop-Process -Id $proc.Id -Force
  }
}
