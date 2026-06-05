@echo off
:: Hermes Sales Operator — Mini-UI starten + Browser oeffnen
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1

python --version >nul 2>&1
if errorlevel 1 (
    echo FEHLER: Python nicht gefunden. Bitte Python 3.10+ installieren.
    pause
    exit /b 1
)

echo Hermes UI startet auf http://127.0.0.1:8767 ...
start /B python product\ui\server.py

timeout /t 2 /nobreak >nul
start http://127.0.0.1:8767

echo Fenster offen lassen — Server laeuft im Hintergrund.
echo Zum Beenden dieses Fenster schliessen.
cmd /k
