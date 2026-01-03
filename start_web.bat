@echo off
chcp 65001 >nul
echo 正在停止旧的 Python 进程...
taskkill /f /im python3.13.exe >nul 2>&1
taskkill /f /im python.exe >nul 2>&1
timeout /t 1 /nobreak >nul

echo 正在启动 Web 管理界面...
cd /d "%~dp0"
python run_web.py
pause

