# Asteroid Archive v0.7 — Final Audited PowerShell launcher
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
Set-Location -LiteralPath $PSScriptRoot

function Resolve-PythonCommand {
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { return @{ Command = $py.Source; Prefix = @('-3') } }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return @{ Command = $python.Source; Prefix = @() } }
    throw "Python 3 was not found. Install Python and enable Add Python to PATH."
}

try {
    $runtime = Resolve-PythonCommand
    Write-Host "" 
    Write-Host "============================================================" -ForegroundColor DarkCyan
    Write-Host "  Asteroid Archive v0.7.2 - Horizons Fixed / Port-Isolated R1" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor DarkCyan
    Write-Host "Program folder: $PSScriptRoot" -ForegroundColor DarkGray
    & $runtime.Command @($runtime.Prefix) --version
    Write-Host "Starting the local scientific engine on its dedicated port 8872..." -ForegroundColor Green
    Write-Host "Keep this PowerShell window open while using the program." -ForegroundColor Yellow
    Write-Host "Press Ctrl+C to stop the engine." -ForegroundColor DarkGray
    Write-Host ""
    & $runtime.Command @($runtime.Prefix) .\server.py --port 8872
}
catch {
    Write-Host "" 
    Write-Host "STARTUP ERROR" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host ""
    Read-Host "Press Enter to close"
    exit 1
}
