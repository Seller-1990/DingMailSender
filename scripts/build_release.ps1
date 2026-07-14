param(
  [Parameter(Mandatory = $true)]
  [ValidatePattern('^v\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$')]
  [string]$Tag,
  [switch]$SkipSmoke
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

& (Join-Path $root "scripts\verify_release_version.ps1") -Tag $Tag
if ($LASTEXITCODE -ne 0) {
  throw "Release version verification failed"
}

$artifactBaseName = "DingMailSender-$Tag-windows-x64"
& (Join-Path $root "build_exe.ps1") -ArtifactBaseName $artifactBaseName
if ($LASTEXITCODE -ne 0) {
  throw "Release build failed"
}

& (Join-Path $root "scripts\audit_release.ps1") -ArtifactBaseName $artifactBaseName
if ($LASTEXITCODE -ne 0) {
  throw "Release audit failed"
}

if (-not $SkipSmoke) {
  & (Join-Path $root "scripts\smoke_exe.ps1") -ArtifactBaseName $artifactBaseName
  if ($LASTEXITCODE -ne 0) {
    throw "Release smoke failed"
  }
}

Write-Host "Release package ready: release\$artifactBaseName.exe"
