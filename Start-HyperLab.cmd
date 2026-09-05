@echo off
setlocal
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
    echo Create the project .venv first; see README.md.
    exit /b 1
)
start "" /D "%~dp0" "%~dp0.venv\Scripts\pythonw.exe" -X utf8 -m hyperlab app %*
exit /b %errorlevel%
