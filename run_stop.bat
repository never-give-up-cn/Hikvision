@echo off
chcp 65001 >nul
title 停止全景图采集

echo 正在停止全景图后台采集...

:: 查找并终止 pythonw 进程（main.py）
for /f "tokens=2 delims=," %%a in ('tasklist /fi "imagename eq pythonw.exe" /fo csv /nh 2^>nul') do (
    taskkill /f /pid %%a >nul 2>&1
)

:: 也尝试终止 python.exe
for /f "tokens=2 delims=," %%a in ('tasklist /fi "imagename eq python.exe" /fo csv /nh 2^>nul') do (
    taskkill /f /pid %%a >nul 2>&1
)

echo.
echo [OK] 后台采集已停止
echo 查看最后日志: type img\auto.log

pause
