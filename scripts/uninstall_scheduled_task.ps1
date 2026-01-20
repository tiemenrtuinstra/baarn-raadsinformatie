# Baarn Raadsinformatie - Uninstall Scheduled Task
# Verwijdert de Windows Scheduled Task
#
# Uitvoeren als Administrator:
#   powershell -ExecutionPolicy Bypass -File uninstall_scheduled_task.ps1

$TaskName = "BaarnRaadsinformatieSync"

Write-Host "Verwijderen van scheduled task '$TaskName'..." -ForegroundColor Yellow

$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existingTask) {
    # Stop if running
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

    # Unregister
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false

    Write-Host "Task '$TaskName' verwijderd." -ForegroundColor Green
} else {
    Write-Host "Task '$TaskName' niet gevonden." -ForegroundColor Yellow
}
