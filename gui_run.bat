@echo off
chcp 65001 >nul
title Hikvision PTZ Control

echo ========================================
echo   Hikvision PTZ Camera Control
echo ========================================
echo.

python3 src/gui.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo FAILED. Please install dependencies:
    echo pip install customtkinter
    pause
)
