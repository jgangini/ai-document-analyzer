$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    if (Test-Path "graphify-out/graph.json") {
        if (Get-Command graphify -ErrorAction SilentlyContinue) {
            graphify update .
        } else {
            Write-Warning "Graphify is configured but unavailable."
        }
    }

    if (Test-Path ".sentrux/rules.toml") {
        if (Get-Command sentrux -ErrorAction SilentlyContinue) {
            sentrux check .
            sentrux gate .
        } else {
            Write-Warning "Sentrux is configured but unavailable."
        }
    }
} finally {
    Pop-Location
}
