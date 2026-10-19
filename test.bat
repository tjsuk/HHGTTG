@echo off
rem The Hitchhiker's Guide: run the test suite.
rem Sets up the virtual environment and pytest on first run.
rem Any arguments are passed to pytest, for example:  test.bat -k amazon
rem (See start.bat for an explanation of the setup lines; they work the same way.)

setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found. Install Python 3.10 or newer from https://www.python.org and try again.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Setting up the virtual environment. This only happens once...
    python -m venv .venv || goto :failed
)

rem requirements-dev.txt includes requirements.txt plus pytest, so one install
rem covers both the app and its tests.
".venv\Scripts\python.exe" -c "import flask, pytest" 2>nul
if errorlevel 1 (
    echo Installing Flask and pytest...
    ".venv\Scripts\python.exe" -m pip install --quiet -r requirements-dev.txt || goto :failed
)

rem %* forwards any arguments given to this file on to pytest.
".venv\Scripts\python.exe" -m pytest %*

rem Save pytest's exit code straight away: the next command would overwrite it.
rem 0 means every test passed. It is returned at the end so other tools
rem (a CI server, a script) can tell whether the tests passed.
set RESULT=%errorlevel%
echo.
if %RESULT%==0 (echo All tests passed.) else (echo Some tests failed. See the output above.)
pause
exit /b %RESULT%

:failed
echo.
echo Setup failed. Read the message above, fix it, and run test.bat again.
pause
exit /b 1
