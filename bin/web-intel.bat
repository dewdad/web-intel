@echo off
:: web-intel wrapper for Windows — resolves its own location so it works from any CWD.
:: Usage: \path\to\web-intel\bin\web-intel.bat search "query"
setlocal

:: Resolve the skill directory (parent of bin\)
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
for %%i in ("%SCRIPT_DIR%\..") do set "SKILL_DIR=%%~fi"

:: Find a working python (prefer 3.11-3.13 over 3.14+ for dep compat)
set "PYTHON="
for %%v in (python3.13 python3.12 python3.11 python3 python) do (
    if not defined PYTHON (
        where %%v >nul 2>&1
        if not errorlevel 1 set "PYTHON=%%v"
    )
)

if not defined PYTHON (
    echo ERROR: python3 not found. Install Python 3.11+ >&2
    exit /b 1
)

"%PYTHON%" "%SKILL_DIR%\scripts\web.py" %*
