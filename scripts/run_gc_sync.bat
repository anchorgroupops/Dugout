@echo off
:: Dugout GC App Auto-Sync
:: Requires BlueStacks to be running with emulator-5554 connected.
:: Scrapes schedule, team stats, and opponent stats from GC app.

set REPO=H:\Repos\Personal\Softball
set LOG=%REPO%\logs\gc_sync_task.log

echo [%date% %time%] Starting GC sync... >> "%LOG%"

:: Path A (new): web-mobile box score ingest (no emulator required)
cd /d "%REPO%"
python tools\gc_web_mobile_scraper.py --max-games 8 >> "%LOG%" 2>&1
if %errorlevel% neq 0 (
    echo [%date% %time%] Web-mobile box score ingest reported non-zero. >> "%LOG%"
)

:: Check if BlueStacks ADB device is available
"C:\Program Files\BlueStacks_nxt\HD-Adb.exe" -s emulator-5554 get-state >nul 2>&1
if %errorlevel% neq 0 (
    echo [%date% %time%] BlueStacks emulator-5554 not available. App scrape skipped; web ingest already attempted. >> "%LOG%"
    exit /b 0
)

:: Path B (existing): app automation scrape via BlueStacks
cd /d "%REPO%\tools"
python gc_app_auto.py >> "%LOG%" 2>&1

echo [%date% %time%] GC sync complete. >> "%LOG%"
