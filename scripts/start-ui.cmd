@echo off
setlocal
set SCRIPT_DIR=%~dp0
set ROOT_DIR=%SCRIPT_DIR%..

if exist "%SCRIPT_DIR%recording-retrieval-service.exe" (
  "%SCRIPT_DIR%recording-retrieval-service.exe" --mode ui %*
  exit /b %errorlevel%
)

if exist "%ROOT_DIR%\recording-retrieval-service.exe" (
  "%ROOT_DIR%\recording-retrieval-service.exe" --mode ui %*
  exit /b %errorlevel%
)

if exist "%ROOT_DIR%\.venv\Scripts\python.exe" (
  "%ROOT_DIR%\.venv\Scripts\python.exe" -m app.main --mode ui %*
  exit /b %errorlevel%
)

python -m app.main --mode ui %*
