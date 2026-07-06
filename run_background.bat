@echo off
chcp 65001 >nul
title Hikvision Background Capture

echo ========================================
echo   Panorama Background Service
echo   Grid: 8x3 = 24 images
echo   Interval: every 5 minutes
echo   Output: img/YYYY-MM-DD/HHMMSS/
echo   Stop with: run_stop.bat
echo   Log: img/auto.log
echo ========================================
echo.

start /B "" pythonw src\main.py --auto --interval 5 > img\auto.log 2>&1

echo [OK] Background capture started
echo.
pause
