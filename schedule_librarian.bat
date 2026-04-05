@echo off
REM ============================================================
REM  The Librarian — Windows Task Scheduler Setup
REM  Run once as Administrator to register daily sync tasks.
REM  Usage: schedule_librarian.bat [install|remove|status|run]
REM ============================================================

set "TASK_SYNC=NotebookLM Librarian Sync"
set "TASK_DEDUP=NotebookLM Librarian Dedup"
set "SCRIPT_DIR=%~dp0"

REM Find Python — try known MS Store path first, fall back to PATH
set "PYTHON=C:\Users\joely\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0\LocalCache\local-packages\Python312\Scripts\python.exe"
if not exist "%PYTHON%" (
    set "PYTHON=python"
)

if /i "%1"=="remove" goto REMOVE
if /i "%1"=="status" goto STATUS
if /i "%1"=="run"    goto RUN

:INSTALL
echo.
echo [Librarian] Installing scheduled tasks...
echo.

REM Daily sync at 6:00 AM
schtasks /Create ^
  /TN "%TASK_SYNC%" ^
  /TR "\"%PYTHON%\" \"%SCRIPT_DIR%batch_sync.py\"" ^
  /SC DAILY /ST 06:00 ^
  /RU "%USERNAME%" ^
  /F
if %ERRORLEVEL% EQU 0 (
    echo [OK]   %TASK_SYNC% — runs daily at 06:00
) else (
    echo [FAIL] Could not create sync task. Run as Administrator?
)

REM Weekly dedup on Sunday at 07:00
schtasks /Create ^
  /TN "%TASK_DEDUP%" ^
  /TR "\"%PYTHON%\" \"%SCRIPT_DIR%dedup_notebook.py\"" ^
  /SC WEEKLY /D SUN /ST 07:00 ^
  /RU "%USERNAME%" ^
  /F
if %ERRORLEVEL% EQU 0 (
    echo [OK]   %TASK_DEDUP% — runs every Sunday at 07:00
) else (
    echo [FAIL] Could not create dedup task. Run as Administrator?
)

echo.
echo [Librarian] Done. Verify with: schedule_librarian.bat status
goto END

:REMOVE
echo.
echo [Librarian] Removing scheduled tasks...
schtasks /Delete /TN "%TASK_SYNC%"  /F 2>nul && echo [OK] Removed: %TASK_SYNC%  || echo [INFO] Not found: %TASK_SYNC%
schtasks /Delete /TN "%TASK_DEDUP%" /F 2>nul && echo [OK] Removed: %TASK_DEDUP% || echo [INFO] Not found: %TASK_DEDUP%
goto END

:STATUS
echo.
echo [Librarian] Task status:
schtasks /Query /TN "%TASK_SYNC%"  /FO LIST 2>nul || echo   %TASK_SYNC%: NOT INSTALLED
echo.
schtasks /Query /TN "%TASK_DEDUP%" /FO LIST 2>nul || echo   %TASK_DEDUP%: NOT INSTALLED
goto END

:RUN
echo.
echo [Librarian] Triggering sync now...
schtasks /Run /TN "%TASK_SYNC%" 2>nul || (
    echo Task not installed. Running directly...
    "%PYTHON%" "%SCRIPT_DIR%batch_sync.py"
)
goto END

:END
echo.
