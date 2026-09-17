# Launch the HPC39 dashboard on a fixed port/address, reachable from any
# device on the same network - not left to Streamlit's defaults.
#
#   .\start.ps1              # port 8501 (default)
#   .\start.ps1 -Port 8080   # a different port
#
# First-time network access also needs an inbound firewall rule (run once,
# as Administrator):
#   New-NetFirewallRule -DisplayName "Streamlit 8501" -Direction Inbound -Protocol TCP -LocalPort 8501 -Action Allow

param(
    [int]$Port = 8501
)

$ip = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
    Select-Object -First 1 -ExpandProperty IPAddress

Write-Host ""
Write-Host "Starting HPC39 dashboard on port $Port ..." -ForegroundColor Cyan
Write-Host "  On this machine : http://localhost:$Port"
if ($ip) {
    Write-Host "  On the network  : http://${ip}:$Port"  -ForegroundColor Green
} else {
    Write-Host "  On the network  : http://<this-machine's-IP>:$Port  (run 'ipconfig' to find it)"
}
Write-Host ""

uv run streamlit run streamlit_app.py --server.port $Port --server.address 0.0.0.0
