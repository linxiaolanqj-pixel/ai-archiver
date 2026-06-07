# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Skillless (macOS .app).

主入口：archiver_menubar.py
依赖：rumps、pywebview、pyobjc 全家桶
子脚本：onboarding_window.py / dashboard.py / quick_capsule.py / quick_archive.py
       这些子脚本由主进程通过 subprocess.Popen([sys.executable, script], ...) 拉起。
       sys.executable 在打包后指向 .app/Contents/MacOS/Skillless 本身，
       所以子脚本需要被打成"额外脚本"或者主程序自己分发到调用对应模块的入口。

实现方案：
- 主入口是一个 dispatcher（boot.py），按 argv[1] 决定跑 menubar / onboarding / dashboard / capsule
- 各子脚本调用方改用 [sys.executable, "--mode=xxx"] 形式
- 但为保持代码改动小，这里采用更简单的策略：
    所有 .py 都打包，且 archiver_menubar.py 里 spawn 子进程时改用
    [sys.executable, str(SCRIPT_DIR / "子脚本.py")] 已经能用，
    只要 SCRIPT_DIR 指向 .app/Contents/Resources/scripts 即可。
"""

import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

# 图标：assets/Skillless.icns 存在则用，没有就 None
_ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(SPEC)), "assets", "Skillless.icns")
ICON = _ICON_PATH if os.path.exists(_ICON_PATH) else None

# ------------------------------------------------------------------------------
# 资源文件 + 子脚本（全部放进 .app/Contents/Resources/）
# ------------------------------------------------------------------------------
DATAS = [
    # 前端静态资源
    ("onboarding", "onboarding"),
    ("dashboard",  "dashboard"),
    ("quick",      "quick"),
    ("prompts",    "prompts"),
    ("assets",     "assets"),
    # 配置（用户可后续覆盖）
    ("config.yaml", "."),
    # 子脚本（被主进程 subprocess.Popen 拉起）
    ("onboarding_window.py", "."),
    ("onboarding.py",        "."),
    ("dashboard.py",         "."),
    ("quick_capsule.py",     "."),
    ("quick_archive.py",     "."),
    ("archiver.py",          "."),
    ("popup.py",             "."),
    # 共享 util（可能被子脚本 import）
    ("settings_util.py",     "."),
    ("hotkey_util.py",       "."),
    ("history.py",           "."),
    ("telemetry.py",         "."),
    # 入口脚本（被 dispatcher 拉起 / 也供主程序自己 reload）
    ("archiver_menubar.py",  "."),
]

# ------------------------------------------------------------------------------
# hidden imports：PyInstaller 静态分析抓不到的运行时 import
# ------------------------------------------------------------------------------
HIDDEN = []
HIDDEN += collect_submodules("webview")
HIDDEN += collect_submodules("rumps")
HIDDEN += collect_submodules("AppKit")
HIDDEN += collect_submodules("WebKit")
HIDDEN += collect_submodules("Foundation")
HIDDEN += [
    "objc",
    "Quartz",
    "PyObjCTools",
    "yaml",
]
# 主程序自己 import 的模块（dispatcher 用）
HIDDEN += [
    "archiver_menubar",
    "onboarding_window",
    "onboarding",
    "dashboard",
    "quick_capsule",
    "quick_archive",
    "archiver",
    "popup",
    "settings_util",
    "hotkey_util",
    "history",
    "telemetry",
]

# pywebview 自带的 JS bridge 资源
try:
    DATAS += collect_data_files("webview")
except Exception:
    pass

# ------------------------------------------------------------------------------
# Analysis：主入口是 boot.py（dispatcher，按 argv 切换子模式）
# ------------------------------------------------------------------------------
a = Analysis(
    ["boot.py"],
    pathex=["."],
    binaries=[],
    datas=DATAS,
    hiddenimports=HIDDEN,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "PIL",
        "numpy",
        "pandas",
        "test",
        "tests",
    ],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Skillless",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # 隐藏终端窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Skillless",
)

# ------------------------------------------------------------------------------
# .app 包装
# ------------------------------------------------------------------------------
app = BUNDLE(
    coll,
    name="Skillless.app",
    icon=ICON,
    bundle_identifier="com.skillless.app",
    info_plist={
        "CFBundleName": "Skillless",
        "CFBundleDisplayName": "Skillless",
        "CFBundleShortVersionString": "0.3.0",
        "CFBundleVersion": "0.3.0",
        # 后台 App：不在 Dock 显示图标
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
        # 用户给输入监听权限时的说明
        "NSAppleEventsUsageDescription": "Skillless 需要 AppleScript 来选择文件、调用 Finder。",
        "NSInputMonitoringUsageDescription": "Skillless 需要监听全局快捷键，让你在任何 App 中按下设定的组合键唤起胶囊。",
        "LSMinimumSystemVersion": "11.0",
    },
)
