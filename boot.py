#!/usr/bin/env python3
"""Skillless.app 启动 dispatcher。

打成 .app 之后，整个 .app 只有一个二进制（Skillless）；所有子脚本通过
   subprocess.Popen([sys.executable, "--mode=xxx", ...])
拉起。本文件按 --mode 路由到对应子模块的 main()。

开发态（直接 python boot.py）也兼容：不带 --mode 默认跑 menubar。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _ensure_paths() -> None:
    """让子模块能找到 onboarding/ dashboard/ quick/ 等资源目录。"""
    if getattr(sys, "frozen", False):
        # PyInstaller 打包后：资源被释放到 sys._MEIPASS
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).resolve().parent
    os.chdir(str(base))
    if str(base) not in sys.path:
        sys.path.insert(0, str(base))


def main() -> int:
    _ensure_paths()

    mode = "menubar"
    argv = list(sys.argv[1:])
    if argv and argv[0].startswith("--mode="):
        mode = argv[0].split("=", 1)[1]
        argv = argv[1:]
    elif argv and argv[0] == "--mode" and len(argv) > 1:
        mode = argv[1]
        argv = argv[2:]

    if mode in ("menubar", "main", ""):
        from archiver_menubar import main as _m
        return _m() if callable(_m) else 0
    if mode == "onboarding":
        from onboarding_window import main as _m
        return _m(argv)
    if mode == "dashboard":
        from dashboard import main as _m
        return _m(argv)
    if mode == "capsule":
        from quick_capsule import main as _m
        return _m(argv)
    if mode == "quick":
        from quick_archive import main as _m
        return _m(argv)
    if mode == "archiver":
        from archiver import main as _m
        return _m(argv)
    if mode == "popup":
        from popup import main as _m
        return _m(argv)

    print(f"[boot] unknown mode: {mode}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
