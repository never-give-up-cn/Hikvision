@echo off
chcp 65001 >nul
title Stop Capture

echo Stopping background capture...

for /f "tokens=2 delims=," %%a in ('tasklist /fi "imagename eq pythonw.exe" /fo csv /nh 2^>nul') do (
    taskkill /f /pid %%a >nul 2>&1
)

for /f "tokens=2 delims=," %%a in ('tasklist /fi "imagename eq python.exe" /fo csv /nh 2^>nul') do (
    taskkill /f /pid %%a >nul 2>&1
)

echo.
echo [OK] Stopped

pause
