#!/usr/bin/env pwsh
# Baarn Raadsinformatie - Complete Rebuild Script
# Dit script ruimt alles op en bouwt de Docker images opnieuw

$ErrorActionPreference = "Continue"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Baarn Raadsinformatie - Complete Rebuild" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 1. Stop Docker Compose services
Write-Host "[1/6] Stopping Docker Compose services..." -ForegroundColor Yellow
Set-Location $ProjectDir
docker compose down --remove-orphans 2>$null

# 2. Kill any running baarn containers
Write-Host "[2/6] Killing all baarn containers..." -ForegroundColor Yellow
$containers = docker ps -a --filter "name=baarn" --format "{{.ID}}" 2>$null
if ($containers) {
    docker rm -f $containers 2>$null
}
$containers = docker ps -a --filter "ancestor=baarn-raadsinformatie" --format "{{.ID}}" 2>$null
if ($containers) {
    docker rm -f $containers 2>$null
}
Write-Host "   Containers removed" -ForegroundColor Green

# 3. Remove Docker images
Write-Host "[3/6] Removing Docker images..." -ForegroundColor Yellow
docker rmi baarn-raadsinformatie:latest 2>$null
docker rmi baarn-politiek-mcp-api-server:latest 2>$null
docker rmi baarn-politiek-mcp-sync-service:latest 2>$null
docker rmi baarn-raadsinformatie-api:latest 2>$null
docker rmi baarn-raadsinformatie-sync:latest 2>$null
Write-Host "   Images removed" -ForegroundColor Green

# 4. Clean Docker build cache
Write-Host "[4/6] Cleaning Docker build cache..." -ForegroundColor Yellow
docker builder prune -f 2>$null
Write-Host "   Build cache cleaned" -ForegroundColor Green

# 5. Rebuild images from scratch
Write-Host "[5/6] Rebuilding Docker images (this may take a few minutes)..." -ForegroundColor Yellow
docker compose build --no-cache
if ($LASTEXITCODE -ne 0) {
    Write-Host "   ERROR: Docker build failed!" -ForegroundColor Red
    exit 1
}
Write-Host "   Images rebuilt successfully" -ForegroundColor Green

# 6. Start services
Write-Host "[6/6] Starting services..." -ForegroundColor Yellow
docker compose up -d
if ($LASTEXITCODE -ne 0) {
    Write-Host "   ERROR: Failed to start services!" -ForegroundColor Red
    exit 1
}
Write-Host "   Services started" -ForegroundColor Green

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Rebuild Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "1. Restart Claude Desktop completely (Exit from System Tray)" -ForegroundColor White
Write-Host "2. Wait a few seconds for the MCP server to initialize" -ForegroundColor White
Write-Host "3. Check if baarn-raadsinformatie shows green in Claude Desktop" -ForegroundColor White
Write-Host ""
Write-Host "To verify the MCP server works, run:" -ForegroundColor Yellow
Write-Host "  docker compose logs -f" -ForegroundColor White
Write-Host ""

# Show container status
Write-Host "Current container status:" -ForegroundColor Yellow
docker ps --filter "name=baarn" --format "table {{.Names}}\t{{.Status}}"
