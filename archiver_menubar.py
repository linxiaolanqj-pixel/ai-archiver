#!/usr/bin/env python3
"""AI Archiver 菜单栏 App — 复制即归档 + 新客引导 + 预览确认 + 黑名单"""

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
    add_to_blacklist_extra,
    get_api_key,
    get_blacklist,
    get_default_target,
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
    set_min_length,
    should_skip_text,
)
from onboarding import _display_dialog, run_onboarding  # _display_dialog 用于短确认弹窗
from picker_util import choose_archive_target, choose_md_file, choose_new_md_file
from ui_util import one_line_summary, show_long_text_preview, truncate_for_dialog


SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"
RUN_SH = SCRIPT_DIR / "run.sh"
ARCHIVER_PY = SCRIPT_DIR / "archiver.py"
STATE_PATH = SCRIPT_DIR / ".state.json"
PROMPTS_CUSTOM = SCRIPT_DIR / "prompts" / "custom"

POLL_INTERVAL = 1.0
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


def _read_clipboard() -> str:
    try:
        out = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=5)
        return out.stdout
    except Exception:
        return ""


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
        super().__init__("📥 归档", quit_button=None)

        self._cfg: dict = {}
        self._kb_root = Path.home()
        self._files: list[tuple[str, str, str]] = []
        self._min_length = 100
        self._mute_after = 2
        self._ai_preview = True

        # 未完成新客引导前：不监听剪贴板，避免设置过程中弹「是否归档」
        self._onboarding_active = not onboarding_done()
        self._watch_mode = onboarding_done() and not self._onboarding_active
        self._dialog_open = False
        self._last_clipboard = ""
        self._skip_streak = 0
        self._ai_mode = True

        self._load_config()
        self._build_menu()
        self._update_title()

        self._last_clipboard = _read_clipboard()
        self._timer = rumps.Timer(self._poll_clipboard, POLL_INTERVAL)
        self._timer.start()

        if not onboarding_done():
            threading.Thread(target=self._run_onboarding_safe, daemon=True).start()

    def _run_onboarding_safe(self) -> None:
        self._onboarding_active = True
        self._watch_mode = False
        if hasattr(self, "_watch_item"):
            self._watch_item.title = self._watch_label()
        try:
            if run_onboarding():
                self._load_config()
                self._build_menu()
                self._update_title()
        except Exception as e:
            rumps.notification("AI Archiver", "新客引导失败", str(e)[:120])
        finally:
            self._onboarding_active = False
            if onboarding_done():
                self._watch_mode = True
                if hasattr(self, "_watch_item"):
                    self._watch_item.title = self._watch_label()

    def _update_title(self) -> None:
        p = str(self._kb_root)
        short = p if len(p) <= 22 else "…" + p[-20:]
        self.title = f"📥 {short}"

    def _load_config(self) -> None:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            self._cfg = yaml.safe_load(f) or {}
        self._kb_root = kb_root(self._cfg)
        beh = self._cfg.get("behavior", {}) or {}
        self._min_length = int(beh.get("auto_prompt_min_length", 100))
        self._mute_after = int(beh.get("auto_mute_after_skips", 2))
        self._ai_preview = bool(beh.get("ai_preview_before_write", True))

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

        # 递归扫描知识库内全部子文件夹中的 .md（含子目录）
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
        if len(p.parts) == 1:
            return p.stem
        return f"{p.stem} · {p.parent}"

    def _build_menu(self) -> None:
        self.menu.clear()

        default = get_default_target()
        if default:
            self.menu.add(
                rumps.MenuItem(
                    f"🌟 一键归档到「{self._short_label(default)}」",
                    callback=self._make_handler(default),
                )
            )
        for rel in get_quick_pick_targets(4):
            if rel == default:
                continue
            if not any(t == rel for _, t, _ in self._files):
                continue
            self.menu.add(
                rumps.MenuItem(
                    f"⭐ {self._short_label(rel)}",
                    callback=self._make_handler(rel),
                )
            )

        self.menu.add(rumps.MenuItem("📂 选择写入目标…", callback=self._pick_from_all_folders))
        self.menu.add(rumps.MenuItem(NEW_FILE_LABEL, callback=self._main_new_file))
        self.menu.add(rumps.separator)

        self._mode_item = rumps.MenuItem(self._mode_label(), callback=self._toggle_mode)
        self.menu.add(self._mode_item)
        self._watch_item = rumps.MenuItem(self._watch_label(), callback=self._toggle_watch)
        self.menu.add(self._watch_item)

        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem(f"📁 知识库：{self._kb_root.name}", callback=self._open_kb))
        self.menu.add(rumps.MenuItem("🌟 更换默认归档文档…", callback=self._settings_default_doc))
        self.menu.add(rumps.MenuItem("⚙️ 设置 API Key…", callback=self._settings_api))
        self.menu.add(rumps.MenuItem("📏 调整复制门槛…", callback=self._settings_threshold))
        self.menu.add(rumps.MenuItem("🚫 管理跳过黑名单…", callback=self._settings_blacklist))
        self.menu.add(rumps.MenuItem("📂 打开 Prompt 目录", callback=self._open_prompts))
        self.menu.add(rumps.MenuItem("🎓 重新走新客引导", callback=self._rerun_onboarding))
        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("📜 查看归档日志", callback=self._view_log))
        self.menu.add(rumps.MenuItem("🔄 重新加载配置", callback=self._reload))
        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("退出", callback=rumps.quit_application))

    def _mode_label(self) -> str:
        return f"🧠 模式：{'AI 梳理' if self._ai_mode else '原文追加'}（点击切换）"

    def _watch_label(self) -> str:
        if self._onboarding_active:
            return "⏸ 新客引导中（暂不监听复制）"
        return f"{'✅' if self._watch_mode else '⬜'} 复制后自动询问（≥{self._min_length} 字）"

    def _make_handler(self, target: str):
        def handler(_s):
            text = _read_clipboard()
            if not text.strip():
                rumps.notification("AI Archiver", "剪贴板为空", "先 Cmd+C 复制")
                return
            self._archive_async(target, text)
        return handler

    def _pick_from_all_folders(self, _s) -> None:
        text = _read_clipboard()
        if not text.strip():
            rumps.notification("AI Archiver", "剪贴板为空", "先 Cmd+C 复制一段文字")
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
            rumps.notification("AI Archiver", "剪贴板为空", "先 Cmd+C")
            return
        t = self._handle_new_file()
        if t:
            self._archive_async(t, text)

    def _toggle_mode(self, _s) -> None:
        self._ai_mode = not self._ai_mode
        self._mode_item.title = self._mode_label()

    def _toggle_watch(self, _s) -> None:
        self._watch_mode = not self._watch_mode
        self._skip_streak = 0
        self._watch_item.title = self._watch_label()

    def _poll_clipboard(self, _s) -> None:
        if self._onboarding_active or not self._watch_mode or self._dialog_open:
            return
        cur = _read_clipboard()
        if not cur or cur == self._last_clipboard:
            return
        self._last_clipboard = cur
        if should_skip_text(cur, self._min_length, self._cfg):
            return
        threading.Thread(target=self._ask_and_archive, args=(cur,), daemon=True).start()

    def _ask_and_archive(self, text: str) -> None:
        self._dialog_open = True
        try:
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
            self._watch_item.title = self._watch_label()
            rumps.notification(
                "AI Archiver · 免打扰",
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
        """打开 Finder 点选 .md，或新建（不再列长清单）。"""
        preview = re.sub(r"\s+", " ", text.strip())[:50]
        rel = choose_archive_target(
            self._kb_root,
            prompt=f"{preview}…",
        )
        if rel is None:
            return None
        # 刷新菜单（可能选了新文件或之前未扫描到的路径）
        self._load_config()
        self._build_menu()
        return rel

    def _handle_new_file(self) -> str | None:
        rel = choose_new_md_file(self._kb_root)
        if rel:
            self._load_config()
            self._build_menu()
            rumps.notification("AI Archiver", "已创建", rel)
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
                rumps.notification("AI Archiver", "无可用 action", "")
                return
            env = {**os.environ, "ARCHIVER_MODE": "raw", "ARCHIVER_TARGET": target}
            r = subprocess.run(
                [RUN_SH, action], input=text, capture_output=True, text=True, timeout=60, env=env,
            )
            if r.returncode != 0:
                rumps.notification("AI Archiver · 失败", "", (r.stderr or r.stdout)[:200])
                return
        self._skip_streak = 0
        record_target_usage(target)
        self._toast(target, _bump_today_count(), True)
        return

        assert action
        if self._ai_preview:
            payload = self._preview_ai(action, text, target)
            if not payload or not payload.get("ok"):
                msg = (payload or {}).get("summary", "AI 梳理失败")
                rumps.notification("AI Archiver", msg, "检查 API Key 或网络")
                return
            confirmed = self._confirm_preview(payload)
            if not confirmed:
                self._on_user_skip(text)
                return
            self._commit_payload(confirmed)
        else:
            r = subprocess.run([RUN_SH, action], input=text, capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                rumps.notification("AI Archiver · 失败", "", (r.stderr or r.stdout)[:200])
                return
            self._skip_streak = 0
            record_target_usage(target)
            self._toast(target, _bump_today_count(), False)

    def _preview_ai(self, action: str, text: str, target: str) -> dict | None:
        try:
            r = subprocess.run(
                [
                    PY, str(ARCHIVER_PY), action,
                    "--preview-json", "--from-stdin", "--no-notify",
                    "--target", target,
                ],
                input=text, capture_output=True, text=True, timeout=120, env=os.environ.copy(),
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
        try:
            r = subprocess.run(
                [PY, str(ARCHIVER_PY), "--commit-json", "--no-notify"],
                input=json.dumps(payload, ensure_ascii=False),
                capture_output=True, text=True, timeout=60,
            )
        except Exception as e:
            rumps.notification("AI Archiver", "写入失败", str(e))
            return
        if r.returncode != 0:
            rumps.notification("AI Archiver", "写入失败", (r.stderr or r.stdout)[:200])
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
        rumps.notification("AI Archiver", f"默认 → {self._short_label(rel)}", "🌟 已更新")

    def _toast(self, target: str, count: int, is_raw: bool) -> None:
        tag = "原文" if is_raw else "AI"
        rumps.notification(
            "你的龙虾今天更聪明一些啦 🎉",
            f"已写入 → {target}（{tag}）",
            f"今天共归档 {count} 条",
        )

    def _settings_api(self, _s) -> None:
        msg = f"""请粘贴 DeepSeek API Key
（sk- 开头）

没有 Key？浏览器打开：
{DEEPSEEK_API_KEYS_URL}"""
        out = _display_dialog(
            msg,
            title="⚙️ 设置 API Key",
            buttons=("取消", "保存"),
            default_button="保存",
        )
        if not out:
            return
        key = out
        if key.startswith("text returned:"):
            key = key.split(":", 1)[1].strip()
        if key.startswith("sk-"):
            save_api_key(key)
            _load_env_file(SCRIPT_DIR / ".env")
            rumps.notification("AI Archiver", "API 已保存 ✅", "已写入 .env")

    def _settings_threshold(self, _s) -> None:
        script = (
            f'display dialog "复制多少字后才弹窗？（当前 {self._min_length}）" '
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
            self._watch_item.title = self._watch_label()
            rumps.notification("AI Archiver", f"门槛已改为 {n} 字", "")
        except ValueError:
            pass

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
            rumps.notification("AI Archiver", "已追加黑名单", pat[:40])

    def _open_prompts(self, _s) -> None:
        PROMPTS_CUSTOM.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(PROMPTS_CUSTOM)])
        rumps.notification(
            "AI Archiver",
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
                self._load_config()
                self._build_menu()
                self._update_title()
        except Exception as e:
            rumps.notification("AI Archiver", "新客引导失败", str(e)[:120])
        finally:
            self._onboarding_active = False
            if onboarding_done():
                self._watch_mode = True
                if hasattr(self, "_watch_item"):
                    self._watch_item.title = self._watch_label()

    def _open_kb(self, _s) -> None:
        if self._kb_root.exists():
            subprocess.run(["open", str(self._kb_root)])

    def _view_log(self, _s) -> None:
        log = self._kb_root / "_archive_log.md"
        subprocess.run(["open", str(log)] if log.exists() else ["open", str(self._kb_root)])

    def _reload(self, _s) -> None:
        self._load_config()
        self._build_menu()
        self._update_title()
        rumps.notification("AI Archiver", "已重新加载", "")


def main() -> None:
    _load_env_file(SCRIPT_DIR / ".env")
    ArchiverApp().run()


if __name__ == "__main__":
    main()
