"""Skillless 子进程启动工具：开发模式跑 .py；PyInstaller .app 模式走 dispatcher。

用法：
    from bootkit import child_cmd
    subprocess.Popen(child_cmd("dashboard"), ...)
    subprocess.run(child_cmd("onboarding", "--force"), ...)
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

_SCRIPT_MAP = {
    "menubar":    "archiver_menubar.py",
    "onboarding": "onboarding_window.py",
    "dashboard":  "dashboard.py",
    "capsule":    "quick_capsule.py",
    "quick":      "quick_archive.py",
    "archiver":   "archiver.py",
    "popup":      "popup.py",
}


def is_frozen() -> bool:
    """PyInstaller 打包后 sys.frozen=True。"""
    return bool(getattr(sys, "frozen", False))


def child_cmd(mode: str, *args: str) -> list[str]:
    """返回拉起子模式的命令列表。

    - 打包后：sys.executable 是 Skillless.app/Contents/MacOS/Skillless（dispatcher）
    - 开发态：sys.executable 是 venv 里的 python，直接跑对应 .py
    """
    if mode not in _SCRIPT_MAP:
        raise ValueError(f"unknown child mode: {mode}")
    if is_frozen():
        return [sys.executable, f"--mode={mode}", *args]
    return [sys.executable, str(SCRIPT_DIR / _SCRIPT_MAP[mode]), *args]
