[CmdletBinding()]
param(
    [ValidateSet("mock", "deepseek", "openai")]
    [string]$Provider = "mock",

    [ValidateRange(1, 65535)]
    [int]$WebPort = 3000,

    [ValidateRange(1, 65535)]
    [int]$ApiPort = 8000,

    [ValidatePattern("^[a-z0-9][a-z0-9_-]{0,62}$")]
    [string]$ProjectName = "agent-studio"
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$previousWebPort = $env:WEB_PORT
$previousApiPort = $env:API_PORT
$exitCode = 0

function Test-ListeningPort {
    param([int]$Port)

    $listeners = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
    return $null -ne ($listeners | Where-Object { $_.Port -eq $Port } | Select-Object -First 1)
}

try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker CLI is not installed or not available on PATH."
    }

    & docker info --format "{{.ServerVersion}}" *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker daemon is not available. Start Docker Desktop or Docker Engine and retry."
    }

    & docker compose version *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose is not available."
    }

    $requiredFiles = @(
        "compose.yaml",
        "apps/api/Dockerfile",
        "apps/web/Dockerfile"
    )
    foreach ($requiredFile in $requiredFiles) {
        if (-not (Test-Path -LiteralPath (Join-Path $repositoryRoot $requiredFile) -PathType Leaf)) {
            throw "Required Docker runtime file is missing: $requiredFile"
        }
    }

    if ($Provider -eq "deepseek" -and [string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY)) {
        throw "DEEPSEEK_API_KEY is not configured."
    }
    if ($Provider -eq "openai" -and [string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) {
        throw "OPENAI_API_KEY is not configured."
    }

    Push-Location $repositoryRoot
    try {
        $baseComposeArguments = @(
            "compose",
            "--project-name", $ProjectName,
            "-f", "compose.yaml"
        )
        $webContainer = ((@(& docker @baseComposeArguments ps -q web) -join "")).Trim()
        $apiContainer = ((@(& docker @baseComposeArguments ps -q api) -join "")).Trim()
        if ([string]::IsNullOrEmpty($webContainer) -and (Test-ListeningPort -Port $WebPort)) {
            throw "Host port $WebPort is already in use; stop the conflicting service or choose -WebPort."
        }
        if ([string]::IsNullOrEmpty($apiContainer) -and (Test-ListeningPort -Port $ApiPort)) {
            throw "Host port $ApiPort is already in use; stop the conflicting service or choose -ApiPort."
        }

        $composeArguments = [System.Collections.Generic.List[string]]::new()
        foreach ($argument in $baseComposeArguments) {
            $composeArguments.Add($argument)
        }
        if ($Provider -eq "deepseek") {
            $composeArguments.Add("-f")
            $composeArguments.Add("compose.deepseek.yaml")
        }
        elseif ($Provider -eq "openai") {
            $composeArguments.Add("-f")
            $composeArguments.Add("compose.openai.yaml")
        }

        $env:WEB_PORT = $WebPort.ToString([System.Globalization.CultureInfo]::InvariantCulture)
        $env:API_PORT = $ApiPort.ToString([System.Globalization.CultureInfo]::InvariantCulture)

        & docker @composeArguments config --quiet
        if ($LASTEXITCODE -ne 0) {
            throw "Docker Compose configuration validation failed."
        }
        if ($Provider -ne "mock") {
            & docker @composeArguments build secret-init
            if ($LASTEXITCODE -ne 0) {
                throw "Provider secret initializer image build failed."
            }
            $providerKey = if ($Provider -eq "deepseek") {
                $env:DEEPSEEK_API_KEY
            }
            else {
                $env:OPENAI_API_KEY
            }
            $providerKey | & docker @composeArguments run --rm -T --no-deps secret-init `
                python -m app.persistence.runtime_secrets --provider-secret $Provider
            if ($LASTEXITCODE -ne 0) {
                throw "Provider secret initialization failed."
            }
            $providerKey = $null
        }
        $upArguments = @("up", "--build", "--detach", "--wait", "--wait-timeout", "300")
        if ($Provider -ne "mock") {
            $upArguments += "--force-recreate"
        }
        & docker @composeArguments @upArguments
        if ($LASTEXITCODE -ne 0) {
            & docker @baseComposeArguments ps
            throw "Agent Studio containers did not become healthy."
        }

        Write-Output "Agent Studio is ready"
        Write-Output "Web: http://127.0.0.1:$WebPort"
        Write-Output "API: http://127.0.0.1:$ApiPort"
        Write-Output "Provider: $Provider"
        Write-Output "Database: PostgreSQL 17 + pgvector"
    }
    finally {
        Pop-Location
    }
}
catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    $exitCode = 1
}
finally {
    $env:WEB_PORT = $previousWebPort
    $env:API_PORT = $previousApiPort
}

exit $exitCode
