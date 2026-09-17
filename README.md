# To Run the Project

Local only:

    uv run streamlit run .\streamlit_app.py

Reachable from other devices on the same network (fixed port 8501, listens on
every network interface instead of leaving it to Streamlit's defaults):

    .\start.ps1
    .\start.ps1 -Port 8080          # a different port

Other devices then open `http://<this-machine's-IP>:8501` - the script prints
that URL for you. First time only, also allow the port through the firewall
(as Administrator):

    New-NetFirewallRule -DisplayName "Streamlit 8501" -Direction Inbound -Protocol TCP -LocalPort 8501 -Action Allow

If it's still unreachable after that, this machine is likely on a
domain-managed network (Group Policy firewall rules override local ones) -
ask IT to allow inbound TCP 8501, or check for client isolation on the Wi-Fi/LAN.
