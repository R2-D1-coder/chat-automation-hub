# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置文件
用于打包微信群发自动化工具
"""

import sys
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(SPECPATH)

# 分析主程序
a = Analysis(
    ['run_web.py'],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[
        # 配置文件
        ('config.json', '.'),
        # Web 模板文件
        ('web/templates', 'web/templates'),
        # 资源文件目录（保留目录结构）
        ('assets', 'assets'),
    ],
    hiddenimports=[
        # Flask 相关
        'flask',
        'werkzeug',
        'jinja2',
        'click',
        'itsdangerous',
        'markupsafe',
        # APScheduler 相关
        'apscheduler',
        'apscheduler.jobstores.base',
        'apscheduler.executors.pool',
        'apscheduler.triggers.cron',
        'apscheduler.triggers.date',
        'apscheduler.triggers.interval',
        # 项目模块
        'web.app',
        'web.models',
        'web.scheduler',
        'src.adapters.wechat_desktop',
        'src.core.config',
        'src.core.send_queue',
        'src.core.dedupe',
        'src.core.log',
        'src.core.ratelimit',
        'src.core.retry',
        'src.core.storage',
        # UI Automation
        'uiautomation',
        # Robocorp
        'robocorp.tasks',
        # 其他可能需要的模块
        'sqlite3',
        'PIL',
        'PIL.Image',
        'win32gui',
        'win32con',
        'win32clipboard',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除不需要的模块以减小体积
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'tkinter',
        'PyQt5',
        'PyQt6',
        'PySide2',
        'PySide6',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# 收集所有依赖
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# 创建可执行文件
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='chat-automation-hub',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # 显示控制台窗口以查看日志
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # 可以添加图标文件路径，如: 'assets/icon.ico'
)

