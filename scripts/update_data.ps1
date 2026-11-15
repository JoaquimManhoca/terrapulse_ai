# Update IMERG observations, retrain the model and sync Supabase.
# Schedule this script with Windows Task Scheduler (see docs/DADOS.md).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$python = Join-Path $root ".venv\Scripts\python.exe"
$log = Join-Path $root "data\update_data.log"
& $python "scripts\update_data.py" @args *>> $log
exit $LASTEXITCODE
