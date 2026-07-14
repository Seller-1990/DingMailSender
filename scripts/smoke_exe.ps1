param(
  [ValidatePattern('^[A-Za-z0-9._-]+$')]
  [string]$ArtifactBaseName = "DingMailSender"
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

$exePath = Join-Path $root "release\$ArtifactBaseName.exe"
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

$resolvedExePath = (Resolve-Path -LiteralPath $exePath).Path
$existingProcessIds = @(
  Get-CimInstance Win32_Process |
    Where-Object { $_.ExecutablePath -eq $resolvedExePath } |
    ForEach-Object { $_.ProcessId }
)
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
  $smokeProcesses = @(
    Get-CimInstance Win32_Process |
      Where-Object {
        $_.ExecutablePath -eq $resolvedExePath -and
        $_.ProcessId -notin $existingProcessIds
      }
  )
  foreach ($smokeProcess in $smokeProcesses) {
    Stop-Process -Id $smokeProcess.ProcessId -Force -ErrorAction SilentlyContinue
  }
  Start-Sleep -Milliseconds 500
  $remainingProcessIds = @(
    Get-CimInstance Win32_Process |
      Where-Object {
        $_.ExecutablePath -eq $resolvedExePath -and
        $_.ProcessId -notin $existingProcessIds
      } |
      ForEach-Object { $_.ProcessId }
  )
  if ($remainingProcessIds.Count -gt 0) {
    throw "Smoke process cleanup failed: $($remainingProcessIds -join ', ')"
  }
}
