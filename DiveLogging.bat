@echo off
rem Start the NDST Dive Logging App.
rem
rem Finds Python 3.10 or later, sets up the app's libraries if needed (run.py --setup),
rem then starts the app. See WINDOWS_APP_PLAN.md, section 5.
rem
rem Keep this file to finding Python: batch handles paths with spaces and
rem parentheses badly, so everything else is in run.py. Quote every path, and
rem avoid ( ) blocks around lines that expand paths.

setlocal EnableExtensions DisableDelayedExpansion
title Dive Logging App
set "APPDIR=%~dp0"
if defined DIVELOG_HOME goto :have_home
set "DIVELOG_HOME=%LOCALAPPDATA%\DiveLogging"
:have_home
if not exist "%DIVELOG_HOME%\" mkdir "%DIVELOG_HOME%"
set "SAVED=%DIVELOG_HOME%\python.txt"
set "PY="

rem 1. The path saved by a previous run
if not exist "%SAVED%" goto :py_launcher
set "CAND="
set /p CAND=<"%SAVED%"
call :try "%CAND%"
if defined PY goto :found

:py_launcher
rem 2. The Python launcher, which the python.org installer adds
for /f "usebackq delims=" %%P in (`py -3 -c "import sys; print(sys.executable)" 2^>nul`) do call :try "%%P"
if defined PY goto :found

rem 3. python on PATH. Every candidate is run, which skips the Microsoft Store
rem    stand-in in WindowsApps (it opens the Store instead of running Python).
for /f "delims=" %%P in ('where python 2^>nul') do if not defined PY call :try "%%P"
if defined PY goto :found

rem 4. The standard install folders: per-user, then for all users
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if not defined PY call :try "%%~D\python.exe"
if defined PY goto :found
for /d %%D in ("%ProgramFiles%\Python3*") do if not defined PY call :try "%%~D\python.exe"
if defined PY goto :found

:ask
echo.
echo Python 3.10 or later was not found.
echo.
echo Either:
echo   - install Python from https://www.python.org/downloads/windows/ and start the app again.
echo     The per-user install doesn't need administrator rights, and "Add python.exe to PATH"
echo     isn't required; or
echo   - enter the full path to an installed python.exe (or its folder) below.
echo.
set "CAND="
set /p "CAND=Path to python.exe (leave empty to quit): "
if not defined CAND goto :quit
rem Remove quotes, e.g. from Explorer's "Copy as path"
set "CAND=%CAND:"=%"
if exist "%CAND%\python.exe" set "CAND=%CAND%\python.exe"
call :try "%CAND%"
if defined PY goto :found
echo.
echo That isn't a working Python 3.10 or later: %CAND%
goto :ask

:found
rem Remember it for next time
>"%SAVED%" echo %PY%
rem pythonw.exe starts the app without a console window
for %%I in ("%PY%") do set "PYW=%%~dpIpythonw.exe"
if not exist "%PYW%" set "PYW=%PY%"

rem Set up or update the libraries. Quick when nothing has changed.
"%PY%" "%APPDIR%run.py" --setup
if errorlevel 2 goto :setup_failed
if errorlevel 1 pause

start "" "%PYW%" "%APPDIR%run.py" %*
endlocal
exit /b 0

:setup_failed
echo.
pause
endlocal
exit /b 1

:quit
endlocal
exit /b 1

rem Set PY to %1 if it runs and is Python 3.10 or later.
:try
if "%~1"=="" exit /b 1
if not exist "%~1" exit /b 1
"%~1" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 exit /b 1
set "PY=%~1"
exit /b 0
