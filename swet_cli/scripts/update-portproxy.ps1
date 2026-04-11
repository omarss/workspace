# Update Windows portproxy rules to forward ports 80/443 to WSL's current IP.
# Must be run as Administrator.
#
# Usage (from PowerShell Admin):
#   .\scripts\update-portproxy.ps1
#
# Or from WSL:
#   powershell.exe -ExecutionPolicy Bypass -File "$(wslpath -w scripts/update-portproxy.ps1)"

$wslIp = (wsl hostname -I).Trim().Split(' ')[0]

if (-not $wslIp) {
    Write-Error "Failed to get WSL IP"
    exit 1
}

Write-Host "WSL IP: $wslIp"

# Remove old rules (ignore errors if they don't exist)
netsh interface portproxy delete v4tov4 listenport=80 listenaddress=0.0.0.0 2>$null
netsh interface portproxy delete v4tov4 listenport=443 listenaddress=0.0.0.0 2>$null

# Add new rules
netsh interface portproxy add v4tov4 listenport=80 listenaddress=0.0.0.0 connectport=80 connectaddress=$wslIp
netsh interface portproxy add v4tov4 listenport=443 listenaddress=0.0.0.0 connectport=443 connectaddress=$wslIp

# Verify
Write-Host ""
Write-Host "Port forwarding rules:"
netsh interface portproxy show v4tov4

# Allow ports through Windows Firewall (idempotent)
$rules = @(
    @{ Name = "WSL2-HTTP";  Port = 80 },
    @{ Name = "WSL2-HTTPS"; Port = 443 }
)
foreach ($r in $rules) {
    $existing = Get-NetFirewallRule -DisplayName $r.Name -ErrorAction SilentlyContinue
    if (-not $existing) {
        New-NetFirewallRule -DisplayName $r.Name -Direction Inbound -Action Allow -Protocol TCP -LocalPort $r.Port | Out-Null
        Write-Host "Created firewall rule: $($r.Name)"
    }
}

Write-Host ""
Write-Host "Done. Forwarding 80/443 -> ${wslIp}:80/443"
