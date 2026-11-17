$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    if (Test-Path "graphify-out/GRAPH_REPORT.md") {
        Get-Content "graphify-out/GRAPH_REPORT.md" -TotalCount 80
    }

    if (Test-Path ".sentrux/rules.toml") {
        if (Get-Command sentrux -ErrorAction SilentlyContinue) {
            sentrux gate --save .
            sentrux check .
        } else {
            Write-Warning "Sentrux is configured but unavailable."
        }
    }
} finally {
    Pop-Location
}
