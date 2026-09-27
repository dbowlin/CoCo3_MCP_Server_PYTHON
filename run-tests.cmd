@echo off
setlocal
set "ROOT=%~dp0"
if exist "%ROOT%.python\python.exe" (
  set "PY=%ROOT%.python\python.exe"
) else (
  set "PY=python"
)
cd /d "%ROOT%"
"%PY%" -m unittest discover -s tests -p "test_*.py" -v
exit /b %ERRORLEVEL%
