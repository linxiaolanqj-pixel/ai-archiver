#!/usr/bin/env python3
"""AI Archiver 菜单栏 App

两种使用方式：
  1) 主动：点屏幕右上角 📥 归档 → 选目标文件 → 归档当前剪贴板
  2) 被动（默认开启）：Cmd+C 复制 ≥100 字时，自动弹"归档到哪个文件"对话框

行为细节：
  - 一步式选择器：列出知识库里所有 .md + 「+ 新建文件...」
  - 全局模式开关：菜单里切「AI 梳理 / 原文追加」
  - 跳过两次自动免打扰：连续 cancel 两次自动暂停监听
  - Toast 显示今日归档计数 + "你的龙虾今天更聪明一些啦🎉"

启动：
    ~/tools/ai-archiver/menubar.sh start
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import subprocess
import threading
from pathlib import Path

import rumps
import yaml


SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"
RUN_SH = SCRIPT_DIR / "run.sh"
STATE_PATH = SCRIPT_DIR / ".state.json"

POLL_INTERVAL = 1.0
DEFAULT_MIN_LENGTH = 100
DEFAULT_MUTE_AFTER = 2

NEW_FILE_LABEL = "➕ 新建文件…"
CANCEL_LABEL = "🙅 跳过"


# ---------------- 工具 ----------------


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


def _applescript_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _today() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d")


def _load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        STATE_PATH.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


# ---------------- App ----------------


class ArchiverApp(rumps.App):
    def __init__(self):
        super().__init__("📥 归档", quit_button=None)

        self._cfg: dict = {}
        self._kb_root: Path = Path.home()
        # 文件菜单项: [(label, target_filename, action_key_for_ai_mode)]
        self._files: list[tuple[str, str, str]] = []
        self._min_length: int = DEFAULT_MIN_LENGTH
        self._mute_after: int = DEFAULT_MUTE_AFTER

        # 运行时状态
        self._watch_mode: bool = True
        self._dialog_open: bool = False
        self._last_clipboard: str = ""
        self._skip_streak: int = 0
        # 全局模式：True=AI 梳理（默认）、False=原文追加
        self._ai_mode: bool = True

        self._load_config()
        self._build_menu()

        # 启动时记录当前剪贴板，避免立刻弹
        self._last_clipboard = _read_clipboard()

        self._timer = rumps.Timer(self._poll_clipboard, POLL_INTERVAL)
        self._timer.start()

    # ---------------- 配置 ----------------

    def _load_config(self) -> None:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            self._cfg = yaml.safe_load(f)
        self._kb_root = Path(os.path.expanduser(self._cfg["knowledge_base"]["root"]))

        beh = self._cfg.get("behavior", {}) or {}
        self._min_length = int(beh.get("auto_prompt_min_length", DEFAULT_MIN_LENGTH))
        self._mute_after = int(beh.get("auto_mute_after_skips", DEFAULT_MUTE_AFTER))

        # 从 actions 推导文件列表：按 target 去重，每个文件取第一个匹配的 action 当 AI 入口
        target_to_action: dict[str, tuple[str, str]] = {}  # target -> (label, action_key)
        for action_key, conf in self._cfg.get("actions", {}).items():
            target = conf.get("target")
            if not target:
                continue
            if target in target_to_action:
                continue
            label = conf.get("label") or target
            # label 里"追加到"前缀去掉，更紧凑
            label = re.sub(r"^(追加到|生成|提取)\s*", "", label)
            target_to_action[target] = (label, action_key)

        # 再扫描知识库目录里实际存在的 .md，把"配置里没绑但磁盘上有"的也加进来
        if self._kb_root.exists():
            for md_path in sorted(self._kb_root.glob("*.md")):
                name = md_path.name
                # 跳过 README / 日志
                if name.lower() in ("readme.md", "_archive_log.md"):
                    continue
                if name not in target_to_action:
                    target_to_action[name] = (md_path.stem, "__raw_only__")

        self._files = [
            (label, target, action_key)
            for target, (label, action_key) in target_to_action.items()
        ]

    # ---------------- 菜单 ----------------

    def _build_menu(self) -> None:
        self.menu.clear()

        for label, target, _action in self._files:
            it = rumps.MenuItem(
                f"📝 {label}",
                callback=self._make_main_handler(target),
            )
            self.menu.add(it)

        self.menu.add(rumps.MenuItem(NEW_FILE_LABEL, callback=self._main_new_file))
        self.menu.add(rumps.separator)

        # 模式开关
        self._mode_item = rumps.MenuItem(
            self._mode_label(),
            callback=self._toggle_mode,
        )
        self.menu.add(self._mode_item)

        # 监听开关
        self._watch_item = rumps.MenuItem(
            self._watch_label(),
            callback=self._toggle_watch,
        )
        self.menu.add(self._watch_item)

        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("📂 打开知识库", callback=self._open_kb))
        self.menu.add(rumps.MenuItem("📜 查看归档日志", callback=self._view_log))
        self.menu.add(rumps.MenuItem("🔄 重新加载配置", callback=self._reload))
        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("退出", callback=rumps.quit_application))

    def _mode_label(self) -> str:
        return f"🧠 模式：{'AI 梳理' if self._ai_mode else '原文追加'}（点击切换）"

    def _watch_label(self) -> str:
        flag = "✅" if self._watch_mode else "⬜"
        return f"{flag} 复制后自动询问（≥{self._min_length} 字）"

    # ---------------- 主动归档（点菜单触发） ----------------

    def _make_main_handler(self, target: str):
        def handler(_sender):
            text = _read_clipboard()
            if not text.strip():
                rumps.notification(
                    "AI Archiver",
                    "剪贴板为空",
                    "先 Cmd+C 复制一段文字再点菜单",
                )
                return
            self._archive_async(target, text)
        return handler

    def _main_new_file(self, _sender) -> None:
        text = _read_clipboard()
        if not text.strip():
            rumps.notification(
                "AI Archiver",
                "剪贴板为空",
                "先 Cmd+C 复制一段文字再新建文件",
            )
            return
        new_target = self._handle_new_file()
        if new_target:
            self._archive_async(new_target, text)

    # ---------------- 模式 / 监听切换 ----------------

    def _toggle_mode(self, _sender) -> None:
        self._ai_mode = not self._ai_mode
        self._mode_item.title = self._mode_label()
        msg = "AI 梳理：调 LLM 结构化后写入" if self._ai_mode else "原文追加：直接把原文追加，不调 LLM"
        rumps.notification("AI Archiver · 模式切换", self._mode_label().split("（")[0], msg)

    def _toggle_watch(self, _sender) -> None:
        self._watch_mode = not self._watch_mode
        self._skip_streak = 0  # 手动开关重置 streak
        self._watch_item.title = self._watch_label()
        state = "已开启" if self._watch_mode else "已暂停"
        rumps.notification("AI Archiver", f"剪贴板监听：{state}", "")

    # ---------------- 被动监听 ----------------

    def _poll_clipboard(self, _sender) -> None:
        if not self._watch_mode or self._dialog_open:
            return
        current = _read_clipboard()
        if not current or current == self._last_clipboard:
            return
        self._last_clipboard = current
        if len(current.strip()) < self._min_length:
            return
        threading.Thread(
            target=self._ask_and_archive,
            args=(current,),
            daemon=True,
        ).start()

    def _ask_and_archive(self, text: str) -> None:
        self._dialog_open = True
        try:
            picked_target = self._show_file_picker(text, mode_hint="auto")
            if picked_target == "__NEW_FILE__":
                picked_target = self._handle_new_file()

            if not picked_target:
                # 用户跳过
                self._skip_streak += 1
                if self._skip_streak >= self._mute_after:
                    self._watch_mode = False
                    self._watch_item.title = self._watch_label()
                    rumps.notification(
                        "AI Archiver · 进入免打扰",
                        f"已连续跳过 {self._skip_streak} 次",
                        "在菜单里手动重新打开「✅ 复制后自动询问」即可恢复",
                    )
                return

            # 用户选了 → 归档（这里同步调，已经在子线程里）
            self._archive(picked_target, text)
        finally:
            self._dialog_open = False

    # ---------------- 选择器 / 新建文件 ----------------

    def _show_file_picker(self, text: str, mode_hint: str = "auto") -> str | None:
        """弹出"选文件"对话框，返回选中的 target 文件名 / "__NEW_FILE__" / None(跳过)。"""
        preview = re.sub(r"\s+", " ", text.strip())[:50]
        preview_esc = _applescript_escape(preview)
        mode_str = "AI 梳理" if self._ai_mode else "原文追加"

        # 选项列表：现有文件 + 新建文件
        items = []
        for label, target, _action in self._files:
            items.append(f"📝 {label}")
        items.append(NEW_FILE_LABEL)

        items_apple = ", ".join(f'"{_applescript_escape(x)}"' for x in items)

        title_text = f"刚复制了 {len(text)} 字 · 当前模式：{mode_str}"
        prompt_text = f"{preview_esc}…"

        script = (
            f'set actionList to {{{items_apple}}}\n'
            f'set theChoice to choose from list actionList '
            f'with prompt "{_applescript_escape(prompt_text)}" '
            f'with title "{_applescript_escape(title_text)}" '
            f'default items {{item 1 of actionList}} '
            f'OK button name "归档" cancel button name "跳过"\n'
            f'if theChoice is false then\n'
            f'  return "__CANCELLED__"\n'
            f'else\n'
            f'  return item 1 of theChoice\n'
            f'end if'
        )

        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=300,
            )
        except subprocess.TimeoutExpired:
            return None
        except Exception:
            return None

        raw = result.stdout.strip()
        if not raw or raw == "__CANCELLED__":
            return None
        if raw == NEW_FILE_LABEL:
            return "__NEW_FILE__"
        # 从 "📝 顺手买信息" 还原成 target 文件名
        clean = raw[2:].strip() if raw.startswith("📝") else raw
        for label, target, _action in self._files:
            if label == clean:
                return target
        return None

    def _handle_new_file(self) -> str | None:
        """让用户新建一个 .md 文件，返回新文件名（带扩展名）。"""
        script = (
            'set kbPath to "' + _applescript_escape(str(self._kb_root)) + '"\n'
            'set theChoice to choose from list {"⌨️ 直接输入文件名（自动建在知识库里）", "📂 在 Finder 里打开知识库（自己建好后下次自动出现在列表）"} '
            'with prompt "怎么新建？" with title "AI Archiver · 新建文件" '
            'OK button name "下一步" cancel button name "取消"\n'
            'if theChoice is false then\n'
            '  return "__CANCELLED__"\n'
            'else\n'
            '  return item 1 of theChoice\n'
            'end if'
        )
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=120,
            )
        except Exception:
            return None

        choice = result.stdout.strip()
        if not choice or choice == "__CANCELLED__":
            return None

        if choice.startswith("📂"):
            subprocess.run(["open", str(self._kb_root)])
            rumps.notification(
                "AI Archiver",
                "已打开知识库",
                "在 Finder 里新建好 .md 文件，下次复制时它会自动出现在列表里",
            )
            return None

        # 输入文件名
        name_script = (
            'set theName to text returned of (display dialog "新文件名（带不带 .md 都行）：" '
            'default answer "" with title "AI Archiver · 新建文件" buttons {"取消", "创建"} default button "创建")\n'
            'return theName'
        )
        try:
            r2 = subprocess.run(
                ["osascript", "-e", name_script],
                capture_output=True, text=True, timeout=120,
            )
        except Exception:
            return None
        if r2.returncode != 0:
            return None

        name = r2.stdout.strip()
        if not name:
            return None
        # 清理 + 自动补 .md
        name = re.sub(r"[^\w\u4e00-\u9fff\-. ]", "", name).strip()
        if not name:
            rumps.notification("AI Archiver", "文件名无效", "只允许中英文/数字/空格/-/.")
            return None
        if not name.lower().endswith(".md"):
            name += ".md"

        target_path = self._kb_root / name
        if not target_path.exists():
            target_path.write_text(f"# {target_path.stem}\n", encoding="utf-8")
            # 刷新文件列表 + 菜单
            self._load_config()
            self._build_menu()
            rumps.notification("AI Archiver", "已新建", str(name))
        return name

    # ---------------- 调归档器 ----------------

    def _archive_async(self, target: str, text: str) -> None:
        threading.Thread(
            target=self._archive,
            args=(target, text),
            daemon=True,
        ).start()

    def _archive(self, target: str, text: str) -> None:
        # target -> action 映射；如果是磁盘扫到的"无 action"文件，强制走 raw
        action_key = "__raw_only__"
        for _label, t, a in self._files:
            if t == target:
                action_key = a
                break

        env = os.environ.copy()
        if action_key == "__raw_only__" or not self._ai_mode:
            env["ARCHIVER_MODE"] = "raw"
            # raw 模式不需要绑定 prompt，但 archiver.py 还是需要一个有效的 action
            # 我们临时找一个写到同一个 target 的 action；找不到就用第一个 action（section 模板会被 raw 模式重写）
            real_action = self._find_action_for_target(target) or self._first_action()
            if not real_action:
                rumps.notification("AI Archiver", "配置异常", "config.yaml 里没有任何 action")
                return
        else:
            real_action = action_key

        try:
            result = subprocess.run(
                [str(RUN_SH), real_action],
                input=text,
                capture_output=True,
                text=True,
                timeout=120,
                env=env,
            )
        except subprocess.TimeoutExpired:
            rumps.notification("AI Archiver", "超时", "LLM 调用超过 120 秒")
            return
        except Exception as e:
            rumps.notification("AI Archiver", "出错", str(e))
            return

        if result.returncode != 0:
            msg = (result.stderr or result.stdout).strip()[:250] or "未知错误"
            rumps.notification("AI Archiver · 失败", real_action, msg)
            return

        # 成功：重置 skip streak，更新今日计数，弹 toast
        self._skip_streak = 0
        count = self._bump_today_count()
        self._toast_success(target, count, env.get("ARCHIVER_MODE") == "raw")

    def _find_action_for_target(self, target: str) -> str | None:
        for action_key, conf in self._cfg.get("actions", {}).items():
            if conf.get("target") == target:
                return action_key
        return None

    def _first_action(self) -> str | None:
        for action_key in self._cfg.get("actions", {}):
            return action_key
        return None

    # ---------------- 计数 + Toast ----------------

    def _bump_today_count(self) -> int:
        state = _load_state()
        today = _today()
        if state.get("date") != today:
            state = {"date": today, "count": 0}
        state["count"] = int(state.get("count", 0)) + 1
        _save_state(state)
        return state["count"]

    def _toast_success(self, target: str, count: int, is_raw: bool) -> None:
        mode_tag = "原文" if is_raw else "AI 梳理"
        title = "你的龙虾今天更聪明一些啦 🎉"
        subtitle = f"已写入 → {target}（{mode_tag}）"
        body = f"今天共归档 {count} 条"
        try:
            # rumps.notification 支持 title/subtitle/message
            rumps.notification(title, subtitle, body)
        except Exception:
            # 兜底：用 osascript
            script = (
                f'display notification "{_applescript_escape(body)}" '
                f'with title "{_applescript_escape(title)}" '
                f'subtitle "{_applescript_escape(subtitle)}"'
            )
            subprocess.run(["osascript", "-e", script], capture_output=True)

    # ---------------- 其它菜单项 ----------------

    def _open_kb(self, _sender) -> None:
        if self._kb_root and self._kb_root.exists():
            subprocess.run(["open", str(self._kb_root)])
        else:
            rumps.notification("AI Archiver", "知识库不存在", str(self._kb_root))

    def _view_log(self, _sender) -> None:
        log = self._kb_root / "_archive_log.md"
        if log.exists():
            subprocess.run(["open", str(log)])
        else:
            rumps.notification("AI Archiver", "无归档日志", "还没归档过任何内容")

    def _reload(self, _sender) -> None:
        self._load_config()
        self._build_menu()
        rumps.notification("AI Archiver", "已重新加载", "config.yaml + 知识库文件列表都已刷新")


def main() -> None:
    _load_env_file(SCRIPT_DIR / ".env")
    ArchiverApp().run()


if __name__ == "__main__":
    main()
