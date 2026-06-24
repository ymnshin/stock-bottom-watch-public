$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path -LiteralPath (Join-Path $ScriptDir "..")
$LogDir = Join-Path $ProjectRoot "logs"
$LogPath = Join-Path $LogDir "stockwatch.log"
$EnvPath = Join-Path $ProjectRoot ".env"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location -LiteralPath $ProjectRoot

function Write-StockWatchLog {
    param([string]$Message)

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $LogPath -Value "[$timestamp] $Message" -Encoding utf8
}

function Set-DotEnvValue {
    param([string]$Line)

    $trimmed = $Line.Trim().TrimStart([char]0xFEFF)
    if ($trimmed.Length -eq 0 -or $trimmed.StartsWith("#")) {
        return
    }

    if ($trimmed.StartsWith("export ")) {
        $trimmed = $trimmed.Substring(7).Trim()
    }

    $separatorIndex = $trimmed.IndexOf("=")
    if ($separatorIndex -lt 1) {
        return
    }

    $name = $trimmed.Substring(0, $separatorIndex).Trim()
    $value = $trimmed.Substring($separatorIndex + 1).Trim()
    if ($name.Length -eq 0) {
        return
    }

    if (
        ($value.Length -ge 2) -and
        (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'")))
    ) {
        $value = $value.Substring(1, $value.Length - 2)
    }

    [Environment]::SetEnvironmentVariable($name, $value, "Process")
}

Write-StockWatchLog "Stock Bottom Watch task started"

if (Test-Path -LiteralPath $EnvPath) {
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false, $true)
    try {
        $envText = [System.IO.File]::ReadAllText($EnvPath, $utf8NoBom)
    } catch {
        $utf8WithBom = New-Object System.Text.UTF8Encoding($true, $true)
        $envText = [System.IO.File]::ReadAllText($EnvPath, $utf8WithBom)
    }

    foreach ($line in ($envText -split "`r?`n")) {
        Set-DotEnvValue -Line $line
    }
} else {
    Write-StockWatchLog ".env not found"
}

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

if ([string]::IsNullOrWhiteSpace($env:DISCORD_WEBHOOK_URL)) {
    Write-StockWatchLog "WEBHOOK_SET=NO"
} else {
    Write-StockWatchLog "WEBHOOK_SET=YES"
}

$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $PythonExe) {
    Write-StockWatchLog "PYTHON=.venv"
    & $PythonExe "src\main.py" 2>&1 | ForEach-Object {
        Add-Content -LiteralPath $LogPath -Value $_ -Encoding utf8
    }
} else {
    Write-StockWatchLog "PYTHON=python"
    & python "src\main.py" 2>&1 | ForEach-Object {
        Add-Content -LiteralPath $LogPath -Value $_ -Encoding utf8
    }
}

$exitCode = $LASTEXITCODE
Write-StockWatchLog "Stock Bottom Watch task finished EXIT_CODE=$exitCode"
exit $exitCode
