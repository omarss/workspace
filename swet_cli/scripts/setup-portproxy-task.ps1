# Create a Windows Scheduled Task that auto-updates portproxy rules
# on login and every hour thereafter.
# Must be run ONCE as Administrator to register the task.
#
# Usage (PowerShell Admin):
#   .\scripts\setup-portproxy-task.ps1

$scriptPath = Join-Path $PSScriptRoot "update-portproxy.ps1"
$taskName = "WSL-PortProxy"

# Remove existing task if present
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$scriptPath`""

# Trigger 1: at user logon + 15s delay (wait for WSL to start)
$logonTrigger = New-ScheduledTaskTrigger -AtLogOn
$logonTrigger.Delay = "PT15S"

# Trigger 2: every hour (repetition via daily trigger with 1h interval)
$hourlyTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Hours 1) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

$principal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -RunLevel Highest

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger @($logonTrigger, $hourlyTrigger) `
    -Settings $settings `
    -Principal $principal `
    -Description "Auto-update netsh portproxy rules to WSL2 dynamic IP on login and every hour"

Write-Host ""
Write-Host "Scheduled task '$taskName' registered."
Write-Host "Triggers: at logon (15s delay) + every hour."
Write-Host ""
Write-Host "To run it now:  schtasks /run /tn $taskName"
Write-Host "To check it:    schtasks /query /tn $taskName"
