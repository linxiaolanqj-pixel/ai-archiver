#!/usr/bin/env python3
"""内嵌式新客引导：pywebview 居中圆角窗 + JS 步进 + Python 桥接。

须在独立进程主线程运行（菜单栏 App 内请用 subprocess 拉起本脚本，勿在子线程 webview.start）。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import traceback
import webview
from pathlib import Path

from onboarding import SCRIPT_DIR
from settings_util import (
    display_target,
    get_api_key,
    get_hotkeys,
    mark_onboarding_done,
    onboarding_done,
    save_api_key,
    set_hotkey,
    set_kb_root,
)

DEMO_SAMPLE_TEXT = (
    "小美：v2 下周三 11:00 开始灰度 30%，李四已经确认了。\n"
    "重点看加购率从 3% 拉到 5%，转化率不能掉。\n"
    "周五 18:00 前补埋点 button_v2_click，新人券分歧下周复盘 —— 王五负责。"
)

ONBOARDING_UI = SCRIPT_DIR / "onboarding"


_PICK_EXISTING_SCRIPT = '''
try
  set theFile to choose file with prompt "选择要默认归档的 Markdown 文档（任意位置）" of type {"md", "markdown", "net.daringfireball.markdown", "public.text"}
  return POSIX path of theFile
on error
  return ""
end try
'''

_PICK_NEW_SCRIPT_TEMPLATE = '''
try
  set f to choose file name with prompt "为新的默认 .md 选个位置（任意位置）" default name "{name}" default location (path to documents folder)
  return POSIX path of f
on error
  return ""
end try
'''


def _run_apple(script: str) -> str:
    try:
        r = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True, timeout=300
        )
        return (r.stdout or "").strip()
    except Exception:
        return ""


class OnboardingApi:
    """暴露给前端的 API（方法名勿以下划线开头）。"""

    def __init__(self) -> None:
        self.root: Path | None = None
        self.kb_name: str = ""
        self.default_md_abs: str | None = None  # 用户最终选定 .md 的绝对路径
        self.success: bool = False

    def get_meta(self) -> dict:
        return {"has_key": bool(get_api_key().startswith("sk-"))}

    def _adopt_md_file(self, abs_path: Path) -> dict:
        """把用户挑的 .md 同时设为「知识库根 + 默认文档」。

        关键：父目录自动成为 kb_root；default_target 用相对路径（仅文件名），
        这样后续 dashboard / 胶囊都能直接打开。
        """
        if abs_path.suffix.lower() != ".md":
            return {"ok": False, "error": "请选择 .md 文件"}
        try:
            kb = abs_path.parent.resolve()
            kb.mkdir(parents=True, exist_ok=True)
            if not abs_path.exists():
                abs_path.write_text(f"# {abs_path.stem}\n\n", encoding="utf-8")
            set_kb_root(str(kb))
            self.root = kb
            self.kb_name = kb.name
            # 父目录已是 kb_root → 相对路径就是文件名，但为了 dashboard 显示稳，
            # 存绝对路径，后端 _sanitize_target_rel 已支持绝对路径
            self.default_md_abs = str(abs_path.resolve())
            return {
                "ok": True,
                "file_path": self.default_md_abs,
                "file_display": display_target(self.default_md_abs),
                "kb_path": str(kb),
                "kb_display": display_target(str(kb)),
                "name": abs_path.name,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def pick_existing_md(self) -> dict:
        raw = _run_apple(_PICK_EXISTING_SCRIPT)
        if not raw:
            return {"ok": False, "cancelled": True}
        return self._adopt_md_file(Path(raw))

    def pick_new_md(self) -> dict:
        script = _PICK_NEW_SCRIPT_TEMPLATE.format(name="我的归档.md")
        raw = _run_apple(script)
        if not raw:
            return {"ok": False, "cancelled": True}
        p = Path(raw)
        if p.suffix.lower() != ".md":
            p = p.with_suffix(".md")
        return self._adopt_md_file(p)

    def open_default_md(self) -> dict:
        if not self.default_md_abs:
            return {"ok": False}
        target = Path(self.default_md_abs)
        if target.exists():
            subprocess.run(["open", str(target)], check=False)
        return {"ok": True}

    def finish(self) -> dict:
        if not self.default_md_abs:
            return {"ok": False, "error": "请先选一个 .md 文档"}
        try:
            mark_onboarding_done(default_target=self.default_md_abs)
            self.success = True
            # 1) 先 spawn 后台（独立进程，引导窗关掉也能继续显示）
            try:
                self.open_dashboard()
            except Exception:
                pass
            # 2) 关引导窗
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

    # ============ 快捷键 ============
    def get_input_hotkey(self) -> dict:
        try:
            hk = get_hotkeys().get("input") or {}
            return {"ok": True, "shortcut": hk.get("shortcut", ""), "name": hk.get("name", "归档")}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def set_input_hotkey(self, shortcut: str) -> dict:
        """从前端 keydown 拿到 ⌃⌥A 这种字符串，标准化后保存。"""
        try:
            from hotkey_util import is_reasonable_hotkey, normalize_hotkey

            norm = normalize_hotkey(shortcut or "")
            if not is_reasonable_hotkey(norm):
                return {"ok": False, "error": "需要至少一个修饰键 + 一个字母键"}
            info = set_hotkey("input", shortcut=norm)
            return {"ok": True, "shortcut": info.get("shortcut", norm)}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    # ============ 手动试一次 ============
    def copy_demo_to_clipboard(self) -> dict:
        """把示例文字写进系统剪贴板，让用户按快捷键能立刻看到效果。"""
        try:
            p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            p.communicate(DEMO_SAMPLE_TEXT.encode("utf-8"))
            return {"ok": p.returncode == 0, "preview": DEMO_SAMPLE_TEXT[:80]}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def get_demo_text(self) -> dict:
        return {"text": DEMO_SAMPLE_TEXT}

    # ============ API Key ============
    def get_api_status(self) -> dict:
        try:
            k = (get_api_key() or "").strip()
            ok = k.startswith("sk-")
            masked = ""
            if ok and len(k) > 10:
                masked = k[:5] + "…" + k[-4:]
            return {"ok": True, "has_key": ok, "masked": masked}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def save_api(self, key: str) -> dict:
        try:
            k = (key or "").strip()
            if not k.startswith("sk-"):
                return {"ok": False, "error": "Key 应以 sk- 开头（DeepSeek / OpenAI 格式）"}
            if len(k) < 20:
                return {"ok": False, "error": "Key 长度不对，请粘贴完整 Key"}
            save_api_key(k)
            return {"ok": True, "masked": k[:5] + "…" + k[-4:]}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    # ============ 拉起后台 ============
    def open_dashboard(self) -> dict:
        try:
            from bootkit import child_cmd
            subprocess.Popen(
                child_cmd("dashboard"),
                cwd=str(SCRIPT_DIR),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def trigger_capsule(self) -> dict:
        """直接拉起 quick_capsule.py，不依赖全局快捷键监听。"""
        try:
            from bootkit import child_cmd
            self.copy_demo_to_clipboard()
            subprocess.Popen(
                child_cmd("capsule"),
                cwd=str(SCRIPT_DIR),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def get_summary(self) -> dict:
        return {
            "kb_name": self.kb_name,
            "kb_path": str(self.root) if self.root else "",
            "kb_display": display_target(str(self.root)) if self.root else "",
            "default_md": self.default_md_abs or "",
            "default_display": display_target(self.default_md_abs) if self.default_md_abs else "",
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
        "Skillless · 上手",
        url=url,
        js_api=api,
        width=820,
        height=620,
        min_size=(720, 560),
        resizable=True,
        text_select=True,
        background_color="#ffffff",
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
    parser = argparse.ArgumentParser(description="Skillless 内嵌新手引导")
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
