@echo off
chcp 65001 >nul
title 海康人员移动侦测

echo ========================================
echo  海康威视 人员移动侦测
echo  摄像头固定不动
echo  检测到人员移动时弹出 Windows 通知
echo  按 Ctrl+C 停止
echo ========================================
echo.

python3 -m src.motion

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo 启动失败
    pause
)
