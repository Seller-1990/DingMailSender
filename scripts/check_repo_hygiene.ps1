$ErrorActionPreference = "Stop"
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new()
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

$trackedPackages = @(git -c core.quotepath=false ls-files -- packages)
if ($trackedPackages.Count -gt 0) {
  Write-Error "Tracked runtime task package files are not allowed:`n$($trackedPackages -join "`n")"
}

$forbiddenPatterns = @(
  "@zhongtenghr\.com"
)

$trackedFiles = @(git -c core.quotepath=false ls-files | Where-Object {
  $_ -notmatch "^(examples/sample_package/|audit-report-)" -and
  $_ -notmatch "\.(png|jpg|jpeg|gif|ico|xlsx|exe|dll|pyd|pyc)$"
} | ForEach-Object { Join-Path $root $_ })

foreach ($pattern in $forbiddenPatterns) {
  if ($trackedFiles.Count -eq 0) {
    continue
  }
  $matches = @($trackedFiles | ForEach-Object {
    Select-String -LiteralPath $_ -Pattern $pattern -CaseSensitive:$false -ErrorAction SilentlyContinue
  })
  if ($matches.Count -gt 0) {
    $summary = $matches | ForEach-Object { "$($_.Path):$($_.LineNumber): $($_.Line.Trim())" }
    Write-Error "Forbidden sensitive pattern found ($pattern):`n$($summary -join "`n")"
  }
}

Write-Host "Repository hygiene check passed."
