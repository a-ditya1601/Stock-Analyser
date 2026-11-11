$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

Write-Host "Stopping container..." -ForegroundColor Cyan
docker compose down | Out-Null

$stillRunning = docker ps -q -f "name=^chart-analyser-app$"
if ($stillRunning) {
    Write-Host "Found a standalone chart-analyser container, removing it..." -ForegroundColor Yellow
    docker rm -f chart-analyser-app | Out-Null
}

Write-Host "Container stopped." -ForegroundColor Green
