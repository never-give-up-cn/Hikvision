@echo off
chcp 65001 >nul
title 海康威视 PTZ 全景图管理

echo ========================================
echo  海康威视 PTZ 全景图管理 v0.14
echo ========================================
echo.

python3 src/gui.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo 启动失败，请确保已安装依赖:
    echo pip install customtkinter
    pause
)
