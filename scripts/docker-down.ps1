[CmdletBinding()]
param(
    [switch]$PurgeData,

    [ValidatePattern("^[a-z0-9][a-z0-9_-]{0,62}$")]
    [string]$ProjectName = "agent-studio"
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$exitCode = 0

try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker CLI is not installed or not available on PATH."
    }
    & docker info --format "{{.ServerVersion}}" *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker daemon is not available. Start Docker Desktop or Docker Engine and retry."
    }

    Push-Location $repositoryRoot
    try {
        $composeArguments = @(
            "compose",
            "--project-name", $ProjectName,
            "-f", "compose.yaml",
            "-f", "compose.deepseek.yaml",
            "-f", "compose.openai.yaml",
            "down",
            "--remove-orphans"
        )
        if ($PurgeData) {
            Write-Warning "This permanently deletes the $ProjectName PostgreSQL, RAG, and runtime-secret volumes."
            $confirmation = Read-Host "Type PURGE $ProjectName to continue"
            if ($confirmation -cne "PURGE $ProjectName") {
                throw "Data purge cancelled. No volumes were deleted."
            }
            $composeArguments += "--volumes"
        }

        & docker @composeArguments
        if ($LASTEXITCODE -ne 0) {
            throw "Docker Compose shutdown failed."
        }
        if ($PurgeData) {
            Write-Output "Agent Studio stopped and project data volumes were deleted."
        }
        else {
            Write-Output "Agent Studio stopped. PostgreSQL and RAG data volumes were preserved."
        }
    }
    finally {
        Pop-Location
    }
}
catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    $exitCode = 1
}

exit $exitCode
