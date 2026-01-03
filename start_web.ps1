# 微信群发管理中心 - 启动脚本
# 使用方法: .\start_web.ps1

Write-Host "正在停止旧的 Python 进程..." -ForegroundColor Yellow
Get-Process python3.13 -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*Python3.13*" } | Stop-Process -Force
Start-Sleep -Seconds 1

Write-Host "正在启动 Web 管理界面..." -ForegroundColor Green
Set-Location $PSScriptRoot
python run_web.py

