$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$env:DINGMAIL_HOME = $root

python .\dingmail_gui.py
