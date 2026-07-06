@echo off
chcp 65001 >nul
title Hikvision Motion Monitor

echo ========================================
echo   Hikvision Motion Detection
echo   Camera stays fixed, monitors for people
echo   Windows notification on detection
echo   Press Ctrl+C to stop
echo ========================================
echo.

python3 -m src.motion

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo FAILED
    pause
)
