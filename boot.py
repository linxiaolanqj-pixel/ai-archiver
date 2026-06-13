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
    """资源在 _MEIPASS；cwd 切到可写的 Application Support（打包后）。"""
    from app_paths import data_dir, resource_dir

    base = resource_dir()
    os.chdir(str(data_dir()))
    if str(base) not in sys.path:
        sys.path.insert(0, str(base))


def _write_launch_log(mode: str, status: str, *, detail: str = "") -> None:
    """记录启动阶段：booting → ready / crashed（避免「有 last_launch 但进程已死」误判）。"""
    try:
        from datetime import datetime
        from app_paths import data_dir

        ts = datetime.now().isoformat(timespec="seconds")
        line = f"{ts} mode={mode} pid={os.getpid()} status={status}"
        if detail:
            line += f" {detail}"
        line += "\n"
        (data_dir() / "last_launch.log").write_text(line, encoding="utf-8")
    except Exception:
        pass


def _log_crash(exc: BaseException) -> None:
    import traceback

    try:
        from app_paths import data_dir

        (data_dir() / "startup.log").write_text(traceback.format_exc(), encoding="utf-8")
        _write_launch_log("menubar", "crashed", detail=type(exc).__name__)
    except Exception:
        pass


def main() -> int:
    try:
        _ensure_paths()
    except Exception as e:
        _log_crash(e)
        raise

    mode = "menubar"
    argv = list(sys.argv[1:])
    if argv and argv[0].startswith("--mode="):
        mode = argv[0].split("=", 1)[1]
        argv = argv[1:]
    elif argv and argv[0] == "--mode" and len(argv) > 1:
        mode = argv[1]
        argv = argv[2:]

    _write_launch_log(mode, "booting")

    if mode in ("menubar", "main", ""):
        try:
            from archiver_menubar import main as _m
            return _m() if callable(_m) else 0
        except Exception as e:
            _log_crash(e)
            raise
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
