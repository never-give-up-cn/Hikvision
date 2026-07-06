@echo off
chcp 65001 >nul
title 海康威视 PTZ 摄像头控制 v0.1

echo ========================================
echo  海康威视 PTZ 摄像头控制程序
echo  版本: v0.1
echo ========================================
echo.

python src/main.py %*
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo 运行失败，请确保已安装依赖: pip install -r requirements.txt
    pause
)
