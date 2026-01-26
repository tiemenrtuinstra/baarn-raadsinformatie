@echo off
echo ========================================
echo Restarting Docker Desktop
echo ========================================

echo Stopping Docker processes...
taskkill /F /IM "Docker Desktop.exe" 2>nul
taskkill /F /IM "com.docker.backend.exe" 2>nul
taskkill /F /IM "com.docker.service.exe" 2>nul
taskkill /F /IM "dockerd.exe" 2>nul

echo Waiting 5 seconds...
timeout /t 5 /nobreak >nul

echo Starting Docker Desktop...
start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"

echo Waiting 60 seconds for Docker to initialize...
timeout /t 60 /nobreak

echo Testing Docker...
docker version

echo Done! If Docker works, run: rebuild.ps1
