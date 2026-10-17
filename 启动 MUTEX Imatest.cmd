@echo off
cd /d "%~dp0"
if exist "MUTEX Imatest.exe" (
  start "" "MUTEX Imatest.exe"
) else if exist "dist\MUTEX Imatest 0.7.1\MUTEX Imatest.exe" (
  start "" "dist\MUTEX Imatest 0.7.1\MUTEX Imatest.exe"
) else if exist "dist\MUTEX Imatest\MUTEX Imatest.exe" (
  start "" "dist\MUTEX Imatest\MUTEX Imatest.exe"
) else if exist ".venv\Scripts\pythonw.exe" (
  start "" ".venv\Scripts\pythonw.exe" -m mutex_imatest
) else (
  echo Install the development environment or extract the full portable package first.
  pause
)

