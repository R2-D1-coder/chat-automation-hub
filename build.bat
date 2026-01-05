@echo off
chcp 65001 >nul
echo ========================================
echo 微信群发自动化工具 - PyInstaller 打包
echo ========================================
echo.

REM 检查 PyInstaller 是否已安装
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo [错误] PyInstaller 未安装
    echo 正在安装 PyInstaller...
    pip install PyInstaller>=6.0.0
    if errorlevel 1 (
        echo [错误] PyInstaller 安装失败
        pause
        exit /b 1
    )
)

echo [1/3] 清理旧的构建文件...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "__pycache__" rmdir /s /q "__pycache__"
echo ✓ 清理完成
echo.

echo [2/3] 开始打包...
pyinstaller --clean --noconfirm chat-automation-hub.spec
if errorlevel 1 (
    echo [错误] 打包失败
    pause
    exit /b 1
)
echo ✓ 打包完成
echo.

echo [3/3] 检查输出文件...
if exist "dist\chat-automation-hub.exe" (
    echo ✓ 可执行文件已生成: dist\chat-automation-hub.exe
    echo.
    echo ========================================
    echo 打包成功！
    echo ========================================
    echo.
    echo 输出目录: dist\
    echo 可执行文件: dist\chat-automation-hub.exe
    echo.
    echo 注意：
    echo - 首次运行前，请确保 config.json 在相同目录下
    echo - assets 目录和 web/templates 目录已包含在打包文件中
    echo - 可以单独分发 dist\chat-automation-hub.exe 和相关文件
    echo.
) else (
    echo [错误] 未找到输出文件
    pause
    exit /b 1
)

pause



