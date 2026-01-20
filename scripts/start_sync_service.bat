@echo off
REM Baarn Raadsinformatie - Start Sync Service
REM Dit script start de background sync service

cd /d "%~dp0.."
echo Starting Baarn Raadsinformatie Sync Service...
echo Press Ctrl+C to stop

python sync_service.py
