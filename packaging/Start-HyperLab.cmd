@echo off
setlocal
if not exist "%~dp0HyperLab.exe" goto incomplete
if not exist "%~dp0_internal\python311.dll" goto incomplete
"%~dp0HyperLab.exe" app %*
set "launch_result=%errorlevel%"
if not "%launch_result%"=="0" (
    echo.
    echo HyperLab could not start. Keep the error above and run Check-Camera.cmd.
    pause
)
exit /b %launch_result%
:incomplete
echo The HyperLab folder is incomplete.
echo Extract the entire ZIP. Keep HyperLab.exe and _internal together.
pause
exit /b 1
