# Baarn Raadsinformatie - Install Scheduled Task
# Dit script installeert een Windows Scheduled Task die de sync service
# automatisch start bij system boot.
#
# Uitvoeren als Administrator:
#   powershell -ExecutionPolicy Bypass -File install_scheduled_task.ps1

$ErrorActionPreference = "Stop"

# Configuration
$TaskName = "BaarnRaadsinformatieSync"
$TaskDescription = "Synchroniseert politieke documenten van gemeente Baarn via Notubiz"
$ProjectPath = Split-Path -Parent $PSScriptRoot
$PythonPath = "python"  # Of volledig pad naar python.exe

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Baarn Raadsinformatie - Task Installer" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if running as admin
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "ERROR: Dit script moet als Administrator worden uitgevoerd!" -ForegroundColor Red
    Write-Host "Rechtermuisklik -> 'Als administrator uitvoeren'" -ForegroundColor Yellow
    exit 1
}

# Check if task already exists
$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existingTask) {
    Write-Host "Task '$TaskName' bestaat al." -ForegroundColor Yellow
    $response = Read-Host "Wil je de bestaande task vervangen? (j/n)"
    if ($response -ne "j") {
        Write-Host "Installatie afgebroken." -ForegroundColor Yellow
        exit 0
    }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Bestaande task verwijderd." -ForegroundColor Green
}

# Create the action
$Action = New-ScheduledTaskAction `
    -Execute $PythonPath `
    -Argument "sync_service.py" `
    -WorkingDirectory $ProjectPath

# Create the trigger (at system startup + daily at 6:00)
$TriggerStartup = New-ScheduledTaskTrigger -AtStartup
$TriggerDaily = New-ScheduledTaskTrigger -Daily -At "06:00"

# Create settings
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0)  # Geen tijdslimiet

# Create principal (run as current user)
$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

# Register the task
try {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Description $TaskDescription `
        -Action $Action `
        -Trigger $TriggerStartup, $TriggerDaily `
        -Settings $Settings `
        -Principal $Principal

    Write-Host ""
    Write-Host "SUCCESS: Scheduled Task geinstalleerd!" -ForegroundColor Green
    Write-Host ""
    Write-Host "De sync service zal nu:" -ForegroundColor Cyan
    Write-Host "  - Starten bij Windows startup" -ForegroundColor White
    Write-Host "  - Dagelijks om 06:00 draaien" -ForegroundColor White
    Write-Host ""
    Write-Host "Beheer via:" -ForegroundColor Cyan
    Write-Host "  - Task Scheduler (taskschd.msc)" -ForegroundColor White
    Write-Host "  - Of: schtasks /query /tn $TaskName" -ForegroundColor White
    Write-Host ""

    # Ask to start now
    $startNow = Read-Host "Wil je de sync service nu starten? (j/n)"
    if ($startNow -eq "j") {
        Start-ScheduledTask -TaskName $TaskName
        Write-Host "Sync service gestart!" -ForegroundColor Green
    }

} catch {
    Write-Host "ERROR: Kon task niet installeren: $_" -ForegroundColor Red
    exit 1
}
