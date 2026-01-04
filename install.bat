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
echo.
REM 使用清华大学镜像源加速下载
set PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
echo [提示] 使用清华大学镜像源加速下载
echo.
echo 正在升级 pip、setuptools 和 wheel...
python -m pip install --upgrade pip setuptools wheel -i %PIP_INDEX_URL% --quiet --disable-pip-version-check >nul 2>&1
if %errorlevel% neq 0 (
    echo [警告] pip 升级失败，将尝试继续安装...
) else (
    echo [完成] pip 工具升级成功
)
echo.
echo 正在安装项目依赖...
echo 提示: 如果看到 "invalid distribution" 警告，通常不影响安装...
python -m pip install -r requirements.txt -i %PIP_INDEX_URL% --disable-pip-version-check --no-warn-script-location
if %errorlevel% neq 0 (
    echo.
    echo [错误] 依赖安装失败，请检查：
    echo   1. 网络连接是否正常
    echo   2. 是否有足够的磁盘空间
    echo   3. Python 环境是否正常
    echo.
    echo 提示: 如果遇到 "invalid distribution" 警告，可尝试：
    echo   python -m pip install --upgrade pip setuptools wheel -i %PIP_INDEX_URL%
    echo   然后重新运行此安装脚本
    pause
    exit /b 1
)
echo.
echo [完成] 依赖安装成功！
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

