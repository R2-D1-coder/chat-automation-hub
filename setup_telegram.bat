@echo off
REM 一键生成 Telegram StringSession

setlocal enabledelayedexpansion

REM 获取脚本所在目录
set SCRIPT_DIR=%~dp0

REM 检查虚拟环境
if not exist "%SCRIPT_DIR%.venv\Scripts\activate.bat" (
    echo.
    echo [错误] 未找到虚拟环境
    echo 请先运行: install.bat
    echo.
    pause
    exit /b 1
)

REM 激活虚拟环境
call "%SCRIPT_DIR%.venv\Scripts\activate.bat"

echo.
echo ============================================================
echo  Telegram StringSession 生成工具
echo ============================================================
echo.
echo 这个脚本会帮你生成一个持久化的 Telegram session
echo 无需每次都输入验证码
echo.
echo 需要准备：
echo   1. Telegram 账户
echo   2. 手机号（带国际区号，如 +8618810932403）
echo   3. 能接收验证码的手机
echo.
echo ============================================================
echo.

REM 运行生成脚本
python "%SCRIPT_DIR%setup_telegram_session.py"

echo.
echo ============================================================
echo  下一步：配置 StringSession
echo ============================================================
echo.
echo 1. 复制上面生成的 StringSession 字符串
echo.
echo 2. 打开 test_feishu_notification_event.py
echo.
echo 3. 找到第 75 行：
echo    TELEGRAM_SESSION = ""
echo.
echo 4. 替换为：
echo    TELEGRAM_SESSION = "你复制的字符串"
echo.
echo 5. 保存文件，下次运行时就无需再输入验证码了！
echo.
echo ============================================================
echo.

pause
