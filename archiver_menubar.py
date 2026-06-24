#!/usr/bin/env python3
"""Skillless 菜单栏 App — 复制即归档 + 新手引导 + 预览确认 + 黑名单"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path  # noqa: F401 used in _load_config

import rumps
import yaml

from settings_util import (
    DEEPSEEK_API_KEYS_URL,
    DEFAULT_INPUT_HOTKEY,
    add_to_blacklist_extra,
    add_manual_skip,
    get_api_key,
    get_blacklist,
    get_default_target,
    auto_prompt_enabled,
    get_hotkeys,
    hotkey_enabled,
    migrate_state_defaults,
    get_quick_pick_targets,
    iter_kb_markdown_files,
    kb_root,
    load_config,
    load_state,
    onboarding_done,
    record_target_usage,
    save_api_key,
    save_state,
    set_default_target,
    set_hotkey,
    set_min_length,
    should_skip_text,
)
from onboarding import _display_dialog, run_onboarding  # _display_dialog 用于短确认弹窗
from picker_util import choose_archive_target, choose_md_file, choose_new_md_file
from ui_util import one_line_summary, show_long_text_preview, truncate_for_dialog
from history import bump_archived, record_text
from hotkey_util import event_to_hotkey, normalize_hotkey


from app_paths import config_path, data_dir, resource_dir

try:
    from version import VERSION
except Exception:
    VERSION = "dev"

SCRIPT_DIR = resource_dir()
RUN_SH = resource_dir() / "run.sh"
ARCHIVER_PY = resource_dir() / "archiver.py"
STATE_PATH = data_dir() / ".state.json"
PROMPTS_CUSTOM = resource_dir() / "prompts" / "custom"

POLL_INTERVAL = 0.5
NEW_FILE_LABEL = "➕ 新建文件…"
ROOT_FOLDER_KEY = "__root__"  # 知识库根目录下的 .md

PY = str(SCRIPT_DIR / ".venv/bin/python") if (SCRIPT_DIR / ".venv/bin/python").exists() else sys.executable


def _load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


# v0.4.11：用 NSPasteboard + changeCount 替换 pbpaste
# 原因：复制图片时 pbpaste 会触发 macOS 的图→文转换，每次轮询都卡几秒。
# changeCount 是剪贴板版本号，没变就用缓存；有变化才读 string 类型（图片直接 ""）
_pb_last_change = -1
_pb_last_text = ""


def _read_clipboard() -> str:
    global _pb_last_change, _pb_last_text
    try:
        from AppKit import NSPasteboard, NSPasteboardTypeString
        pb = NSPasteboard.generalPasteboard()
        change = int(pb.changeCount())
        if change == _pb_last_change:
            return _pb_last_text
        _pb_last_change = change
        # stringForType_ 是 O(1) 拿字符串；图片 / 文件等只返回 None
        s = pb.stringForType_(NSPasteboardTypeString)
        _pb_last_text = s if s else ""
        return _pb_last_text
    except Exception:
        # AppKit 不可用 / import 失败的兜底（极少见）
        try:
            out = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=5)
            return out.stdout
        except Exception:
            return ""


def _read_pb_image() -> bytes | None:
    """v0.4.15：从剪贴板拿 PNG bytes。优先 PNG，没有就 TIFF→PNG 转。

    设计原则：
      - 不调 osascript（每次启动子进程 ~150ms，且不稳定）
      - 不调 pbpaste（图→文转换会卡几秒）
      - 直接用 AppKit 的 NSPasteboardTypePNG / NSPasteboardTypeTIFF
      - 失败一律返回 None；调用方决定后续行为（通知 / 跳过）
    """
    try:
        from AppKit import (
            NSPasteboard,
            NSPasteboardTypePNG,
            NSPasteboardTypeTIFF,
            NSBitmapImageRep,
            NSBitmapImageFileTypePNG,
        )
    except Exception:
        return None
    try:
        pb = NSPasteboard.generalPasteboard()
        png = pb.dataForType_(NSPasteboardTypePNG)
        if png is not None:
            return bytes(png)
        tiff = pb.dataForType_(NSPasteboardTypeTIFF)
        if tiff is None:
            return None
        rep = NSBitmapImageRep.imageRepWithData_(tiff)
        if rep is None:
            return None
        # NSBitmapImageRep.representationUsingType_properties_(NSBitmapImageFileTypePNG, {})
        png_data = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, {})
        if png_data is None:
            return None
        return bytes(png_data)
    except Exception:
        return None


def _hash_image_bytes(data: bytes) -> str:
    """对图片做轻量指纹：取头 4KB + 尾 4KB 拼起来 sha256，避免大图 hash 慢。

    用途：双击 ⌘C 判定「两次复制是不是同一张图」；不要求加密强度，求速度。
    """
    import hashlib
    if not data:
        return ""
    if len(data) <= 8192:
        sample = data
    else:
        sample = data[:4096] + data[-4096:]
    return hashlib.sha256(sample).hexdigest()


def _debug_log(msg: str) -> None:
    try:
        from datetime import datetime

        line = f"{datetime.now().isoformat(timespec='seconds')} {msg}\n"
        (data_dir() / "clip_watcher.log").open("a", encoding="utf-8").write(line)
    except Exception:
        pass


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _today() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d")


def _bump_today_count() -> int:
    state = load_state()
    today = _today()
    if state.get("date") != today:
        state = {"date": today, "count": 0}
    state["count"] = int(state.get("count", 0)) + 1
    save_state(state)
    return state["count"]


class ArchiverApp(rumps.App):
    def __init__(self):
        super().__init__("📥", quit_button=None)

        self._cfg: dict = {}
        self._kb_root = Path.home()
        self._files: list[tuple[str, str, str]] = []
        self._min_length = 100
        self._max_length = 20000
        self._mute_after = 2
        self._ai_preview = True

        migrate_state_defaults()
        # 默认：复制 ≥ 100 字就弹胶囊（⌘C 主路径 / 也有全局 hotkey 备份路径）。
        self._onboarding_active = not onboarding_done()
        self._watch_mode = auto_prompt_enabled() and not self._onboarding_active
        self._dialog_open = False
        self._last_clipboard = ""
        self._skip_streak = 0
        self._ai_mode = True
        self._hotkey_monitor = None
        self._hotkey_last_at: dict[str, float] = {}
        self._quick_proc: subprocess.Popen | None = None

        # 启动先不扫全盘 .md（rglob 大库会卡）；引导结束后再后台补扫
        self._load_config(scan_kb=False)
        self._build_menu()
        self._update_title()

        self._last_clipboard = _read_clipboard()
        self._timer = rumps.Timer(self._poll_clipboard, POLL_INTERVAL)
        self._timer.start()

        if onboarding_done():
            self._ensure_hotkey_ready()
            threading.Thread(target=self._deferred_kb_scan, daemon=True).start()
        else:
            # 延迟拉起引导，避免与菜单栏进程同时抢 CPU（打包版会起两个 Skillless 子进程）
            threading.Timer(
                2.0,
                lambda: threading.Thread(target=self._run_onboarding_safe, daemon=True).start(),
            ).start()

        def _notify_started() -> None:
            try:
                rumps.notification(
                    "Skillless 已启动",
                    "双击 ⌘C 召唤胶囊（≥100 字）",
                    f"也可按 {DEFAULT_INPUT_HOTKEY}；菜单点 📥 可切换",
                )
            except Exception:
                pass

        threading.Timer(1.0, _notify_started).start()
        # 首启动告知：默认开启了「自动错误上报」，给用户一个明显的提醒
        threading.Timer(2.5, self._maybe_notify_feedback_first_run).start()
        _debug_log(
            f"menubar ready watch={self._watch_mode} min_len={self._min_length} "
            f"target={get_default_target() or '(none)'}"
        )

    def _clip_skip_reason(self, text: str) -> str | None:
        t = text.strip()
        if len(t) < self._min_length:
            return f"too_short({len(t)}<{self._min_length})"
        if self._max_length and len(t) > self._max_length:
            return f"too_long({len(t)}>{self._max_length})"
        # 细分原因方便诊断（get_blacklist 已 import 在顶部）
        from settings_util import looks_like_code, get_behavior
        beh = get_behavior(self._cfg)
        if bool(beh.get("skip_code_like", True)) and looks_like_code(t):
            cjk_lo, cjk_hi = "\u4e00", "\u9fff"
            cjk = sum(1 for c in t if cjk_lo <= c <= cjk_hi)
            ratio = cjk / max(len(t), 1)
            return "code_like(len={}, cjk_ratio={:.2f})".format(len(t), ratio)
        for pat in get_blacklist(self._cfg):
            try:
                if re.search(pat, t, re.IGNORECASE | re.MULTILINE):
                    return f"blacklist({pat!r})"
            except re.error:
                continue
        return None

    def _run_onboarding_safe(self) -> None:
        self._onboarding_active = True
        self._watch_mode = False
        if hasattr(self, "_watch_item"):
            self._watch_item.title = self._watch_label()
        try:
            if run_onboarding():
                self._load_config(scan_kb=True)
                self._build_menu()
                self._update_title()
        except Exception as e:
            rumps.notification("Skillless", "新客引导失败", str(e)[:120])
        finally:
            self._onboarding_active = False
            if onboarding_done():
                self._watch_mode = auto_prompt_enabled()
                if hasattr(self, "_watch_item"):
                    self._watch_item.title = self._watch_label()
                self._ensure_hotkey_ready()
                threading.Thread(target=self._deferred_kb_scan, daemon=True).start()

    def _update_title(self) -> None:
        # 菜单栏只保留短标记；知识库路径在菜单项里看，避免标题过长把图标挤出屏幕。
        self.title = "📥"

    def _deferred_kb_scan(self) -> None:
        """后台补扫知识库，避免启动时阻塞菜单栏。"""
        import time
        time.sleep(1.5)
        try:
            self._load_config(scan_kb=True)
            self._build_menu()
        except Exception:
            pass

    def _load_config(self, *, scan_kb: bool = True) -> None:
        cfg_path = config_path()
        with cfg_path.open("r", encoding="utf-8") as f:
            self._cfg = yaml.safe_load(f) or {}
        self._kb_root = kb_root(self._cfg)
        beh = self._cfg.get("behavior", {}) or {}
        self._min_length = int(beh.get("auto_prompt_min_length", 100))
        # 2500 太低（一段长会议转录 ~15K 字直接被拦），实测会议记录 + 长文章是核心场景
        self._max_length = int(beh.get("auto_prompt_max_length", 20000) or 0)
        self._mute_after = int(beh.get("auto_mute_after_skips", 2))
        self._ai_preview = bool(beh.get("ai_preview_before_write", True))
        self._skip_code_like = bool(beh.get("skip_code_like", True))
        self._clip_stable_ms = int(beh.get("clipboard_stable_ms", 400))
        self._pending_clip: str = ""
        self._pending_at: float = 0.0
        # v0.4.11 双击 ⌘C：只在「两次 ⌘C 同样内容、间隔 < dbl_window_ms」时弹胶囊。
        # 单次 ⌘C 走 macOS 原生复制，不打扰。changeCount 是 NSPasteboard 的递增版本号，
        # 每次 ⌘C 都 +1（即使内容相同），是唯一可靠区分「内容变化」vs「再按一次 ⌘C」的方式
        self._last_pb_change: int = -1
        self._dbl_pending_text: str = ""
        self._dbl_pending_at: float = 0.0
        self._dbl_window_ms: int = int(beh.get("double_cmdc_window_ms", 1500))
        # v0.4.15「图片即附件归档」：用图片指纹（头 4KB + 尾 4KB sha256）判同一张图，
        # 走和文本完全一样的双击窗口逻辑
        self._dbl_pending_img_hash: str = ""
        self._last_pb_img_hash: str = ""

        # rel_path -> (展示名, action_key)
        target_to_action: dict[str, tuple[str, str]] = {}
        basename_to_action: dict[str, str] = {}
        for action_key, conf in self._cfg.get("actions", {}).items():
            target = conf.get("target")
            if not target:
                continue
            basename_to_action[Path(target).name] = action_key
            label = re.sub(r"^(追加到|生成|提取)\s*", "", conf.get("label") or target)
            target_to_action[target] = (label, action_key)

        for item in self._cfg.get("custom_prompts", []) or []:
            t = item.get("target")
            if t and t not in target_to_action:
                target_to_action[t] = (item.get("label", item.get("id", t)), item.get("id", ""))
                basename_to_action[Path(t).name] = item.get("id", "")

        if scan_kb:
            for display, rel in iter_kb_markdown_files(self._kb_root):
                if rel in target_to_action:
                    continue
                action = basename_to_action.get(Path(rel).name, "__raw_only__")
                target_to_action[rel] = (display, action)

        # 配置里登记了、磁盘上还没有的文件也显示（首次写入会自动创建）
        for action_key, conf in self._cfg.get("actions", {}).items():
            target = conf.get("target")
            if target and target not in target_to_action:
                label = re.sub(r"^(追加到|生成|提取)\s*", "", conf.get("label") or target)
                target_to_action[target] = (label, action_key)

        self._files = sorted(
            [(lb, rel, a) for rel, (lb, a) in target_to_action.items()],
            key=lambda x: x[1],
        )

    def _short_label(self, rel: str) -> str:
        p = Path(rel)
        if p.is_absolute():
            return p.stem
        if len(p.parts) == 1:
            return p.stem
        return f"{p.stem} · {p.parent}"

    def _hotkey_menu_label(self) -> str:
        sc = (get_hotkeys().get("input") or {}).get("shortcut") or DEFAULT_INPUT_HOTKEY
        return f"⌨️ 快捷键（{sc}）"

    def _build_menu(self) -> None:
        self.menu.clear()
        self.menu.add(rumps.MenuItem(self._hotkey_menu_label(), callback=self._menu_hotkey))
        self.menu.add(rumps.MenuItem("退出", callback=rumps.quit_application))
        self.menu.add(rumps.MenuItem("打开后台", callback=self._open_dashboard))
        self.menu.add(rumps.MenuItem("反馈意见", callback=self._menu_feedback))
        self.menu.add(rumps.MenuItem("添加到黑名单", callback=self._menu_add_blacklist))
        self.menu.add(rumps.MenuItem("调整复制门槛", callback=self._settings_threshold))
        # 版本标识：callback=None → 视觉灰显，不可点（rumps 没有原生 disabled API）
        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem(f"Skillless v{VERSION}", callback=None))

    def _setup_input_monitor(self) -> None:
        """一键申请输入监控，并轮询直到剪贴板/全局 hotkey 监听可用。"""
        from hotkey_perm import input_monitor_granted, request_input_monitor_access

        request_input_monitor_access()

        def _poll(attempt: int = 0) -> None:
            if input_monitor_granted():
                self._hotkey_monitor = None
                self._ensure_hotkey_ready()
                rumps.notification("Skillless", "输入监控已开启", "在任意 App 按 ⌘C 复制即弹")
                return
            if attempt < 45:
                threading.Timer(1.0, lambda: _poll(attempt + 1)).start()
            else:
                rumps.notification("Skillless", "还没检测到权限", "菜单 → 快捷键 → 一键开启权限")

        threading.Timer(0.8, lambda: _poll(0)).start()
        rumps.notification("Skillless", "正在打开系统设置", "打开 Skillless 开关后会自动生效")

    def _menu_hotkey(self, _s) -> None:
        from hotkey_perm import input_monitor_granted

        sc = (get_hotkeys().get("input") or {}).get("shortcut") or DEFAULT_INPUT_HOTKEY
        granted = input_monitor_granted()
        perm_line = (
            "✓ 输入监控已开启，快捷键全局可用。"
            if granted
            else "⚠ 快捷键需要「输入监控」权限。点「一键开启权限」自动跳转设置。"
        )
        script = (
            f'display dialog "选中文字后按 ⌘C 复制（≥ 100 字），剪贴板更新就会弹出精简胶囊。\\n\\n{perm_line}" '
            f'buttons {{"知道了", "一键开启权限", "恢复默认 ⌘C"}} '
            f'default button "一键开启权限" with title "快捷键"'
        )
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            return
        choice = (r.stdout or "").strip()
        if "一键开启权限" in choice:
            self._setup_input_monitor()
        elif "恢复默认" in choice:
            set_hotkey("input", shortcut=DEFAULT_INPUT_HOTKEY)
            state = load_state()
            state["hotkey_enabled"] = True
            save_state(state)
            self._hotkey_monitor = None
            if input_monitor_granted():
                self._ensure_hotkey_ready()
            else:
                self._setup_input_monitor()
            self._build_menu()
            rumps.notification("Skillless", f"快捷键已恢复为 {DEFAULT_INPUT_HOTKEY}", "")

    def _maybe_notify_feedback_first_run(self) -> None:
        """首启动告知：默认开启了「自动错误上报」，让用户知道并能关。

        触发条件：onboarding 已完成 + 还没告知过。引导走中的不打扰。
        """
        try:
            if not onboarding_done():
                return
            from settings_util import load_state, save_state
            state = load_state()
            fb = state.get("feedback", {}) or {}
            if fb.get("first_run_notified"):
                return
            try:
                rumps.notification(
                    "已开启自动错误上报",
                    "崩溃 / API 故障会自动发开发者一份精简日志（不含你的笔记）",
                    "可在「打开后台 → 反馈」里关闭或修改署名",
                )
            except Exception:
                pass
            fb["first_run_notified"] = True
            # 只有没显式设置过 auto_error_enabled 才赋默认值
            fb.setdefault("auto_error_enabled", True)
            state["feedback"] = fb
            save_state(state)
        except Exception:
            pass

    def _menu_feedback(self, _s) -> None:
        out = _display_dialog(
            "一句话描述：建议、bug、想要的功能、奇怪的行为……\n"
            "（提交后会随附最近日志/版本/系统信息，不含你的笔记原文）",
            title="反馈意见",
            buttons=("取消", "提交"),
            default_button="提交",
            default_answer="",
        )
        if not out or out == "取消":
            return
        text = out.strip()
        if text.startswith("text returned:"):
            text = text.split(":", 1)[1].strip()
        if not text:
            return
        from datetime import datetime

        # 先写本地备份（即便发送失败也有据可查）
        line = f"{datetime.now().isoformat(timespec='seconds')}\n{text}\n---\n"
        try:
            (data_dir() / "feedback.log").open("a", encoding="utf-8").write(line)
        except Exception:
            pass

        # 远程上报
        try:
            from feedback_collector import build_payload, send_feedback
            payload = build_payload(kind="user_report", description=text)
            r = send_feedback(payload)
            if r.get("ok"):
                rumps.notification("Skillless", "感谢反馈", "已发送给开发者 ✓")
            elif r.get("fallback") == "clipboard":
                rumps.notification(
                    "Skillless",
                    "网络发送失败，已复制",
                    "反馈包已在剪贴板，可粘贴给开发者",
                )
            else:
                rumps.notification(
                    "Skillless",
                    "反馈已本地记录",
                    "尚未配置开发者收件，可在后台「日志」查看",
                )
        except Exception as e:
            rumps.notification("Skillless", "反馈发送出错", str(e)[:120])

    def _menu_add_blacklist(self, _s) -> None:
        clip = _read_clipboard().strip()
        preview = re.sub(r"\s+", " ", clip)[:50].replace('"', "'")
        default_pat = re.escape(clip[:80]) if clip else ""
        hint = f"当前剪贴板：{preview}…\\n\\n" if preview else ""
        script = (
            f'display dialog "{hint}输入要跳过的内容规则（留空取消）：" '
            f'default answer "{_escape(default_pat)}" '
            'buttons {"取消", "添加"} default button "添加" with title "添加到黑名单"'
        )
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            return
        pat = r.stdout.strip()
        if pat.startswith("text returned:"):
            pat = pat.split(":", 1)[1].strip()
        if not pat:
            return
        # 防误加：超短词当 substring regex 会拒掉所有含它的文本（曾出现 "http" 把所有带链接复制全毙的事故）
        if len(pat) < 6 and not pat.startswith("^"):
            rumps.notification(
                "Skillless · 已拒绝",
                f"「{pat}」太短",
                "短于 6 字会误伤大量文本，请用更具体的正则（如 ^http） 或加长",
            )
            return
        if add_manual_skip(pat):
            rumps.notification("Skillless", "已加入黑名单", pat[:40])
        else:
            rumps.notification("Skillless", "已在黑名单中", pat[:40])

    def _mode_label(self) -> str:
        return f"🧠 模式：{'AI 梳理' if self._ai_mode else '原文追加'}（点击切换）"

    def _watch_label(self) -> str:
        if self._onboarding_active:
            return "⏸ 新客引导中（暂不监听复制）"
        default = get_default_target()
        suffix = f"→ {Path(default).name}" if default else "（未设置默认文档）"
        return f"{'✅' if self._watch_mode else '⬜'} Cmd+C 弹对比浮层（≥{self._min_length} 字 {suffix}）"

    def _make_handler(self, target: str):
        def handler(_s):
            text = _read_clipboard()
            if not text.strip():
                rumps.notification("Skillless", "剪贴板为空", "先 Cmd+C 复制")
                return
            self._archive_async(target, text)
        return handler

    def _pick_from_all_folders(self, _s) -> None:
        text = _read_clipboard()
        if not text.strip():
            rumps.notification("Skillless", "剪贴板为空", "先 Cmd+C 复制一段文字")
            return
        self._dialog_open = True
        try:
            target = self._pick_md_via_finder(text)
            if target:
                self._archive_async(target, text)
        finally:
            self._dialog_open = False

    def _main_new_file(self, _s) -> None:
        text = _read_clipboard()
        if not text.strip():
            rumps.notification("Skillless", "剪贴板为空", "先 Cmd+C")
            return
        t = self._handle_new_file()
        if t:
            self._archive_async(t, text)

    def _toggle_mode(self, _s) -> None:
        self._ai_mode = not self._ai_mode

    def _toggle_watch(self, _s) -> None:
        self._watch_mode = not self._watch_mode
        self._skip_streak = 0
        state = load_state()
        state["auto_prompt_enabled"] = self._watch_mode
        save_state(state)

    def _ensure_hotkey_ready(self) -> None:
        """保证全局 hotkey 监听已挂上（备份路径，主路径是 ⌘C 剪贴板监听）。"""
        state = load_state()
        if not state.get("hotkey_enabled", True):
            state["hotkey_enabled"] = True
            save_state(state)
        self._install_hotkey_monitor()

    def _install_hotkey_monitor(self) -> None:
        """监听全局 hotkey（备份路径；⌘C 实际走 auto_prompt 剪贴板监听）。"""
        if not hotkey_enabled():
            return
        try:
            import AppKit
        except Exception:
            return
        if self._hotkey_monitor is not None:
            return

        def handler(event):
            try:
                self._handle_global_hotkey(event)
            except Exception as e:
                rumps.notification("Skillless", "快捷键监听出错", str(e)[:120])

        try:
            self._hotkey_monitor = AppKit.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                AppKit.NSEventMaskKeyDown,
                handler,
            )
            if self._hotkey_monitor is None:
                rumps.notification(
                    "Skillless · 快捷键",
                    "需要开启输入监控",
                    "菜单 → 快捷键 → 一键开启权限",
                )
        except Exception as e:
            rumps.notification("Skillless", "快捷键监听未启动", str(e)[:120])

    def _simulate_copy_selection(self) -> None:
        """先 Cmd+C 把当前选区放进剪贴板（备忘录里只选中不按复制时用）。"""
        try:
            subprocess.run(
                [
                    "osascript", "-e",
                    'tell application "System Events" to keystroke "c" using command down',
                ],
                capture_output=True, timeout=3,
            )
        except Exception:
            pass

    def _hotkey_open_capsule(self) -> None:
        import time

        _debug_log("hotkey_open_capsule start")
        time.sleep(0.08)
        self._simulate_copy_selection()
        time.sleep(0.2)
        text = _read_clipboard()
        t = (text or "").strip()
        _debug_log(f"hotkey clip len={len(t)}")
        if len(t) < self._min_length:
            if len(t) < 10:
                rumps.notification(
                    "Skillless",
                    "没读到选中文字",
                    "请开：系统设置 → 隐私 → 辅助功能 → Skillless；并确认已开输入监控",
                )
            else:
                rumps.notification(
                    "Skillless",
                    "文字太短",
                    f"先选中 ≥{self._min_length} 字，再复制（菜单可改门槛）",
                )
            return
        self._last_clipboard = text
        self._pending_clip = ""
        self._open_quick_compare()

    def _dispatch_hotkey_action(self, key: str) -> None:
        """全局 hotkey（备份路径）弹胶囊。"""
        if key == "input":
            threading.Thread(target=self._hotkey_open_capsule, daemon=True).start()

    def _handle_global_hotkey(self, event) -> None:
        combo = normalize_hotkey(event_to_hotkey(event))
        if not combo:
            return
        hotkeys = get_hotkeys()
        matched: tuple[str, dict] | None = None
        for key, info in hotkeys.items():
            if combo == normalize_hotkey(info.get("shortcut", "")):
                matched = (key, info)
                break
        if not matched:
            return

        import time

        now = time.time()
        last = self._hotkey_last_at.get(combo, 0)
        if now - last < 1.0:
            return
        self._hotkey_last_at[combo] = now

        key, _info = matched
        _debug_log(f"hotkey hit {combo} -> {key}")
        self._dispatch_hotkey_action(key)

    def _poll_clipboard(self, _s) -> None:
        """v0.4.11 双击 ⌘C 触发：单击照常复制（0 打扰），双击同样内容才弹胶囊。

        实现原理：NSPasteboard.changeCount() 每次 ⌘C 都会 +1（即使内容相同），
        通过比较 delta + 内容 + 时间窗判定双击；不需要全局键盘监听权限。
        """
        if self._onboarding_active:
            return

        import time as _time
        try:
            from AppKit import NSPasteboard, NSPasteboardTypeString
            pb = NSPasteboard.generalPasteboard()
            pb_change = int(pb.changeCount())
            s = pb.stringForType_(NSPasteboardTypeString)
            cur = s if s else ""
        except Exception:
            pb_change = self._last_pb_change + 1
            cur = _read_clipboard()

        if pb_change == self._last_pb_change:
            return

        delta = pb_change - self._last_pb_change
        self._last_pb_change = pb_change
        now = _time.time()

        # 记历史：每次新内容都进 record_text（包括单击，用户复制了就该进历史）
        if cur and cur != self._last_clipboard:
            try:
                record_text(cur, source="clip")
            except Exception:
                pass
            self._last_clipboard = cur

        # v0.4.15「图片即附件归档」：cur 为空时尝试看是不是剪贴板图片。
        # 双击判定走和文本完全一样的窗口逻辑，但内容比对换成图片指纹（头/尾 4KB sha256）。
        # 触发后只跑「弹胶囊预览」，不调 AI、不动剪贴板（用户拍板再走 archive_image）。
        if not cur:
            self._maybe_handle_image_double(delta, now)
            return

        # 文本路径（下面的双击判定）开始前先把图片态清掉，避免「先复制图片再复制文字」之间错位
        self._dbl_pending_img_hash = ""

        # 双击判定（v0.4.13 校准）：
        # A. 单 poll 周期内 changeCount 跳了 ≥ 2（强信号）
        # B. 距上次 changeCount 变化 < dbl_window_ms 且文本"近似相同"（容忍选区微调）
        # 校准原因：500ms 窗口 + 500ms poll 周期等于"几乎永远抓不到"；
        # 用户实际节奏是 0.8-1.5s 一击 ⌘C。同时复制时选区常有 1-2 字偏差，要求完全相同会误毙
        elapsed_ms = (now - self._dbl_pending_at) * 1000 if self._dbl_pending_at > 0 else 9e9
        prev = self._dbl_pending_text
        if prev and cur:
            n1, n2 = len(prev), len(cur)
            len_diff_ratio = abs(n1 - n2) / max(n1, n2)
            prefix_n = min(60, n1, n2)
            text_match = (prev == cur) or (
                len_diff_ratio <= 0.05 and prev[:prefix_n] == cur[:prefix_n]
            )
        else:
            text_match = False
        is_double = text_match and (delta >= 2 or elapsed_ms < self._dbl_window_ms)
        self._dbl_pending_text = cur
        self._dbl_pending_at = now

        if not is_double:
            _debug_log(
                f"copy single len={len(cur.strip())} delta={delta} "
                f"elapsed={int(elapsed_ms)}ms match={text_match} (need double ⌘C)"
            )
            return

        if not self._watch_mode:
            _debug_log(f"copy ignored watch_off len={len(cur.strip())}")
            return
        if self._dialog_open:
            return
        if self._quick_proc and self._quick_proc.poll() is None:
            _debug_log("copy ignored capsule_already_open")
            return
        reason = self._clip_skip_reason(cur)
        if reason:
            _debug_log(f"copy skipped {reason}")
            if reason.startswith("too_long"):
                try:
                    n = len(cur.strip())
                    rumps.notification(
                        "Skillless",
                        f"文本太长（{n} 字），分段复制试试",
                        f"胶囊上限 {self._max_length} 字；菜单 → 防误触可改",
                    )
                except Exception:
                    pass
            return
        _debug_log(f"copy trigger len={len(cur.strip())} (double ⌘C)")
        self._open_quick_compare()

    def _maybe_handle_image_double(self, delta: int, now: float) -> None:
        """v0.4.15：剪贴板里没有文本时，看是不是图片；双击 ⌘C 同一张图 → 弹图片胶囊。

        关键设计：
          - 不调 AI、不动剪贴板（剪贴板里仍是用户原图，胶囊点「归档+复制」后照样能粘别处）
          - 临时图片缓存到 ~/Library/Application Support/Skillless/.tmp/<hash>.png，
            存在则复用，避免大图反复落盘
          - 单击 ⌘C 不打扰；双击窗口同 dbl_window_ms（用文本路径同款逻辑，只是比对换成图片指纹）
          - 图片归档不做 _clip_skip_reason 文本过滤（图片 ≠ 文本，没意义跑代码检测/黑名单）
        """
        img = _read_pb_image()
        if not img:
            self._dbl_pending_img_hash = ""
            return
        h = _hash_image_bytes(img)
        if not h:
            return

        # 历史指纹比对：和「上次刚处理过的图片」一致才算双击
        prev_h = self._dbl_pending_img_hash
        elapsed_ms = (now - self._dbl_pending_at) * 1000 if self._dbl_pending_at > 0 else 9e9
        is_double = (
            prev_h == h
            and (delta >= 2 or elapsed_ms < self._dbl_window_ms)
        )
        self._dbl_pending_img_hash = h
        self._dbl_pending_at = now
        # 文本侧的 pending 同步清掉，下一次 ⌘C 切回文本场景时不会被旧 text 干扰
        self._dbl_pending_text = ""

        if not is_double:
            _debug_log(
                f"img single hash={h[:8]} delta={delta} "
                f"elapsed={int(elapsed_ms)}ms (need double ⌘C)"
            )
            return

        if not self._watch_mode:
            _debug_log(f"img ignored watch_off hash={h[:8]}")
            return
        if self._dialog_open:
            return
        if self._quick_proc and self._quick_proc.poll() is None:
            _debug_log("img ignored capsule_already_open")
            return
        if not get_default_target():
            try:
                rumps.notification(
                    "Skillless",
                    "尚未设置默认归档文档",
                    "菜单栏 → 🌟 更换默认归档文档",
                )
            except Exception:
                pass
            return

        # 缓存到 tmp（hash 命名 → 同一张图反复双击只落盘一次）
        try:
            tmp_dir = data_dir() / ".tmp"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            tmp_path = tmp_dir / f"{h}.png"
            if not tmp_path.exists():
                tmp_path.write_bytes(img)
        except Exception as e:
            _debug_log(f"img tmp_write_failed {e}")
            try:
                rumps.notification("Skillless", "图片写盘失败", str(e)[:80])
            except Exception:
                pass
            return

        _debug_log(f"img trigger hash={h[:8]} bytes={len(img)} path={tmp_path}")
        self._open_image_capsule(str(tmp_path))

    def _open_image_capsule(self, image_path: str) -> None:
        """拉胶囊子进程，模式 = 图片预览（不调 AI）。"""
        default = get_default_target()
        if not default:
            return
        try:
            from bootkit import child_cmd

            err_path = data_dir() / "capsule_spawn.log"
            err_f = err_path.open("a", encoding="utf-8")
            cmd = child_cmd(
                "capsule",
                "--target", default,
                "--image-path", image_path,
            )
            _debug_log(f"spawn capsule (image) cmd={' '.join(cmd)}")
            self._quick_proc = subprocess.Popen(
                cmd,
                cwd=str(data_dir()),
                stdout=subprocess.DEVNULL,
                stderr=err_f,
                start_new_session=True,
            )
        except Exception as e:
            _debug_log(f"img spawn failed {e}")
            try:
                rumps.notification("Skillless", "图片胶囊启动失败", str(e)[:120])
            except Exception:
                pass

    def _open_quick_compare(self) -> None:
        """打开胶囊浮层（Raycast 风格，鼠标边小卡片）。

        胶囊内可点「⤢ 详细」拉起大对比浮层 quick_archive.py。
        """
        default = get_default_target()
        if not default:
            rumps.notification(
                "Skillless",
                "尚未设置默认文档",
                "菜单栏 → 🌟 更换默认归档文档",
            )
            return
        try:
            from bootkit import child_cmd

            err_path = data_dir() / "capsule_spawn.log"
            err_f = err_path.open("a", encoding="utf-8")
            cmd = child_cmd("capsule", "--target", default, "--mode", "polish")
            _debug_log(f"spawn capsule cmd={' '.join(cmd)}")
            self._quick_proc = subprocess.Popen(
                cmd,
                cwd=str(data_dir()),
                stdout=subprocess.DEVNULL,
                stderr=err_f,
                start_new_session=True,
            )
        except Exception as e:
            _debug_log(f"spawn failed {e}")
            rumps.notification("Skillless", "浮层启动失败", str(e)[:120])

    def _trigger_capsule_from_clipboard(self, _s) -> None:
        """菜单手动触发：不依赖轮询，用于排查复制监听。"""
        text = _read_clipboard().strip()
        if not text:
            rumps.notification("Skillless", "剪贴板为空", "先选中文字再 Cmd+C")
            return
        reason = self._clip_skip_reason(text)
        if reason:
            rumps.notification(
                "Skillless",
                "当前剪贴板未达触发条件",
                f"{reason}；需要 ≥{self._min_length} 字",
            )
            _debug_log(f"manual skip {reason}")
            return
        self._last_clipboard = text
        self._open_quick_compare()

    def _ask_and_archive(self, text: str) -> None:
        """旧版「选目标 + 写入」流程；保留给手动触发的入口（菜单里 📂 选择写入目标）。"""
        self._dialog_open = True
        try:
            self._load_config()
            target = self._show_file_picker(text)
            if not target:
                self._on_user_skip(text)
                return
            self._archive(target, text)
        finally:
            self._dialog_open = False

    def _on_user_skip(self, text: str) -> None:
        self._skip_streak += 1
        t = text.strip()
        if re.match(r"^https?://", t) or (len(t) < 80 and "." in t):
            add_to_blacklist_extra(re.escape(t[:80]))
        if self._skip_streak >= self._mute_after:
            self._watch_mode = False
            state = load_state()
            state["auto_prompt_enabled"] = False
            save_state(state)
            rumps.notification(
                "Skillless · 免打扰",
                f"连续跳过 {self._skip_streak} 次",
                "菜单里可重新打开监听",
            )

    def _folder_key_for_rel(self, rel: str) -> str:
        parts = Path(rel).parts
        if len(parts) <= 1:
            return ROOT_FOLDER_KEY
        return "/".join(parts[:-1])

    def _folder_display_name(self, folder_key: str) -> str:
        return "📁 根目录" if folder_key == ROOT_FOLDER_KEY else f"📁 {folder_key}"

    def _build_folder_groups(self) -> dict[str, list[tuple[str, str, str]]]:
        """按文件夹分组：folder_key -> [(label, rel_path, action)]"""
        groups: dict[str, list[tuple[str, str, str]]] = {}
        for label, rel, action in self._files:
            key = self._folder_key_for_rel(rel)
            groups.setdefault(key, []).append((label, rel, action))
        for key in groups:
            groups[key].sort(key=lambda x: x[1])
        return dict(sorted(groups.items(), key=lambda kv: (kv[0] != ROOT_FOLDER_KEY, kv[0])))

    def _apple_choose_list(
        self,
        items: list[str],
        *,
        title: str,
        prompt: str,
        ok_button: str = "下一步",
        cancel_button: str = "跳过",
    ) -> str | None:
        if not items:
            return None
        items_apple = ", ".join(f'"{_escape(x)}"' for x in items)
        script = (
            f'set actionList to {{{items_apple}}}\n'
            f'set theChoice to choose from list actionList '
            f'with prompt "{_escape(prompt)}" '
            f'with title "{_escape(title)}" '
            f'OK button name "{_escape(ok_button)}" cancel button name "{_escape(cancel_button)}"\n'
            f'if theChoice is false then return "__CANCELLED__"\n'
            f'return item 1 of theChoice'
        )
        try:
            r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=300)
        except Exception:
            return None
        raw = r.stdout.strip()
        if not raw or raw == "__CANCELLED__":
            return None
        return raw

    def _show_file_picker(self, text: str) -> str | None:
        """优先展示常用文档；需要时再进入「按文件夹浏览」。"""
        quick = [r for r in get_quick_pick_targets(6) if any(t == r for _, t, _ in self._files)]
        mode = "AI 梳理" if self._ai_mode else "原文追加"
        preview = re.sub(r"\s+", " ", text.strip())[:50]

        if quick:
            labels: list[str] = []
            rel_map: dict[str, str] = {}
            for rel in quick:
                tag = "🌟" if rel == get_default_target() else "⭐"
                lab = f"{tag} {self._short_label(rel)}"
                labels.append(lab)
                rel_map[lab] = rel
            labels.append("📂 在 Finder 里选其他文档…")
            labels.append(NEW_FILE_LABEL)

            picked = self._apple_choose_list(
                labels,
                title=f"⭐ 常用归档（{len(text)} 字 · {mode}）",
                prompt=f"{preview}…",
                ok_button="下一步",
                cancel_button="跳过 😴",
            )
            if not picked:
                return None
            if picked == NEW_FILE_LABEL:
                return self._handle_new_file()
            if picked == "📂 在 Finder 里选其他文档…":
                return self._pick_md_via_finder(text)
            return rel_map.get(picked)

        return self._pick_md_via_finder(text)

    def _pick_md_via_finder(self, text: str) -> str | None:
        """打开 Finder 直接点选 .md（不再多一层中间清单）。"""
        preview = re.sub(r"\s+", " ", text.strip())[:50]
        rel = choose_md_file(
            self._kb_root,
            prompt=f"{preview}…",
        )
        if rel is None:
            return None
        self._load_config()
        self._build_menu()
        return rel

    def _handle_new_file(self) -> str | None:
        rel = choose_new_md_file(self._kb_root)
        if rel:
            self._load_config()
            self._build_menu()
            rumps.notification("Skillless", "已创建", rel)
        return rel

    def _archive_async(self, target: str, text: str) -> None:
        threading.Thread(target=self._archive, args=(target, text), daemon=True).start()

    def _find_action(self, target: str) -> str | None:
        for _, t, a in self._files:
            if t == target:
                return a if a != "__raw_only__" else None
        for key, conf in self._cfg.get("actions", {}).items():
            if conf.get("target") == target:
                return key
        return None

    def _archive(self, target: str, text: str) -> None:
        action = self._find_action(target)
        use_raw = (not self._ai_mode) or (action is None)

        if use_raw:
            action = action or next(iter(self._cfg.get("actions", {})), None)
            if not action:
                rumps.notification("Skillless", "无可用 action", "")
                return
            from bootkit import child_cmd, is_frozen

            if is_frozen():
                cmd = child_cmd(
                    "archiver", action, "--from-stdin", "--no-notify",
                    "--mode", "raw", "--target", target,
                )
                r = subprocess.run(
                    cmd, input=text, capture_output=True, text=True, timeout=60,
                    cwd=str(data_dir()), env=os.environ.copy(),
                )
            else:
                env = {**os.environ, "ARCHIVER_MODE": "raw", "ARCHIVER_TARGET": target}
                r = subprocess.run(
                    [RUN_SH, action], input=text, capture_output=True, text=True, timeout=60, env=env,
                )
            if r.returncode != 0:
                rumps.notification("Skillless · 失败", "", (r.stderr or r.stdout)[:200])
                return
        self._skip_streak = 0
        record_target_usage(target)
        try:
            bump_archived(1)
        except Exception:
            pass
        self._toast(target, _bump_today_count(), True)
        return

        assert action
        if self._ai_preview:
            payload = self._preview_ai(action, text, target)
            if not payload or not payload.get("ok"):
                msg = (payload or {}).get("summary", "AI 梳理失败")
                rumps.notification("Skillless", msg, "检查 API Key 或网络")
                return
            confirmed = self._confirm_preview(payload)
            if not confirmed:
                self._on_user_skip(text)
                return
            self._commit_payload(confirmed)
        else:
            from bootkit import child_cmd, is_frozen

            if is_frozen():
                cmd = child_cmd("archiver", action, "--from-stdin", "--no-notify", "--target", target)
                r = subprocess.run(
                    cmd, input=text, capture_output=True, text=True, timeout=120,
                    cwd=str(data_dir()), env=os.environ.copy(),
                )
            else:
                r = subprocess.run([RUN_SH, action], input=text, capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                rumps.notification("Skillless · 失败", "", (r.stderr or r.stdout)[:200])
                return
            self._skip_streak = 0
            record_target_usage(target)
            self._toast(target, _bump_today_count(), False)

    def _preview_ai(self, action: str, text: str, target: str) -> dict | None:
        from bootkit import child_cmd

        try:
            cmd = child_cmd(
                "archiver", action,
                "--preview-json", "--from-stdin", "--no-notify",
                "--target", target,
            )
            r = subprocess.run(
                cmd, input=text, capture_output=True, text=True, timeout=120,
                cwd=str(data_dir()), env=os.environ.copy(),
            )
        except subprocess.TimeoutExpired:
            return None
        if r.returncode != 0:
            return {"ok": False, "summary": (r.stderr or r.stdout)[:200]}
        try:
            return json.loads(r.stdout)
        except json.JSONDecodeError:
            return {"ok": False, "summary": "JSON 解析失败"}

    def _confirm_preview(self, payload: dict) -> dict | None:
        md = payload.get("markdown", "")
        target = payload.get("target", "")
        show_long_text_preview(md, filename="archiver_preview.md")
        summary = one_line_summary(md)
        snippet = truncate_for_dialog(md)
        out = _display_dialog(
            f"完整预览已在 TextEdit 打开（共 {len(md)} 字）。\n\n"
            f"写入目标：{target}\n\n"
            f"一句话：{summary}\n\n"
            f"摘要：{snippet}",
            title="🧠 确认 AI 梳理结果",
            buttons=("算了", "写入"),
            default_button="写入",
        )
        if not out or "写入" not in out:
            return None
        return payload

    def _commit_payload(self, payload: dict) -> None:
        from bootkit import child_cmd

        try:
            cmd = child_cmd("archiver", "--commit-json", "--no-notify")
            r = subprocess.run(
                cmd, input=json.dumps(payload, ensure_ascii=False),
                capture_output=True, text=True, timeout=60, cwd=str(data_dir()),
            )
        except Exception as e:
            rumps.notification("Skillless", "写入失败", str(e))
            return
        if r.returncode != 0:
            rumps.notification("Skillless", "写入失败", (r.stderr or r.stdout)[:200])
            return
        self._skip_streak = 0
        t = payload.get("target", "")
        if t:
            record_target_usage(t)
        self._toast(t, _bump_today_count(), False)

    def _settings_default_doc(self, _s) -> None:
        """更换默认文档：Finder 里直接点选 .md。"""
        rel = choose_md_file(self._kb_root, prompt="选择新的默认归档文档")
        if not rel:
            return
        set_default_target(rel)
        self._build_menu()
        rumps.notification("Skillless", f"默认 → {self._short_label(rel)}", "🌟 已更新")

    def _toast(self, target: str, count: int, is_raw: bool) -> None:
        tag = "原文" if is_raw else "AI"
        rumps.notification(
            "你的龙虾今天更聪明一些啦 🎉",
            f"已写入 → {target}（{tag}）",
            f"今天共归档 {count} 条",
        )

    def _settings_api(self, _s) -> None:
        msg = f"""在下方输入框粘贴 DeepSeek API Key（sk- 开头）

没有 Key？浏览器打开：
{DEEPSEEK_API_KEYS_URL}"""
        out = _display_dialog(
            msg,
            title="⚙️ 设置 API Key",
            buttons=("取消", "保存"),
            default_button="保存",
            default_answer=get_api_key() or "",
        )
        if not out:
            return
        key = out
        if key.startswith("text returned:"):
            key = key.split(":", 1)[1].strip()
        if key.startswith("sk-"):
            save_api_key(key)
            _load_env_file(data_dir() / ".env")
            rumps.notification("Skillless", "API 已保存 ✅", "已写入 .env")

    def _settings_threshold(self, _s) -> None:
        script = (
            f'display dialog "复制时至少多少字才弹胶囊？（当前 {self._min_length}）" '
            f'default answer "{self._min_length}" '
            'buttons {"取消", "保存"} default button "保存"'
        )
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            return
        val = r.stdout.strip()
        if val.startswith("text returned:"):
            val = val.split(":", 1)[1].strip()
        try:
            n = int(val)
            set_min_length(n)
            self._load_config()
            rumps.notification("Skillless", f"门槛已改为 {n} 字", "")
        except ValueError:
            pass

    def _settings_protect(self, _s) -> None:
        """调最大字数 / 切换代码检测 / 改稳定期。"""
        cur_max = self._max_length
        cur_code = self._skip_code_like
        cur_stable = self._clip_stable_ms
        info = (
            f"当前：\\n"
            f"  最大字数 {cur_max}（超过不弹，0=不限）\\n"
            f"  代码检测：{'开' if cur_code else '关'}\\n"
            f"  稳定期 {cur_stable} ms\\n\\n"
            "格式：max,code,stable\\n"
            "例如：20000,1,700  或  0,0,500"
        )
        default = f"{cur_max},{1 if cur_code else 0},{cur_stable}"
        script = (
            f'display dialog "{info}" default answer "{default}" '
            'buttons {"取消", "保存"} default button "保存" with title "🛡️ 防误触"'
        )
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            return
        val = r.stdout.strip()
        if val.startswith("text returned:"):
            val = val.split(":", 1)[1].strip()
        parts = [p.strip() for p in val.replace("，", ",").split(",")]
        if len(parts) < 3:
            rumps.notification("Skillless", "格式不对", "需要：max,code,stable")
            return
        try:
            new_max = int(parts[0])
            new_code = parts[1] not in ("0", "false", "False", "off", "no")
            new_stable = int(parts[2])
        except ValueError:
            rumps.notification("Skillless", "数字解析失败", val[:80])
            return

        cfg = load_config()
        beh = cfg.get("behavior", {}) or {}
        beh["auto_prompt_max_length"] = max(0, new_max)
        beh["skip_code_like"] = bool(new_code)
        beh["clipboard_stable_ms"] = max(0, new_stable)
        cfg["behavior"] = beh
        from settings_util import save_config

        save_config(cfg)
        self._load_config()
        rumps.notification(
            "Skillless",
            "防误触已更新",
            f"max={beh['auto_prompt_max_length']}, code={'on' if new_code else 'off'}, stable={beh['clipboard_stable_ms']}ms",
        )

    def _settings_blacklist(self, _s) -> None:
        bl = get_blacklist(self._cfg)
        preview = "\\n".join(bl[:8]) + ("\\n…" if len(bl) > 8 else "")
        script = (
            f'display dialog "当前跳过规则（正则）：\\n{preview}\\n\\n'
            f'输入要追加的一条（如 https:// 或某域名），留空只查看：" '
            f'default answer "" buttons {{"关闭", "追加"}} default button "追加"'
        )
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            return
        pat = r.stdout.strip()
        if pat.startswith("text returned:"):
            pat = pat.split(":", 1)[1].strip()
        if pat:
            add_to_blacklist_extra(pat)
            rumps.notification("Skillless", "已追加黑名单", pat[:40])

    def _open_prompts(self, _s) -> None:
        PROMPTS_CUSTOM.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(PROMPTS_CUSTOM)])
        rumps.notification(
            "Skillless",
            "自定义 Prompt",
            "在此目录新建 .md，再登记到 config.yaml 的 custom_prompts",
        )

    def _rerun_onboarding(self, _s) -> None:
        threading.Thread(target=self._run_onboarding_safe_force, daemon=True).start()

    def _run_onboarding_safe_force(self) -> None:
        """重新走引导时同样暂停剪贴板监听。"""
        from settings_util import load_state, save_state

        state = load_state()
        state["onboarding_complete"] = False
        save_state(state)
        self._onboarding_active = True
        self._watch_mode = False
        if hasattr(self, "_watch_item"):
            self._watch_item.title = self._watch_label()
        try:
            run_onboarding(force=True)
            if onboarding_done():
                self._load_config(scan_kb=True)
                self._build_menu()
                self._update_title()
        except Exception as e:
            rumps.notification("Skillless", "新客引导失败", str(e)[:120])
        finally:
            self._onboarding_active = False
            if onboarding_done():
                self._watch_mode = auto_prompt_enabled()
                if hasattr(self, "_watch_item"):
                    self._watch_item.title = self._watch_label()
                self._ensure_hotkey_ready()
                threading.Thread(target=self._deferred_kb_scan, daemon=True).start()

    def _open_kb(self, _s) -> None:
        if self._kb_root.exists():
            subprocess.run(["open", str(self._kb_root)])

    def _open_dashboard(self, _s) -> None:
        """后台 App 必须独立进程跑（webview 主线程要求）。"""
        try:
            from bootkit import child_cmd
            subprocess.Popen(
                child_cmd("dashboard"),
                cwd=str(data_dir()),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except Exception as e:
            rumps.notification("Skillless", "后台启动失败", str(e)[:120])

    def _view_log(self, _s) -> None:
        log = self._kb_root / "_archive_log.md"
        subprocess.run(["open", str(log)] if log.exists() else ["open", str(self._kb_root)])

    def _reload(self, _s) -> None:
        self._load_config()
        self._build_menu()
        self._update_title()
        rumps.notification("Skillless", "已重新加载", "")


def _install_reopen_handler(_app) -> None:
    """让 Spotlight/Finder 再次打开 Skillless 时 → 拉起后台窗口。

    LSUIElement=true 的 App 没有 Dock 图标，用户没有直观地方"再打开"。
    NSApp 收到 reopen 事件（hasVisibleWindows=NO）时帮他开后台。
    """
    try:
        from AppKit import NSApp
        from PyObjCTools import AppHelper  # noqa: F401
        import objc

        def _open_dashboard_subprocess() -> None:
            try:
                from bootkit import child_cmd
                subprocess.Popen(
                    child_cmd("dashboard"),
                    cwd=str(data_dir()),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except Exception:
                pass

        cur = NSApp.delegate()
        if cur is None:
            return

        # 给 rumps 的 delegate 动态注入 applicationShouldHandleReopen:hasVisibleWindows:
        def _reopen(self, sender, flag):  # noqa: ARG001
            _open_dashboard_subprocess()
            return True

        sel = b"applicationShouldHandleReopen:hasVisibleWindows:"
        if not cur.respondsToSelector_(sel):
            method = objc.selector(_reopen, signature=b"B@:@B")
            try:
                cur.__class__.applicationShouldHandleReopen_hasVisibleWindows_ = method  # type: ignore[attr-defined]
            except Exception:
                pass
    except Exception:
        pass


def main() -> None:
    import atexit

    def _on_exit() -> None:
        try:
            from boot import _write_launch_log

            _write_launch_log("menubar", "exited")
        except Exception:
            pass

    atexit.register(_on_exit)
    _load_env_file(data_dir() / ".env")
    try:
        from boot import _write_launch_log

        app = ArchiverApp()
        _install_reopen_handler(app)
        _write_launch_log("menubar", "ready")
        app.run()
    except Exception as e:
        try:
            from boot import _log_crash

            _log_crash(e)
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
