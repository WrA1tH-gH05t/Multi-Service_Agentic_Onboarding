REM Double-click this file to activate the venv and start the server
REM Or run this in PowerShell: .\activate-venv.ps1

cd /d "%~dp0"
if exist "venv\Scripts\python.exe" (
    echo Activating venv...
    "venv\Scripts\python.exe" start.py
) else (
    echo ERROR: venv\Scripts\python.exe not found!
    echo Make sure the venv exists at: %~dp0venv
)
pause
