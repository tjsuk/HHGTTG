@echo off
rem The Hitchhiker's Guide: one-click start.
rem Sets up the virtual environment on first run, rebuilds the database,
rem opens your browser and starts the Flask server. Close this window to stop.
rem
rem "@echo off" stops Windows printing every command before it runs it.

rem setlocal keeps variables set here (like PORT) from leaking into the
rem command prompt that ran this file.
setlocal

rem %~dp0 is the folder this .bat file is in. Changing to it means the relative
rem paths below (.venv, data\build_db.py, app) work even when the file is
rem double-clicked from Explorer or run from another folder. /d also switches drive.
cd /d "%~dp0"
set PORT=5000

rem "where" looks for python on the PATH. ">nul 2>nul" hides its output;
rem we only care whether it succeeded, which "if errorlevel 1" checks.
where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found. Install Python 3.10 or newer from https://www.python.org and try again.
    pause
    exit /b 1
)

rem A virtual environment keeps this project's packages separate from any
rem other Python projects. It only needs creating once.
rem "|| goto :failed" jumps to the error message if the command fails.
if not exist ".venv\Scripts\python.exe" (
    echo Setting up the virtual environment. This only happens once...
    python -m venv .venv || goto :failed
)

rem Install Flask only if it is missing, so normal starts are quick and work offline.
rem Every command uses the venv's own python.exe directly, so there is no need
rem to "activate" the environment first.
".venv\Scripts\python.exe" -c "import flask" 2>nul
if errorlevel 1 (
    echo Installing Flask...
    ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt || goto :failed
)

rem Rebuild the database every time, so edits to the text files in data\ show
rem up without a separate step. It takes well under a second.
echo Building the Guide database...
".venv\Scripts\python.exe" data\build_db.py || goto :failed

echo.
echo  DON'T PANIC. The Guide is at http://127.0.0.1:%PORT%
echo  Close this window, or press Ctrl+C, to stop it.
echo.

rem Open the browser before starting the server, because the server keeps
rem running in this window and nothing after it would run until it stops.
rem The empty "" is the window title that "start" expects before a URL.
rem The page may need a moment to load while the server finishes starting.
start "" "http://127.0.0.1:%PORT%"
".venv\Scripts\python.exe" -m flask --app app run --port %PORT%
goto :eof

rem Shared error exit. "pause" keeps the window open so the message can be read
rem (a double-clicked window would otherwise close straight away).
:failed
echo.
echo Something went wrong. Read the message above, fix it, and run start.bat again.
pause
exit /b 1
