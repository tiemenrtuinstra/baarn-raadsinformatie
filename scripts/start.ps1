#Requires -Version 5.1
<#
.SYNOPSIS
    Start Baarn Raadsinformatie services
.DESCRIPTION
    Start de API server en sync service
#>

param(
    [switch]$ApiOnly,
    [switch]$SyncOnly,
    [switch]$Logs,
    [switch]$Stop,
    [switch]$Restart
)

$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot

try {
    if ($Stop) {
        Write-Host "Services stoppen..." -ForegroundColor Cyan
        docker compose down
        Write-Host "Services gestopt" -ForegroundColor Green
    }
    elseif ($Restart) {
        Write-Host "Services herstarten..." -ForegroundColor Cyan
        docker compose restart
        Write-Host "Services herstart" -ForegroundColor Green
    }
    elseif ($Logs) {
        Write-Host "Logs bekijken (Ctrl+C om te stoppen)..." -ForegroundColor Cyan
        docker compose logs -f
    }
    elseif ($ApiOnly) {
        Write-Host "API server starten..." -ForegroundColor Cyan
        docker compose up -d api-server
        Write-Host ""
        Write-Host "API Server: http://localhost:8000" -ForegroundColor Yellow
        Write-Host "API Docs:   http://localhost:8000/docs" -ForegroundColor Yellow
    }
    elseif ($SyncOnly) {
        Write-Host "Sync service starten..." -ForegroundColor Cyan
        docker compose up -d sync-service
        Write-Host "Sync service gestart" -ForegroundColor Green
    }
    else {
        Write-Host "Alle services starten..." -ForegroundColor Cyan
        docker compose up -d api-server sync-service
        Write-Host ""
        Write-Host "API Server: http://localhost:8000" -ForegroundColor Yellow
        Write-Host "API Docs:   http://localhost:8000/docs" -ForegroundColor Yellow
        Write-Host ""
        docker compose ps
    }
}
finally {
    Pop-Location
}
