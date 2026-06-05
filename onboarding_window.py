#!/usr/bin/env python3
"""内嵌式新客引导：pywebview 居中圆角窗 + JS 步进 + Python 桥接。

须在独立进程主线程运行（菜单栏 App 内请用 subprocess 拉起本脚本，勿在子线程 webview.start）。
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import traceback
import webview
from pathlib import Path

from onboarding import DEMO_SAMPLE_TEXT, SCRIPT_DIR, _load_env_file, run_live_demo_archive
from picker_util import choose_md_file, choose_new_md_file
from settings_util import (
    DEEPSEEK_API_KEYS_URL,
    create_knowledge_base,
    get_api_key,
    mark_onboarding_done,
    onboarding_done,
    save_api_key,
    set_kb_root,
)
from ui_util import one_line_summary, show_long_text_preview, truncate_for_dialog

ONBOARDING_UI = SCRIPT_DIR / "onboarding"


class OnboardingApi:
    """暴露给前端的 API（方法名勿以下划线开头）。"""

    def __init__(self) -> None:
        self.root: Path | None = None
        self.kb_name: str = ""
        self.default_md: str | None = None
        self.demo_ran: bool = False
        self.success: bool = False

    def get_meta(self) -> dict:
        return {
            "api_keys_url": DEEPSEEK_API_KEYS_URL,
            "demo_len": len(DEMO_SAMPLE_TEXT),
            "has_key": bool(get_api_key().startswith("sk-")),
        }

    def get_demo_preview(self) -> dict:
        return {
            "summary": one_line_summary(DEMO_SAMPLE_TEXT),
            "snippet": truncate_for_dialog(DEMO_SAMPLE_TEXT, 200),
        }

    def open_demo_in_textedit(self) -> dict:
        try:
            show_long_text_preview(DEMO_SAMPLE_TEXT, filename="demo_sample_original.md", dialog_title="演示原文")
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def open_api_keys_page(self) -> dict:
        subprocess.run(["open", DEEPSEEK_API_KEYS_URL], check=False)
        return {"ok": True}

    def create_kb(self, name: str) -> dict:
        safe = re.sub(r"[^\w\u4e00-\u9fff\- ]", "", (name or "").strip())
        if not safe:
            return {"ok": False, "error": "请输入知识库名称"}
        try:
            root = create_knowledge_base(safe)
            set_kb_root(str(root))
            self.root = root
            self.kb_name = safe
            return {"ok": True, "name": safe, "path": str(root)}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def pick_existing_md(self) -> dict:
        if not self.root:
            return {"ok": False, "error": "请先创建知识库"}
        rel = choose_md_file(self.root, prompt="选择默认归档的 Markdown 文档")
        if not rel:
            return {"ok": False, "cancelled": True}
        self.default_md = rel
        return {"ok": True, "path": rel, "label": Path(rel).name}

    def pick_new_md(self) -> dict:
        if not self.root:
            return {"ok": False, "error": "请先创建知识库"}
        rel = choose_new_md_file(self.root, prompt="新建默认文档", default_name="默认归档.md")
        if not rel:
            return {"ok": False, "cancelled": True}
        self.default_md = rel
        return {"ok": True, "path": rel, "label": Path(rel).name}

    def save_api_key(self, key: str) -> dict:
        key = (key or "").strip()
        if not key:
            return {"ok": True, "skipped": True}
        if key.startswith("text returned:"):
            key = key.split(":", 1)[1].strip()
        if not key.startswith("sk-"):
            return {"ok": False, "error": "Key 应以 sk- 开头，或点「跳过」"}
        try:
            save_api_key(key)
            _load_env_file()
            return {"ok": True, "skipped": False}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def skip_api_key(self) -> dict:
        return {"ok": True, "skipped": True}

    def prepare_demo_clipboard(self) -> dict:
        subprocess.run(["pbcopy"], input=DEMO_SAMPLE_TEXT.encode("utf-8"), check=False)
        return {"ok": True}

    def run_demo(self) -> dict:
        if not self.root or not self.default_md:
            return {"ok": False, "error": "请先完成知识库与默认文档设置"}
        _load_env_file()
        ok, msg, used_ai = run_live_demo_archive(self.root, self.default_md)
        self.demo_ran = ok
        return {
            "ok": ok,
            "message": msg,
            "used_ai": used_ai,
            "mode": "AI 梳理" if used_ai else "原文追加",
        }

    def open_demo_result(self) -> dict:
        if not self.root or not self.default_md:
            return {"ok": False}
        target = self.root / self.default_md
        if target.exists():
            subprocess.run(["open", str(target)], check=False)
        return {"ok": True}

    def finish(self) -> dict:
        if not self.default_md:
            return {"ok": False, "error": "请选择默认文档"}
        try:
            mark_onboarding_done(default_target=self.default_md)
            self.success = True
            for w in webview.windows:
                w.destroy()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def cancel(self) -> dict:
        self.success = False
        for w in webview.windows:
            w.destroy()
        return {"ok": True}

    def get_summary(self) -> dict:
        return {
            "kb_name": self.kb_name,
            "kb_path": str(self.root) if self.root else "",
            "default_md": self.default_md or "",
            "demo_ran": self.demo_ran,
            "has_key": bool(get_api_key().startswith("sk-")),
        }


def _activate_app() -> None:
    """把当前 Python 进程推到前台，避免窗口开在后台看不见。"""
    pid = os.getpid()
    script = f'''
    tell application "System Events"
      set frontmost of (first process whose unix id is {pid}) to true
    end tell
    '''
    subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)


def run_onboarding_window() -> bool:
    if not ONBOARDING_UI.joinpath("index.html").exists():
        raise FileNotFoundError(f"缺少引导页: {ONBOARDING_UI / 'index.html'}")

    api = OnboardingApi()
    index = ONBOARDING_UI / "index.html"
    url = index.resolve().as_uri()
    window = webview.create_window(
        "AI Archiver · 新客引导",
        url=url,
        js_api=api,
        width=860,
        height=600,
        min_size=(720, 520),
        resizable=True,
        text_select=True,
    )
    api._window = window  # noqa: SLF001 — 仅供调试

    def after_start() -> None:
        _activate_app()
        try:
            window.show()
        except Exception:
            pass

    try:
        webview.start(gui="cocoa", func=after_start)
    except Exception:
        traceback.print_exc()
        return False
    return api.success


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI Archiver 内嵌新客引导")
    parser.add_argument(
        "--force",
        action="store_true",
        help="已完成引导时也强制打开（菜单「重新走引导」）",
    )
    args = parser.parse_args(argv)
    if onboarding_done() and not args.force:
        print(
            "引导已标记完成。若要重来：菜单「🎓 重新走新客引导」，或\n"
            "  .venv/bin/python onboarding_window.py --force",
            file=sys.stderr,
        )
        return 2
    print("正在打开引导窗口…（关闭窗口前终端会停在这里）", flush=True)
    ok = run_onboarding_window()
    if ok:
        print("引导已完成。", flush=True)
        return 0
    print("引导未走完（取消或未完成）。", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
