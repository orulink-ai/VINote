$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $projectRoot
try {
    & yarn dev @args
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
