@echo off
chcp 65001 >nul
title 海康全景图后台采集

echo ========================================
echo  全景图后台采集服务
echo  网格: 8列x3行 = 24张
echo  间隔: 每5分钟采集一次
echo  输出: img/YYYY-MM-DD/HHMMSS/
echo ========================================
echo.
echo  启动方式: 双击此文件（后台运行）
echo  停止方式: run_stop.bat
echo  查看日志: img/auto.log
echo.

:: 在后台运行 Python（无窗口模式）
start /B "" pythonw src\main.py --auto --interval 5 > img\auto.log 2>&1

echo [OK] 后台采集已启动 (PID: %ERRORLEVEL%)
echo 查看日志: type img\auto.log
echo.
pause
