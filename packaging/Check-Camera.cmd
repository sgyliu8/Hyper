@echo off
setlocal
if not exist "%~dp0HyperLab.exe" goto incomplete
if not exist "%~dp0_internal\python311.dll" goto incomplete
echo HyperLab camera setup check - no camera or serial port will be opened.
"%~dp0HyperLab.exe" hardware-check %*
set "check_result=%errorlevel%"
echo.
if "%check_result%"=="2" echo Setup needs attention. Follow the report above.
pause
exit /b %check_result%
:incomplete
echo The HyperLab folder is incomplete. Extract the entire ZIP, including _internal.
pause
exit /b 1
