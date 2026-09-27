@echo off
setlocal EnableExtensions
REM One step: find Python 3.10+, then register the CoCo 3 MCP server with Cursor.
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

call :find_python
if not defined PY (
  echo Could not find Python 3.10+. >&2
  echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH". >&2
  echo Then run this script again. >&2
  exit /b 1
)

cd /d "%ROOT%"
"%PY%" -m coco3_mcp.activate
exit /b %ERRORLEVEL%

:find_python
REM A normal Python on PATH. The Windows Store alias fails this version check.
where python >nul 2>&1
if not errorlevel 1 (
  python -c "import sys; raise SystemExit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
  if not errorlevel 1 (
    for /f "delims=" %%I in ('python -c "import sys; print(sys.executable)"') do set "PY=%%I"
    if defined PY exit /b 0
  )
)

where py >nul 2>&1
if not errorlevel 1 (
  py -3 -c "import sys; raise SystemExit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
  if not errorlevel 1 (
    for /f "delims=" %%I in ('py -3 -c "import sys; print(sys.executable)"') do set "PY=%%I"
    if defined PY exit /b 0
  )
)

if exist "%ROOT%\.python\python.exe" (
  "%ROOT%\.python\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
  if not errorlevel 1 (
    set "PY=%ROOT%\.python\python.exe"
    exit /b 0
  )
)

if exist "%ROOT%\..\CoCo3_MCP_Server\.python\python.exe" (
  echo Copying a private Python into .python ... >&2
  if not exist "%ROOT%\.python" mkdir "%ROOT%\.python"
  xcopy /E /I /Q /Y "%ROOT%\..\CoCo3_MCP_Server\.python" "%ROOT%\.python\" >nul
  if errorlevel 1 exit /b 0
  > "%ROOT%\.python\python312._pth" (
    echo python312.zip
    echo .
    echo ..
    echo import site
  )
  set "PY=%ROOT%\.python\python.exe"
  exit /b 0
)
exit /b 0
