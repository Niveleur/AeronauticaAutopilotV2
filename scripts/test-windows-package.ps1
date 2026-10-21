param(
    [Parameter(Mandatory = $true)][string]$PackageDirectory,
    [Parameter(Mandatory = $true)][string]$ReportPath
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $PackageDirectory).Path
$exe = Join-Path $root 'AeronauticaAutopilotV2.exe'
if (!(Test-Path -LiteralPath $exe)) { throw "EXE missing from package: $exe" }

# NumPy 1.24.3's Windows wheel needs this hidden directory. Checking only
# the build output misses upload-artifact's default hidden-file exclusion.
$numpyLibs = Join-Path $root '_internal/numpy/.libs'
$openblas = @(Get-ChildItem -LiteralPath $numpyLibs -Filter '*openblas*.dll' -File)
if ($openblas.Count -eq 0) { throw 'NumPy OpenBLAS DLL missing from the package' }
$core = Join-Path $root '_internal/numpy/core'
$extension = @(Get-ChildItem -LiteralPath $core -Filter '_multiarray_umath*.pyd' -File)
if ($extension.Count -eq 0) { throw 'NumPy C extension missing from the package' }

$reportDirectory = Split-Path -Parent $ReportPath
New-Item -ItemType Directory -Force -Path $reportDirectory | Out-Null
if (Test-Path -LiteralPath $ReportPath) { Remove-Item -LiteralPath $ReportPath }
$previousPath = $env:PATH
try {
    # Test without Python/toolchain folders in PATH and outside the checkout.
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    $process = Start-Process -FilePath $exe -WorkingDirectory $reportDirectory -ArgumentList @('--hud-smoke-test', "`"$ReportPath`"") -PassThru
    if (!$process.WaitForExit(120000)) {
        Stop-Process -Id $process.Id -Force
        throw 'Packaged HUD smoke test timed out'
    }
    if (!(Test-Path -LiteralPath $ReportPath)) { throw 'Packaged HUD smoke report missing' }
    $result = Get-Content -LiteralPath $ReportPath -Raw | ConvertFrom-Json
    Get-Content -LiteralPath $ReportPath
    if ($env:GITHUB_SHA -and $result.build_revision -ne $env:GITHUB_SHA.Substring(0, 7)) {
        throw 'Packaged EXE build identity does not match this workflow'
    }
    if ($process.ExitCode -ne 0 -or !$result.ok -or !$result.frozen) {
        throw 'Packaged Windows HUD smoke test failed'
    }
} finally {
    $env:PATH = $previousPath
}
