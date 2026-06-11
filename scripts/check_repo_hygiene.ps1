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

$trackedArtifacts = @(git -c core.quotepath=false ls-files -- release "*.spec")
if ($trackedArtifacts.Count -gt 0) {
  Write-Error "Tracked build artifacts are not allowed (release/, *.spec):`n$($trackedArtifacts -join "`n")"
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

$trackedXlsx = @(git -c core.quotepath=false ls-files -- "*.xlsx")
if ($trackedXlsx.Count -gt 0) {
  # 从正则模式去掉转义得到明文子串，避免在本脚本中出现可被自身扫描命中的字面量。
  $xlsxPatterns = ($forbiddenPatterns | ForEach-Object { $_ -replace '\\', '' }) -join ','
  & python (Join-Path $root "scripts\scan_xlsx_sensitive.py") $xlsxPatterns @trackedXlsx
  if ($LASTEXITCODE -ne 0) {
    Write-Error "Sensitive content found in tracked xlsx files."
  }
}

Write-Host "Repository hygiene check passed."
