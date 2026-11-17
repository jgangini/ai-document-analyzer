param(
    [ValidateRange(0, 10000)]
    [int]$MinQuality = 0,

    [ValidateRange(-1, 10000)]
    [int]$MinBackendQuality = -1,

    [ValidateRange(-1, 10000)]
    [int]$MinFrontendQuality = -1,

    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$ErrorActionPreference = "Stop"

if ($MinBackendQuality -lt 0) {
    $MinBackendQuality = $MinQuality
}

if ($MinFrontendQuality -lt 0) {
    $MinFrontendQuality = $MinQuality
}

function New-ProductRules {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RootPath
    )

    $rulesPath = Join-Path $RootPath ".sentrux"
    New-Item -ItemType Directory -Force -Path $rulesPath | Out-Null

    @"
[constraints]
min_quality = 0.0
min_modularity = 0.0
min_acyclicity = 0.0
min_depth = 0.0
min_equality = 0.0
min_redundancy = 0.0

max_cycles = 0
max_cc = 1000
max_fn_lines = 10000
max_file_lines = 200000
max_upward_violations = 0
no_god_files = false
"@ | Set-Content -Encoding UTF8 -Path (Join-Path $rulesPath "rules.toml")
}

function Copy-ProductTree {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourcePath,

        [Parameter(Mandatory = $true)]
        [string]$DestinationPath
    )

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $DestinationPath) | Out-Null

    $robocopyArgs = @(
        $SourcePath,
        $DestinationPath,
        "/E",
        "/XD", "__pycache__", "node_modules", "dist", "build", ".vite",
        "/XF", "*.pyc", "*.pyo",
        "/NFL", "/NDL", "/NJH", "/NJS", "/NC", "/NS"
    )

    & robocopy @robocopyArgs | Out-Null
    if ($LASTEXITCODE -gt 7) {
        throw "robocopy failed for '$SourcePath' with exit code $LASTEXITCODE"
    }
}

function Invoke-ProductSentruxCheck {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,

        [Parameter(Mandatory = $true)]
        [string]$RelativePath,

        [Parameter(Mandatory = $true)]
        [int]$MinimumQuality
    )

    $sourcePath = Join-Path $RepoRoot $RelativePath
    if (-not (Test-Path $sourcePath)) {
        throw "Product path not found: $sourcePath"
    }

    $tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("doc-agent-sentrux-" + $Name + "-" + [guid]::NewGuid().ToString("N"))

    try {
        Copy-ProductTree -SourcePath $sourcePath -DestinationPath $tempRoot
        New-ProductRules -RootPath $tempRoot

        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            $output = & sentrux check $tempRoot 2>&1
            $exitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
        $outputText = ($output | Out-String)

        $qualityMatch = [regex]::Match($outputText, "Quality:\s*(\d+)")
        if (-not $qualityMatch.Success) {
            Write-Host $outputText
            throw "Could not parse Sentrux quality for $Name."
        }

        $quality = [int]$qualityMatch.Groups[1].Value
        $passed = ($exitCode -eq 0) -and ($quality -ge $MinimumQuality)

        [pscustomobject]@{
            Name = $Name
            Path = $RelativePath
            Quality = $quality
            Minimum = $MinimumQuality
            Passed = $passed
            SentruxExitCode = $exitCode
        }
    }
    finally {
        if (Test-Path $tempRoot) {
            Remove-Item -LiteralPath $tempRoot -Recurse -Force
        }
    }
}

$checks = @(
    Invoke-ProductSentruxCheck -Name "backend" -RelativePath "apps\backend\app" -MinimumQuality $MinBackendQuality
    Invoke-ProductSentruxCheck -Name "frontend" -RelativePath "apps\frontend\src" -MinimumQuality $MinFrontendQuality
)

$minimumProductQuality = ($checks | Measure-Object -Property Quality -Minimum).Minimum
$failedChecks = @($checks | Where-Object { -not $_.Passed })

$checks | Format-Table Name, Path, Quality, Minimum, Passed -AutoSize
Write-Host "Product quality floor: $minimumProductQuality"

if ($failedChecks.Count -gt 0) {
    $failedNames = ($failedChecks | ForEach-Object { "$($_.Name)=$($_.Quality) < $($_.Minimum)" }) -join ", "
    throw "Sentrux product check failed: $failedNames"
}
