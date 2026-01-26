@echo off
REM Baarn Raadsinformatie - Windows Installer
REM Dit script start de PowerShell installer met de juiste rechten

echo.
echo   Baarn Raadsinformatie - Windows Installer
echo   ==========================================
echo.

REM Check of PowerShell beschikbaar is
where powershell >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [FOUT] PowerShell niet gevonden. Installeer Windows PowerShell.
    pause
    exit /b 1
)

REM Check voor administrator rechten
net session >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [INFO] Dit script vereist administrator rechten voor Docker installatie.
    echo [INFO] Het script wordt opnieuw gestart als administrator...
    echo.

    REM Herstart als administrator
    powershell -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

REM Voer PowerShell script uit
echo [INFO] PowerShell installer starten...
echo.

powershell -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*

if %ERRORLEVEL% neq 0 (
    echo.
    echo [FOUT] Installatie gefaald. Zie bovenstaande foutmeldingen.
    pause
    exit /b 1
)

pause
