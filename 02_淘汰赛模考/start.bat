@echo off
cd /d "%~dp0"
set "TASK_VENV=%~dp0..\.venv"
where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")
if not exist "%TASK_VENV%\Scripts\python.exe" (
  %PY% -m venv "%TASK_VENV%"
  if errorlevel 1 goto :fail
)
"%TASK_VENV%\Scripts\python.exe" -m pip --version >nul 2>nul
if errorlevel 1 (
  echo Installing pip in the local Python environment...
  "%TASK_VENV%\Scripts\python.exe" -m ensurepip --upgrade
  if errorlevel 1 goto :pipfail
)
"%TASK_VENV%\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :fail
echo.
echo Open http://localhost:5000 in this PC.
echo Teammates on the same LAN: http://THIS-PC-IP:5000
echo First-run admin password: data\admin_credentials.txt
"%TASK_VENV%\Scripts\python.exe" app.py
pause
exit /b 0
:pipfail
echo Could not install pip into .venv. Check the Python installation.
pause
exit /b 1
:fail
echo Startup failed. Please install Python 3.10+ and check network access.
pause
exit /b 1
