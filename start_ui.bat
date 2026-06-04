@echo off
:: Hermes Sales Operator — Mini-UI starten
:: Oeffnet http://127.0.0.1:8767 im Browser

setlocal
cd /d "%~dp0"
set PYTHONUTF8=1

python --version >nul 2>&1
if errorlevel 1 (
    echo FEHLER: Python nicht gefunden. Bitte Python 3.10+ installieren.
    pause
    exit /b 1
)

echo Mini-UI startet auf http://127.0.0.1:8767 ...
python product\ui\server.py

pause
