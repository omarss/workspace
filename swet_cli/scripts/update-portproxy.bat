@echo off
for /f "tokens=1" %%i in ('wsl hostname -I') do set WSL_IP=%%i
netsh interface portproxy delete v4tov4 listenport=80 listenaddress=0.0.0.0 2>/dev/null
netsh interface portproxy delete v4tov4 listenport=443 listenaddress=0.0.0.0 2>/dev/null
netsh interface portproxy add v4tov4 listenport=80 listenaddress=0.0.0.0 connectport=80 connectaddress=%WSL_IP%
netsh interface portproxy add v4tov4 listenport=443 listenaddress=0.0.0.0 connectport=443 connectaddress=%WSL_IP%
