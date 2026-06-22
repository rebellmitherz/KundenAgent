@echo off
:: Rebellsystem Sales Operator — Mini-UI starten + Browser oeffnen
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1

python --version >nul 2>&1
if errorlevel 1 (
    echo FEHLER: Python nicht gefunden. Bitte Python 3.10+ installieren.
    pause
    exit /b 1
)

echo Rebellsystem UI startet auf http://127.0.0.1:8767 ...
REM Python 3.14 nutzen: hat die Engine-Pakete (ddgs etc.) UND python-dotenv (laedt b2bbot\.env).
REM Sonst: entweder SERPER_API_KEY fehlt (kein dotenv) oder mine.py-enrich bricht (kein ddgs).
start /B "" "C:\Users\micha\AppData\Local\Python\pythoncore-3.14-64\python.exe" product\ui\server.py

timeout /t 2 /nobreak >nul
start http://127.0.0.1:8767

echo Fenster offen lassen — Server laeuft im Hintergrund.
echo Zum Beenden dieses Fenster schliessen.
cmd /k
