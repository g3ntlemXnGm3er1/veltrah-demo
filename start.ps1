param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$launchArgs = @('run_demo.py')
if (-not $NoBrowser) { $launchArgs += '--open' }
if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 @launchArgs
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python @launchArgs
} else {
    Write-Error 'Python 3.10+ is required. Alternatively open Veltrah_Demo_Offline.html for the browser-only fixture preview.'
    exit 1
}
exit $LASTEXITCODE
