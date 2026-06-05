@echo off
:: Rebellsystem Sales Operator — Start-Script
:: Kein hardcodierter Pfad. Läuft aus dem product/-Ordner heraus.

setlocal
cd /d "%~dp0"
set PYTHONUTF8=1

:: Python-Version prüfen
python --version >nul 2>&1
if errorlevel 1 (
    echo FEHLER: Python nicht gefunden. Bitte Python 3.10+ installieren.
    pause
    exit /b 1
)

:: Config prüfen — bei fehlendem Config Onboarding starten
if not exist "product_config.json" (
    echo.
    echo  Willkommen bei Rebellsystem Sales Operator.
    echo  Erste Einrichtung wird gestartet...
    echo.
    python setup\onboarding.py
    if errorlevel 1 (
        echo.
        echo FEHLER: Einrichtung abgebrochen oder fehlgeschlagen.
        echo Bitte erneut versuchen oder product_config.example.json manuell anpassen.
        pause
        exit /b 1
    )
    echo.
)

:: Installations-Check (schnell, nicht blockierend)
python ..\product\packaging\check_install.py >nul 2>&1
if errorlevel 1 (
    echo.
    echo  Installations-Pruefung:
    python ..\product\packaging\check_install.py
    echo.
)

echo Rebellsystem Sales Operator startet...
python telegram\bot.py

pause
