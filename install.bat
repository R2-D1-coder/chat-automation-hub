@echo off
chcp 65001 >nul
echo ============================================================
echo   微信群发管理中心 - 一键安装
echo ============================================================
echo.

REM 检查 Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [1/3] 检测到 Python:
python --version
echo.

echo [2/3] 正在安装依赖包（首次安装约需 2-5 分钟）...
pip install -r requirements.txt -q
if %errorlevel% neq 0 (
    echo [错误] 依赖安装失败，请检查网络连接
    pause
    exit /b 1
)
echo 依赖安装完成！
echo.

echo [3/3] 创建必要目录...
if not exist "output" mkdir output
if not exist "assets\uploads" mkdir assets\uploads
echo.

echo ============================================================
echo   安装完成！
echo ============================================================
echo.
echo 使用方法:
echo   1. 编辑 config.json 配置白名单群组
echo   2. 双击 start_web.bat 启动管理界面
echo   3. 浏览器访问 http://localhost:5000
echo.
pause

