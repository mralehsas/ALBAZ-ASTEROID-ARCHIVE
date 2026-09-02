# NASA/JPL connectivity diagnostic for Asteroid Archive v0.7 Final Audited
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
    throw "Python 3 was not found."
}

try {
    $runtime = Resolve-PythonCommand
    Write-Host "Testing CAD, Fireball, SBDB, Sentry, Horizons Lookup and real Horizons vectors sequentially..." -ForegroundColor Cyan
    & $runtime.Command @($runtime.Prefix) .\horizons_engine.py
}
catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
}
Write-Host ""
Read-Host "Press Enter to close"
