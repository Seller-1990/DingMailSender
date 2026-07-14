param(
  [ValidatePattern('^[A-Za-z0-9._-]+$')]
  [string]$ArtifactBaseName = "DingMailSender"
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

$exePath = Join-Path $root "release\$ArtifactBaseName.exe"
$hashPath = "$exePath.sha256"

if (-not (Test-Path -LiteralPath $exePath)) {
  throw "Missing release executable: $exePath"
}
if (-not (Test-Path -LiteralPath $hashPath)) {
  throw "Missing release checksum: $hashPath"
}

$actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $exePath).Hash.ToLowerInvariant()
$checksumLine = (Get-Content -LiteralPath $hashPath -Encoding ascii | Select-Object -First 1).Trim()
if ($checksumLine -notmatch '^[0-9a-fA-F]{64}\s+\S+$') {
  throw "Invalid checksum file format. Expected: <sha256> <filename>"
}
$expected = ($checksumLine -split '\s+')[0].ToLowerInvariant()
$fileName = ($checksumLine -split '\s+', 2)[1]
if ($fileName -ne "$ArtifactBaseName.exe") {
  throw "Checksum filename mismatch: $fileName"
}
if ($actual -ne $expected) {
  throw "Checksum mismatch. expected=$expected actual=$actual"
}

$size = (Get-Item -LiteralPath $exePath).Length
if ($size -le 0) {
  throw "Release executable is empty"
}

Write-Host "Release audit OK"
Write-Host ("Executable: {0}" -f $exePath)
Write-Host ("Size: {0} bytes" -f $size)
Write-Host ("SHA256: {0}" -f $actual)
