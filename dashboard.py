#!/usr/bin/env python3
"""AI Archiver 后台管理 App。

四个 Tab：
  - 首页：最后复制、累计字数、节省时间
  - 历史：剪贴板历史（文字+图片）
  - 词典：跳过名单管理（auto/manual 分组）
  - 快捷键：三类入口的 Shortcuts 桥接配置
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import traceback
from pathlib import Path

import webview

from history import (
    bump_archived,
    clear_history,
    get_last_record,
    get_stats,
    get_text_for,
    list_records,
)
from settings_util import (
    add_manual_skip,
    get_default_target,
    get_dictionary,
    get_hotkeys,
    get_quick_pick_targets,
    kb_root,
    load_config,
    remove_skip,
    set_hotkey,
)
from hotkey_util import is_reasonable_hotkey, normalize_hotkey

SCRIPT_DIR = Path(__file__).resolve().parent
DASHBOARD_DIR = SCRIPT_DIR / "dashboard"
PY = str(SCRIPT_DIR / ".venv/bin/python") if (SCRIPT_DIR / ".venv/bin/python").exists() else sys.executable
ARCHIVER_PY = SCRIPT_DIR / "archiver.py"


class DashboardApi:
    """暴露给前端的 API。"""

    def __init__(self) -> None:
        self._window = None

    def get_overview(self) -> dict:
        cfg = load_config()
        stats = get_stats()
        last = get_last_record()
        return {
            "kb_root": str(kb_root(cfg)),
            "default_target": get_default_target(),
            "favorites": get_quick_pick_targets(8),
            "stats": stats,
            "last_record": last or {},
        }

    def list_history(self, kind: str | None = None, limit: int = 100) -> list[dict]:
        records = list_records(limit=limit, kind=kind)
        out = []
        for r in records:
            item = dict(r)
            if item.get("type") == "image":
                p = item.get("img_path")
                if p and Path(p).exists():
                    item["img_url"] = Path(p).resolve().as_uri()
            out.append(item)
        return out

    def get_record_text(self, ts: int) -> dict:
        for r in list_records(limit=200):
            if int(r.get("ts", 0)) == int(ts):
                return {"ok": True, "text": get_text_for(r)}
        return {"ok": False}

    def clear_history(self) -> dict:
        clear_history()
        return {"ok": True}

    def get_dictionary(self) -> dict:
        return get_dictionary()

    def add_skip(self, pattern: str) -> dict:
        ok = add_manual_skip(pattern)
        return {"ok": ok, "dict": get_dictionary()}

    def remove_skip(self, pattern: str, scope: str = "manual") -> dict:
        ok = remove_skip(pattern, scope=scope)
        return {"ok": ok, "dict": get_dictionary()}

    def get_hotkeys(self) -> dict:
        return get_hotkeys()

    def update_hotkey(self, key: str, shortcut: str) -> dict:
        shortcut = normalize_hotkey(shortcut)
        if not is_reasonable_hotkey(shortcut):
            return {"ok": False, "error": "请至少包含一个修饰键（⌃/⌥/⇧/⌘）和一个字母"}
        info = set_hotkey(key, shortcut=shortcut)
        return {"ok": True, "info": info}

    def copy_command(self, text: str) -> dict:
        try:
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=False, timeout=5)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def open_shortcuts_app(self) -> dict:
        subprocess.run(["open", "-a", "Shortcuts"], check=False)
        return {"ok": True}

    def open_kb(self) -> dict:
        subprocess.run(["open", str(kb_root(load_config()))], check=False)
        return {"ok": True}

    def open_path(self, p: str) -> dict:
        if not p:
            return {"ok": False}
        subprocess.run(["open", p], check=False)
        return {"ok": True}

    def archive_text(self, text: str, target: str | None = None, mode: str = "auto") -> dict:
        """从后台手动归档某段文字（用于历史 Tab 的「再次归档」）。"""
        from settings_util import get_default_target

        if not text or not text.strip():
            return {"ok": False, "error": "空内容"}
        target = target or get_default_target()
        if not target:
            return {"ok": False, "error": "未设置默认文档"}

        cmd = [PY, str(ARCHIVER_PY), "daily", "--target", target, "--from-stdin", "--no-notify"]
        if mode == "raw":
            cmd += ["--mode", "raw"]
        try:
            r = subprocess.run(
                cmd, input=text, capture_output=True, text=True, timeout=180, cwd=str(SCRIPT_DIR),
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "超时"}
        if r.returncode != 0:
            return {"ok": False, "error": (r.stderr or r.stdout)[:200]}
        try:
            bump_archived(1)
        except Exception:
            pass
        return {"ok": True, "target": target}


def run_dashboard() -> int:
    if not DASHBOARD_DIR.joinpath("index.html").exists():
        raise FileNotFoundError(f"缺少 dashboard/index.html: {DASHBOARD_DIR}")
    api = DashboardApi()
    index = DASHBOARD_DIR / "index.html"
    window = webview.create_window(
        "AI Archiver · 后台",
        url=index.resolve().as_uri(),
        js_api=api,
        width=980,
        height=680,
        min_size=(820, 560),
        resizable=True,
        text_select=True,
    )
    api._window = window  # noqa: SLF001

    def after_start() -> None:
        try:
            pid = os.getpid()
            subprocess.run(
                ["osascript", "-e",
                 f'tell application "System Events" to set frontmost of '
                 f'(first process whose unix id is {pid}) to true'],
                capture_output=True, timeout=5,
            )
        except Exception:
            pass

    try:
        webview.start(gui="cocoa", func=after_start)
    except Exception:
        traceback.print_exc()
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI Archiver 后台 App")
    parser.parse_args(argv)
    print("正在打开后台窗口…（关闭窗口前终端会停在这里）", flush=True)
    return run_dashboard()


if __name__ == "__main__":
    raise SystemExit(main())
