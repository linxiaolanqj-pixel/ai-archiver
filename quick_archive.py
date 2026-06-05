#!/usr/bin/env python3
"""极简 ✅❌ 浮层：读剪贴板 → 1 秒决定归档/取消 → 灰底白字提示。

设计：
- 屏幕中下出现无边框小窗（420×180）
- 内容：前 120 字预览 + 目标文件名 + ✅ / ❌ 两个大按钮
- ✅ → 写入默认 md → toast「✓ 已记录」→ 1.5s 自动关
- ❌ / Esc → 取消
- 默认 AI 梳理（无 Key 自动 raw）
- --raw 强制原文，--target 指定文件，--mode polish/i18n/structure 用 AI 转译
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

SCRIPT_DIR = Path(__file__).resolve().parent
QUICK_UI = SCRIPT_DIR / "quick"
PY = str(SCRIPT_DIR / ".venv/bin/python") if (SCRIPT_DIR / ".venv/bin/python").exists() else sys.executable
ARCHIVER_PY = SCRIPT_DIR / "archiver.py"

from history import bump_archived, record_text  # noqa: E402
from settings_util import get_default_target, kb_root, load_config, record_target_usage  # noqa: E402


def _load_env() -> None:
    env = SCRIPT_DIR / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _read_clip() -> str:
    try:
        r = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=5)
        return r.stdout
    except Exception:
        return ""


def _notify(title: str, body: str) -> None:
    try:
        body = body.replace('"', "'")
        title = title.replace('"', "'")
        subprocess.run(
            ["osascript", "-e", f'display notification "{body}" with title "{title}"'],
            check=False, capture_output=True, timeout=5,
        )
    except Exception:
        pass


def _resolve_target(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    return get_default_target()


def _action_for_target(cfg: dict, target: str) -> str:
    bn = Path(target).name
    for key, conf in cfg.get("actions", {}).items():
        t = conf.get("target", "")
        if t == target or t == bn or Path(t).name == bn:
            return key
    return "daily"


class QuickApi:
    def __init__(self, text: str, target: str, mode: str) -> None:
        self.text = text
        self.target = target
        self.mode = mode
        self.done = False

    def get_payload(self) -> dict:
        flat = re.sub(r"\s+", " ", self.text.strip())
        preview = flat[:140] + ("…" if len(flat) > 140 else "")
        return {
            "preview": preview,
            "len": len(self.text.strip()),
            "target_label": Path(self.target).name if self.target else "未设置默认文档",
            "target": self.target or "",
            "mode": self.mode,
            "mode_label": {
                "auto": "AI 梳理",
                "raw": "原文追加",
                "polish": "润色",
                "i18n": "翻译",
                "structure": "结构化",
            }.get(self.mode, self.mode),
        }

    def confirm(self) -> dict:
        if not self.target:
            return {"ok": False, "error": "未设置默认文档，请到后台首页确认。"}
        cfg = load_config()
        action = _action_for_target(cfg, self.target)
        cmd = [PY, str(ARCHIVER_PY), action, "--target", self.target, "--from-stdin", "--no-notify"]

        env = os.environ.copy()
        if self.mode == "raw":
            cmd += ["--mode", "raw"]
        elif self.mode in ("polish", "i18n", "structure"):
            cmd += ["--prompt", f"prompts/translate_{self.mode}.md"]
        elif not env.get("DEEPSEEK_API_KEY", "").startswith("sk-"):
            cmd += ["--mode", "raw"]

        try:
            r = subprocess.run(
                cmd, input=self.text, capture_output=True, text=True, timeout=180, cwd=str(SCRIPT_DIR), env=env,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "超时"}
        if r.returncode != 0:
            return {"ok": False, "error": (r.stderr or r.stdout)[:160]}
        try:
            record_target_usage(self.target)
        except Exception:
            pass
        try:
            bump_archived(1)
        except Exception:
            pass
        self.done = True
        target_path = str(kb_root(cfg) / self.target)
        return {
            "ok": True,
            "target": self.target,
            "target_path": target_path,
            "message": f"已经补充到 {target_path}，放在了文件末尾。",
        }

    def cancel(self) -> dict:
        self.done = False
        return {"ok": True}

    def close(self) -> dict:
        for w in webview.windows:
            w.destroy()
        return {"ok": True}


def show_quick(text: str, *, target: str | None, mode: str) -> int:
    api = QuickApi(text=text, target=target or "", mode=mode)
    if not QUICK_UI.joinpath("index.html").exists():
        raise FileNotFoundError(f"缺少 {QUICK_UI / 'index.html'}")

    window = webview.create_window(
        "Quick Archive",
        url=(QUICK_UI / "index.html").resolve().as_uri(),
        js_api=api,
        width=440,
        height=220,
        frameless=True,
        on_top=True,
        easy_drag=True,
        resizable=False,
        transparent=False,
        background_color="#0c1016",
    )

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
    return 0 if api.done else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="极简 ✅❌ 归档浮层")
    parser.add_argument("--target", help="指定目标 md 相对路径")
    parser.add_argument("--mode", default="auto",
                        choices=["auto", "raw", "polish", "i18n", "structure"],
                        help="auto=按 Key 决定 | raw=原文 | polish/i18n/structure=AI 转译")
    parser.add_argument("--raw", action="store_true", help="等同 --mode raw")
    args = parser.parse_args(argv)

    if args.raw:
        args.mode = "raw"

    _load_env()
    text = _read_clip()
    if not text.strip():
        _notify("AI Archiver", "剪贴板为空，先 Cmd+C")
        return 2
    try:
        record_text(text, source="quick")
    except Exception:
        pass

    target = _resolve_target(args.target)
    if not target:
        _notify("AI Archiver", "尚未设置默认文档，先到后台设置")
        return 2

    return show_quick(text, target=target, mode=args.mode)


if __name__ == "__main__":
    raise SystemExit(main())
