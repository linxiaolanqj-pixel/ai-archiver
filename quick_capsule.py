#!/usr/bin/env python3
"""轻量胶囊浮层（Raycast 风格）：

3 个状态：
  1. Thinking 小胶囊（~160×44）出现在鼠标附近
  2. AI 完成 → 展开成「精简结果 + [精简] [复制] [归档] [⤢ 详细对比]」
  3. 用户点击操作 → 显示绿色 ✓ 反馈 → 1.5s 自动关

设计原则：
  - 不打断、不抢焦点（不调 frontmost / on_top=True 只是浮在最上不抢键盘）
  - 默认随鼠标位置；超出屏幕时贴边
  - LLM 失败时仍可点[复制]/[归档]（用原文）

CLI：
  quick_capsule.py                  默认 polish 模式，target=default
  quick_capsule.py --mode structure
  quick_capsule.py --target xx.md
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import traceback
from pathlib import Path

import webview

SCRIPT_DIR = Path(__file__).resolve().parent
QUICK_UI = SCRIPT_DIR / "quick"
PY = str(SCRIPT_DIR / ".venv/bin/python") if (SCRIPT_DIR / ".venv/bin/python").exists() else sys.executable
ARCHIVER_PY = SCRIPT_DIR / "archiver.py"

from history import bump_archived, record_text  # noqa: E402
from settings_util import (  # noqa: E402
    display_target,
    get_app_theme,
    get_capsule_size,
    get_default_target,
    kb_root,
    load_config,
    record_target_usage,
    resolve_target_path,
    set_capsule_size,
    set_default_target,
)
from quick_archive import (  # noqa: E402  复用 LLM 调用 / 模式标签
    MODE_LABELS,
    _call_deepseek_stream,
    _load_env,
    _refine,
    _read_clip,
    _read_prompt,
    _resolve_target,
    _notify,
    _action_for_target,
    md_to_plain,
)
from telemetry import track as _track  # noqa: E402


CAPSULE_INITIAL = (200, 60)


def _mouse_anchor(window_size: tuple[int, int]) -> tuple[int, int]:
    """根据鼠标位置 + 屏幕尺寸算出窗口左上角坐标（pywebview 用屏幕左上角原点）。"""
    try:
        from AppKit import NSEvent, NSScreen
    except Exception:
        return (100, 100)

    try:
        mouse = NSEvent.mouseLocation()
        screen = NSScreen.mainScreen().frame()
        screen_w = int(screen.size.width)
        screen_h = int(screen.size.height)
        mx = int(mouse.x)
        my_from_bottom = int(mouse.y)
        my_from_top = screen_h - my_from_bottom

        w, h = window_size
        x = mx - w // 2 + 30  # 略偏右，避开鼠标光标本体
        y = my_from_top + 18
        x = max(8, min(x, screen_w - w - 8))
        y = max(8, min(y, screen_h - h - 8))
        return (x, y)
    except Exception:
        return (100, 100)


class CapsuleApi:
    def __init__(self, text: str, target: str, mode: str) -> None:
        self.text = text
        self.target = target
        self.mode = mode if mode in MODE_LABELS else "polish"
        self.refined = ""
        self.done = False
        self._cur_w = 0
        self._cur_h = 0
        self._cur_x = 0
        self._cur_y = 0
        # 流式状态：{text, done, ok, mode, seq}
        self._stream_lock = threading.Lock()
        self._stream = {"text": "", "done": True, "ok": True, "mode": "", "seq": 0}
        self._stream_thread: threading.Thread | None = None

    def get_payload(self) -> dict:
        body = self.text.rstrip()
        saved = get_capsule_size()
        _track("view", "opened", scope="capsule",
               props={"mode": self.mode, "len": len(body), "target": Path(self.target).name if self.target else ""})
        return {
            "text": body,
            "len": len(body),
            "target_label": Path(self.target).name if self.target else "未设置默认文档",
            "target_display": display_target(self.target),
            "target": self.target or "",
            "mode": self.mode,
            "mode_label": MODE_LABELS.get(self.mode, self.mode),
            "modes": [{"id": k, "label": v} for k, v in MODE_LABELS.items()],
            "saved_size": list(saved) if saved else None,
            "theme": "dark" if get_app_theme() == "dark" else "white",
        }

    def resize_to(self, w: int, h: int) -> dict:
        """前端拖拽 resize 时实时调用（仅右/下方向，不动位置）。"""
        w = max(280, int(w))
        h = max(120, int(h))
        try:
            for win in webview.windows:
                win.resize(w, h)
                break
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}
        self._cur_w = w
        self._cur_h = h
        return {"ok": True, "w": w, "h": h}

    def move_and_resize(self, x: int, y: int, w: int, h: int) -> dict:
        """拖左/上/左上/左下/右上边或角时使用：原子地同时改窗口位置 + 大小。

        关键：直接调 Cocoa `setFrame_display_animate_` 把 origin 和 size 一次性更新，
        避免 pywebview 的 win.move() + win.resize() 两步带来的视觉闪烁。
        """
        w = max(280, int(w))
        h = max(120, int(h))
        x = int(x)
        y = int(y)
        ok_native = False
        try:
            from AppKit import NSMakeRect, NSScreen  # type: ignore
            for win in webview.windows:
                native = getattr(win, "native", None)
                if native is not None:
                    screen_h = int(NSScreen.mainScreen().frame().size.height)
                    # JS / pywebview create_window 用 top-left + y 向下；
                    # Cocoa setFrame 用 bottom-left + y 向上，需翻转
                    cocoa_y = screen_h - y - h
                    rect = NSMakeRect(x, cocoa_y, w, h)
                    native.setFrame_display_animate_(rect, False, False)
                    ok_native = True
                break
        except Exception:
            ok_native = False

        if not ok_native:
            # fallback：pywebview 通用 API
            try:
                for win in webview.windows:
                    try:
                        win.move(x, y)
                    except Exception:
                        pass
                    win.resize(w, h)
                    break
            except Exception as e:
                return {"ok": False, "error": str(e)[:120]}

        self._cur_w = w
        self._cur_h = h
        self._cur_x = x
        self._cur_y = y
        return {"ok": True, "x": x, "y": y, "w": w, "h": h}

    def get_position(self) -> dict:
        """返回当前窗口在屏幕上的真实坐标（top-left 原点，y 向下）。

        JS 拖拽开始时调一次，避免用 `e.screenX - e.clientX` 这种不可靠的算法。
        """
        try:
            from AppKit import NSScreen  # type: ignore
            for win in webview.windows:
                native = getattr(win, "native", None)
                if native is None:
                    break
                frame = native.frame()
                screen_h = int(NSScreen.mainScreen().frame().size.height)
                top_y = int(screen_h - frame.origin.y - frame.size.height)
                return {
                    "ok": True,
                    "x": int(frame.origin.x),
                    "y": top_y,
                    "w": int(frame.size.width),
                    "h": int(frame.size.height),
                }
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}
        return {"ok": False, "error": "no window"}

    def save_size(self) -> dict:
        """拖拽结束后保存到 .state.json，下次启动恢复。"""
        if self._cur_w and self._cur_h:
            try:
                set_capsule_size(self._cur_w, self._cur_h)
            except Exception as e:
                return {"ok": False, "error": str(e)[:120]}
        return {"ok": True}

    def refine(self, mode: str | None = None) -> dict:
        """同步整理（保留兜底；正常路径用 start_refine 流式）。"""
        m = mode or self.mode
        if m not in MODE_LABELS:
            m = "polish"
        self.mode = m
        if m == "raw":
            self.refined = self.text.strip()
            return {"ok": True, "body": self.refined, "mode": m}
        ok, body = _refine(self.text, m)
        if ok:
            self.refined = body
        return {"ok": ok, "body": body, "mode": m}

    def start_refine(self, mode: str | None = None) -> dict:
        """启动流式 LLM；前端调 get_progress 轮询读 chunk。"""
        m = mode or self.mode
        if m not in MODE_LABELS:
            m = "polish"
        self.mode = m
        _track("click", "refine", scope="capsule", props={"mode": m, "len": len(self.text)})

        with self._stream_lock:
            self._stream = {"text": "", "done": False, "ok": True, "mode": m, "seq": 0}

        if m == "raw":
            with self._stream_lock:
                self._stream["text"] = self.text.strip()
                self._stream["done"] = True
                self._stream["seq"] = 1
            self.refined = self.text.strip()
            return {"ok": True, "mode": m}

        def worker() -> None:
            sys_prompt = _read_prompt(m) or "请把用户的原文整理成清晰的 Markdown 笔记。"
            acc = ""
            ok = True
            for kind, payload in _call_deepseek_stream(sys_prompt, self.text):
                if kind == "error":
                    ok = False
                    with self._stream_lock:
                        self._stream["ok"] = False
                        self._stream["text"] = payload
                        self._stream["seq"] += 1
                    break
                acc += payload
                with self._stream_lock:
                    self._stream["text"] = acc
                    self._stream["seq"] += 1
            # 兜底：如果模型仍然返回 JSON 包装，抽 body
            final = acc.strip()
            if ok and final.startswith("{") and '"body"' in final:
                try:
                    import json as _json
                    obj = _json.loads(final)
                    if isinstance(obj, dict) and obj.get("body"):
                        final = obj["body"].strip()
                except Exception:
                    pass
            with self._stream_lock:
                self._stream["text"] = final if ok else self._stream["text"]
                self._stream["done"] = True
                self._stream["seq"] += 1
            if ok:
                self.refined = final

        self._stream_thread = threading.Thread(target=worker, daemon=True)
        self._stream_thread.start()
        return {"ok": True, "mode": m}

    def get_progress(self) -> dict:
        with self._stream_lock:
            return dict(self._stream)

    def copy_result(self) -> dict:
        """把精简结果（没有就用原文）以**纯文本**复制回剪贴板，去掉 md 标记字符。"""
        raw = (self.refined or self.text).strip()
        body = md_to_plain(raw) if self.refined else raw
        try:
            subprocess.run(["pbcopy"], input=body, text=True, timeout=5, check=False)
            _track("click", "copy_result", scope="capsule",
                   props={"len": len(body), "has_refined": bool(self.refined)})
            return {"ok": True, "len": len(body)}
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}

    def archive(self) -> dict:
        """写入默认 md：优先用 refined，没有就用原文。"""
        if not self.target:
            return {"ok": False, "error": "未设置默认文档"}
        cfg = load_config()
        write_text = (self.refined or self.text).strip()
        action = _action_for_target(cfg, self.target) or next(iter(cfg.get("actions", {})), "daily")
        cmd = [
            PY, str(ARCHIVER_PY), action,
            "--target", self.target, "--from-stdin", "--no-notify", "--mode", "raw",
        ]
        try:
            r = subprocess.run(
                cmd, input=write_text, capture_output=True, text=True, timeout=60,
                cwd=str(SCRIPT_DIR), env=os.environ.copy(),
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "写入超时"}
        if r.returncode != 0:
            return {"ok": False, "error": (r.stderr or r.stdout)[:160]}

        try:
            record_target_usage(self.target)
            bump_archived(1)
        except Exception:
            pass

        self.done = True
        target_path = str(resolve_target_path(self.target, cfg))
        _track("click", "archive", scope="capsule",
               props={"target": Path(self.target).name, "len": len(write_text), "mode": self.mode})
        return {
            "ok": True,
            "target": self.target,
            "target_path": target_path,
            "message": f"已写入 {Path(self.target).name}",
        }

    def pick_target(self) -> dict:
        """点击 › 弹 Finder 选 .md，同步更新默认归档文档。

        在 kb_root 内 → 存相对；在 kb_root 外 → 存绝对路径。
        """
        cfg = load_config()
        cur_kb = kb_root(cfg).resolve()
        script = f'''
        try
          set theFile to choose file with prompt "切换归档目标" of type {{"public.text", "net.daringfireball.markdown", "md"}} default location POSIX file "{cur_kb}" without invisibles
          return POSIX path of theFile
        on error
          return ""
        end try
        '''
        try:
            r = subprocess.run(
                ["osascript", "-e", script], capture_output=True, text=True, timeout=300
            )
            raw = (r.stdout or "").strip()
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}
        if not raw:
            return {"ok": False, "cancelled": True}
        if not raw.lower().endswith(".md"):
            return {"ok": False, "error": "请选 .md 文件"}
        abs_p = Path(raw).resolve()
        if not abs_p.exists():
            return {"ok": False, "error": "文件不存在"}
        try:
            stored = abs_p.relative_to(cur_kb).as_posix()
        except ValueError:
            stored = str(abs_p)
        try:
            set_default_target(stored)
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}
        self.target = stored
        _track("click", "switch_target", scope="capsule", props={"target": Path(stored).name})
        return {
            "ok": True,
            "target": stored,
            "target_label": Path(stored).name,
            "target_display": display_target(stored),
        }

    def resize(self, w: int, h: int) -> dict:
        """状态切换时使用，不更新用户记忆尺寸。"""
        try:
            for win in webview.windows:
                win.resize(int(w), int(h))
                break
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}
        self._cur_w = int(w)
        self._cur_h = int(h)
        return {"ok": True}

    def close(self) -> dict:
        """关窗：先 destroy，然后 0.3s 后强制退出进程 — 防止流式 LLM 线程拖住主进程。"""
        for w in webview.windows:
            try:
                w.destroy()
            except Exception:
                pass

        def _force_exit() -> None:
            try:
                os._exit(0)
            except Exception:
                pass

        threading.Timer(0.3, _force_exit).start()
        return {"ok": True}


def show_capsule(text: str, *, target: str, mode: str) -> int:
    api = CapsuleApi(text=text, target=target or "", mode=mode)
    html = QUICK_UI / "capsule.html"
    if not html.exists():
        raise FileNotFoundError(f"缺少 {html}")

    init_w, init_h = CAPSULE_INITIAL
    x, y = _mouse_anchor((init_w, init_h))

    webview.create_window(
        "Quick Capsule",
        url=html.resolve().as_uri(),
        js_api=api,
        width=init_w,
        height=init_h,
        x=x,
        y=y,
        frameless=True,
        on_top=True,
        easy_drag=True,
        resizable=True,
        transparent=True,
        background_color="#000000",
    )

    try:
        webview.start(gui="cocoa")
    except Exception:
        traceback.print_exc()
        return 1
    return 0 if api.done else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="鼠标边轻量胶囊浮层")
    parser.add_argument("--target", help="指定目标 md 相对路径，默认 default_target")
    parser.add_argument("--mode", default="polish",
                        choices=list(MODE_LABELS.keys()))
    parser.add_argument("--raw", action="store_true")
    args = parser.parse_args(argv)
    if args.raw:
        args.mode = "raw"

    _load_env()
    text = _read_clip()
    if not text.strip():
        _notify("Skillless", "剪贴板为空，先 Cmd+C")
        return 2
    try:
        record_text(text, source="capsule")
    except Exception:
        pass

    target = _resolve_target(args.target)
    if not target:
        _notify("Skillless", "尚未设置默认文档")
        return 2

    return show_capsule(text, target=target, mode=args.mode)


if __name__ == "__main__":
    raise SystemExit(main())
