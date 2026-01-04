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
echo 正在升级 pip、setuptools 和 wheel...
REM 升级 pip 使用官方源（更可靠），--user 避免权限问题
python -m pip install --upgrade pip setuptools wheel --user --quiet --disable-pip-version-check >nul 2>&1
if %errorlevel% neq 0 (
    echo [警告] pip 升级失败，将尝试继续安装...
) else (
    echo [完成] pip 工具升级成功
)
echo.
echo 正在安装项目依赖...
echo 提示: 如果看到 "invalid distribution" 警告，通常不影响安装...
echo 提示: 使用 --user 选项安装到用户目录，无需管理员权限
echo.
echo [尝试] 使用清华大学镜像源加速下载...
python -m pip install -r requirements.txt --user -i https://pypi.tuna.tsinghua.edu.cn/simple --disable-pip-version-check --no-warn-script-location
if %errorlevel% neq 0 (
    echo.
    echo [警告] 镜像源安装失败（可能缺少某些包），尝试使用官方 PyPI 源...
    echo.
    python -m pip install -r requirements.txt --user --disable-pip-version-check --no-warn-script-location
    if %errorlevel% neq 0 (
        echo.
        echo [错误] 依赖安装失败，请检查：
        echo   1. 网络连接是否正常
        echo   2. 是否有足够的磁盘空间
        echo   3. Python 环境是否正常
        echo.
        echo 提示: 如果遇到权限错误，可尝试：
        echo   以管理员身份运行此脚本
        echo   或手动执行: python -m pip install -r requirements.txt --user
        pause
        exit /b 1
    )
    echo.
    echo [完成] 依赖安装成功（使用官方源）！
) else (
    echo.
    echo [完成] 依赖安装成功（使用镜像源）！
)
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

