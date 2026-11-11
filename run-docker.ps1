param(
    [switch]$Rebuild
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

Write-Host "Checking Docker..." -ForegroundColor Cyan
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker CLI is not available. Install Docker Desktop and re-open terminal."
}

docker info *> $null

$existingStandalone = docker ps -aq -f "name=^chart-analyser-app$"
if ($existingStandalone) {
    Write-Host "Removing existing container chart-analyser-app to avoid name conflict..." -ForegroundColor Yellow
    docker rm -f chart-analyser-app | Out-Null
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example" -ForegroundColor Yellow
}

$upArgs = @("compose", "up", "-d")
if ($Rebuild) {
    $upArgs += "--build"
}

Write-Host "Starting container with docker compose..." -ForegroundColor Cyan
docker @upArgs

$healthUrl = "http://127.0.0.1:8000/api/health"
$deadline = (Get-Date).AddSeconds(90)
$healthy = $false

while ((Get-Date) -lt $deadline) {
    try {
        $resp = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 5
        if ($resp.status -eq "ok") {
            $healthy = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 2
    }
}

if (-not $healthy) {
    Write-Host "Health check failed. Recent logs:" -ForegroundColor Red
    docker compose logs --tail=100
    exit 1
}

Write-Host "App is up." -ForegroundColor Green
Write-Host "Web:    http://127.0.0.1:8000"
Write-Host "Health: http://127.0.0.1:8000/api/health"
