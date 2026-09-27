@echo off
setlocal EnableExtensions
REM Start the CoCo 3 MCP server on localhost. Any program can call it.
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
if exist "%ROOT%\.python\python.exe" (
  set "PY=%ROOT%.python\python.exe"
) else (
  set "PY=python"
)
cd /d "%ROOT%"
"%PY%" -m coco3_mcp.serve
exit /b %ERRORLEVEL%
