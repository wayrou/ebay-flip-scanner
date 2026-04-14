$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = "python"
$venvPython = Join-Path $scriptDir ".venv\\Scripts\\python.exe"
$logPath = Join-Path $scriptDir "scanner.log"

if (Test-Path $venvPython) {
    $python = $venvPython
}

Set-Location $scriptDir
& $python "src\\app.py" *>> $logPath
