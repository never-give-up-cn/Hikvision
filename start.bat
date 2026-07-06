@echo off
chcp 65001 >nul
title Hikvision PTZ Control

echo ========================================
echo   Hikvision PTZ Camera Control
echo ========================================
echo.

python3 src/main.py %*
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo FAILED - install dependencies: pip install -r requirements.txt
    pause
)
