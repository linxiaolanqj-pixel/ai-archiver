#!/usr/bin/env python3
"""Skillless 后台管理 App。

五个 Tab：首页 / 历史记录 / 黑名单 / 日志 / 反馈
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
    count_records,
    get_last_record,
    get_stats,
    get_text_for,
    list_records,
)
from settings_util import (
    add_manual_skip,
    display_target,
    get_app_theme,
    get_default_target,
    get_dictionary as _get_skip_dict,
    get_hotkeys,
    get_quick_pick_targets,
    kb_root,
    load_config,
    load_state,
    remove_skip,
    resolve_target_path,
    save_state,
    set_app_theme,
    set_default_target,
    set_hotkey,
)
from dictionary_util import (
    load_dictionary,
    add_entry as dict_add_entry,
    delete_entry as dict_delete_entry,
)
from profile_util import (
    ensure_profile,
    load_profile,
    profile_dir_path,
    save_profile_part as _profile_save_part,
)
from picker_util import choose_md_file, choose_new_md_file
from hotkey_util import is_reasonable_hotkey, normalize_hotkey
from telemetry import track as _track, summary as _track_summary, recent as _track_recent

from app_paths import data_dir, resource_dir

SCRIPT_DIR = resource_dir()
DASHBOARD_DIR = resource_dir() / "dashboard"
PY = str(resource_dir() / ".venv/bin/python") if (resource_dir() / ".venv/bin/python").exists() else sys.executable
ARCHIVER_PY = resource_dir() / "archiver.py"

APP_LOGS: list[tuple[str, str]] = [
    ("clip_watcher.log", "复制监听"),
    ("capsule_spawn.log", "胶囊启动"),
    ("last_launch.log", "启动记录"),
    ("startup.log", "报错详情"),
    ("feedback.log", "反馈意见"),
]


class DashboardApi:
    """暴露给前端的 API。"""

    def __init__(self) -> None:
        self._window = None

    def get_overview(self) -> dict:
        cfg = load_config()
        stats = get_stats()
        last = get_last_record()
        default = get_default_target()
        default_path = str(resolve_target_path(default, cfg)) if default else ""
        return {
            "kb_root": str(kb_root(cfg)),
            "default_target": default,
            "default_target_display": display_target(default),
            "default_target_path": default_path,
            "favorites": [
                {"raw": f, "display": display_target(f)} for f in get_quick_pick_targets(8)
            ],
            "stats": stats,
            "last_record": last or {},
            "app_theme": get_app_theme(),
        }

    def update_app_theme(self, theme: str) -> dict:
        t = set_app_theme(theme)
        _track("click", "theme_toggle", scope="dashboard", props={"theme": t})
        return {"ok": True, "theme": t}

    # —— 今日 memory ——
    def memory_stats(self) -> dict:
        """轻量：返回今日 text 记录数 + 是否已生成缓存。不调 LLM。"""
        from datetime import datetime
        today_str = datetime.now().strftime("%Y-%m-%d")
        today_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        day_start = int(today_dt.timestamp())

        state = load_state()
        cache = state.get("daily_memory") or {}

        n = 0
        for r in list_records(limit=10**9):
            if int(r.get("ts", 0)) < day_start:
                break
            if r.get("type") == "text":
                n += 1

        is_cached = cache.get("date") == today_str and bool(cache.get("content"))
        return {
            "today_records": n,
            "cached": is_cached,
            "content": cache.get("content", "") if is_cached else "",
            "generated_ts": cache.get("ts", 0) if is_cached else 0,
            "source_count": cache.get("source_count", 0) if is_cached else 0,
            "date": today_str,
        }

    def regen_today_memory(self) -> dict:
        """调 LLM 生成今日 memory（同步，5-15s）。"""
        from datetime import datetime
        import time as _t
        today_str = datetime.now().strftime("%Y-%m-%d")
        today_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        day_start = int(today_dt.timestamp())

        recs = []
        for r in list_records(limit=10**9):
            if int(r.get("ts", 0)) < day_start:
                break
            if r.get("type") == "text":
                recs.append(r)

        if not recs:
            return {"ok": False, "error": "今天还没复制任何文字"}

        chunks = []
        total_chars = 0
        for r in recs[:60]:
            t = get_text_for(r)
            if not t:
                continue
            t = t.strip()[:600]
            chunks.append(t)
            total_chars += len(t)
            if total_chars > 12000:
                break
        big = "\n\n---\n\n".join(chunks)

        sys_prompt = (
            "你是用户的「学习日志」助理。下面是用户今天复制 / 归档的内容片段（多条以 --- 分隔）。\n"
            "请用中文输出一段 120-200 字的「今日 memory」摘要，结构如下：\n"
            "1) 第一行：一句话概括今天主要在思考 / 学习什么，**关键词加粗**。\n"
            "2) 接着用 - 列 2-4 条分主题的要点，每条 20-35 字，描述「学到了什么」而非「复制了什么」。\n"
            "禁止：列表超过 4 条、复述具体片段、添加额外的前后缀解释。直接输出 markdown 正文。"
        )

        from quick_archive import _call_deepseek_stream, _load_env
        _load_env()
        acc = ""
        err = None
        for kind, payload in _call_deepseek_stream(sys_prompt, big):
            if kind == "error":
                err = payload
                break
            acc += payload
        if err:
            return {"ok": False, "error": err}

        content = acc.strip()
        state = load_state()
        state["daily_memory"] = {
            "date": today_str,
            "content": content,
            "ts": int(_t.time()),
            "source_count": len(recs),
        }
        save_state(state)
        _track("click", "regen_memory", scope="dashboard",
               props={"source_count": len(recs), "len": len(content)})
        return {
            "ok": True,
            "content": content,
            "cached": False,
            "date": today_str,
            "generated_ts": int(_t.time()),
            "source_count": len(recs),
        }

    # —— 埋点 ——
    def track(self, kind: str, name: str, props: dict | None = None) -> dict:
        """前端通用埋点入口：view / click。"""
        _track(kind, name, scope="dashboard", props=props)
        return {"ok": True}

    def telemetry_summary(self, days: int = 7) -> dict:
        return _track_summary(days=days)

    def telemetry_recent(self, limit: int = 50) -> list:
        return _track_recent(limit=limit)

    def list_history(
        self,
        kind: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """分页：每次默认 50 条。回包带 total 让前端做「还有更多」判断。"""
        records = list_records(limit=limit, kind=kind, offset=offset)
        out = []
        for r in records:
            item = dict(r)
            if item.get("type") == "image":
                p = item.get("img_path")
                if p and Path(p).exists():
                    item["img_url"] = Path(p).resolve().as_uri()
            out.append(item)
        return {
            "items": out,
            "total": count_records(kind=kind),
            "offset": offset,
            "limit": limit,
        }

    def get_record_text(self, ts: int) -> dict:
        ts_i = int(ts)
        # 用全量 + 单次扫描；mtime 缓存命中时 O(N) 内存遍历，很快
        for r in list_records(limit=10**9):
            if int(r.get("ts", 0)) == ts_i:
                return {"ok": True, "text": get_text_for(r)}
        return {"ok": False}

    def clear_history(self) -> dict:
        clear_history()
        return {"ok": True}

    def get_skip_dict(self) -> dict:
        """黑名单 / 跳过规则（manual + auto + builtin）。"""
        return _get_skip_dict()

    def add_skip(self, pattern: str) -> dict:
        ok = add_manual_skip(pattern)
        return {"ok": ok, "dict": _get_skip_dict()}

    def remove_skip(self, pattern: str, scope: str = "manual") -> dict:
        ok = remove_skip(pattern, scope=scope)
        return {"ok": ok, "dict": _get_skip_dict()}

    # —— 纠错词典（路线 A）——
    def get_dictionary(self) -> dict:
        """纠错词典内容：{"entries": [...]}。"""
        try:
            return load_dictionary()
        except Exception:
            return {"entries": []}

    def add_dictionary_entry(self, wrong: str, right: str, source: str = "manual") -> dict:
        try:
            r = dict_add_entry(wrong, right, ctx="dashboard", source=source)
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}
        _track("click", "dict_add", scope="dashboard",
               props={"ok": bool(r.get("ok")), "source": source})
        return r

    def delete_dictionary_entry(self, wrong: str) -> dict:
        try:
            r = dict_delete_entry(wrong)
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}
        _track("click", "dict_del", scope="dashboard",
               props={"ok": bool(r.get("ok"))})
        return r

    # —— 三层档案（SOUL / USER / TOOLS）——
    def get_profile(self) -> dict:
        """后台「档案」Tab 拉取三份 .md 当前内容。"""
        try:
            return load_profile()
        except Exception:
            return {"soul": "", "user": "", "tools": ""}

    def save_profile_part(self, kind: str, content: str) -> dict:
        """保存某一份档案。kind 只能是 soul|user|tools。"""
        try:
            r = _profile_save_part(kind, content)
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}
        _track("click", "save_profile", scope="dashboard",
               props={"kind": kind, "ok": bool(r.get("ok"))})
        return r

    def open_profile_dir(self) -> dict:
        """在 Finder 中打开 profile 目录。"""
        try:
            subprocess.Popen(["open", profile_dir_path()])
            _track("click", "open_profile_dir", scope="dashboard")
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}

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

    def list_logs(self) -> dict:
        items = []
        for name, label in APP_LOGS:
            p = data_dir() / name
            st = p.stat() if p.exists() else None
            items.append({
                "name": name,
                "label": label,
                "exists": p.exists(),
                "size": st.st_size if st else 0,
                "mtime": int(st.st_mtime) if st else 0,
            })
        return {"items": items, "dir": str(data_dir())}

    def read_log(self, name: str, tail: int = 300) -> dict:
        allowed = {n for n, _ in APP_LOGS}
        if name not in allowed:
            return {"ok": False, "error": "未知日志"}
        p = data_dir() / name
        if not p.exists():
            return {"ok": True, "content": "", "empty": True, "lines": 0}
        text = p.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        content = "\n".join(lines[-max(1, int(tail)):])
        return {"ok": True, "content": content, "empty": not content.strip(), "lines": len(lines)}

    def open_logs_folder(self) -> dict:
        subprocess.run(["open", str(data_dir())], check=False)
        return {"ok": True}

    def open_kb(self) -> dict:
        subprocess.run(["open", str(kb_root(load_config()))], check=False)
        _track("click", "open_kb", scope="dashboard")
        return {"ok": True}

    def trigger_capsule(self) -> dict:
        """非阻塞 spawn 胶囊（用当前剪贴板内容）。"""
        from bootkit import child_cmd

        try:
            subprocess.Popen(
                child_cmd("capsule"),
                cwd=str(data_dir()),
                env=os.environ.copy(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            _track("click", "trigger_capsule", scope="dashboard")
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}

    def open_design_report(self) -> dict:
        p = resource_dir() / "docs" / "ui-design-report.html"
        if not p.exists():
            return {"ok": False, "error": "报告未生成"}
        subprocess.run(["open", str(p)], check=False)
        _track("click", "open_design_report", scope="dashboard")
        return {"ok": True}

    def open_path(self, p: str) -> dict:
        if not p:
            return {"ok": False}
        subprocess.run(["open", p], check=False)
        return {"ok": True}

    def open_default_target(self) -> dict:
        cfg = load_config()
        rel = get_default_target()
        if not rel:
            return {"ok": False}
        full = str(kb_root(cfg) / rel)
        subprocess.run(["open", full], check=False)
        return {"ok": True, "path": full}

    def pick_default_target(self) -> dict:
        """Finder 选一个 .md 设为默认归档文档。

        关键：如果用户选的文件不在当前 kb_root 下，自动把 kb_root 切到该文件的父目录，
        在 kb_root 内 → 存相对路径；在 kb_root 外 → 存绝对路径。两不误。
        """
        cfg = load_config()
        cur_kb = kb_root(cfg).resolve()

        script = f'''
        try
          set theFile to choose file with prompt "选择默认归档文档" of type {{"public.text", "net.daringfireball.markdown", "md"}} default location POSIX file "{cur_kb}" without invisibles
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
            return {"ok": False, "error": f"文件不存在：{abs_p}"}

        # 优先存相对（kb 内）；不在 kb 下 → 存绝对路径
        try:
            stored = abs_p.relative_to(cur_kb).as_posix()
        except ValueError:
            stored = str(abs_p)

        set_default_target(stored)
        return {
            "ok": True,
            "default_target": stored,
            "default_target_path": str(abs_p),
            "default_target_display": display_target(stored),
        }

    def switch_default_target(self, target: str) -> dict:
        """点击常用文档时直接切换默认（无需再开 Finder）。"""
        s = (target or "").strip()
        if not s:
            return {"ok": False, "error": "空 target"}
        try:
            cfg = load_config()
            abs_p = resolve_target_path(s, cfg)
            if not abs_p.exists():
                return {"ok": False, "error": f"文件不存在：{abs_p}"}
            set_default_target(s)
            return {
                "ok": True,
                "default_target": s,
                "default_target_path": str(abs_p),
                "default_target_display": display_target(s),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}

    def create_default_target(self) -> dict:
        """新建一个 .md（仍走 kb_root 模板）并设为默认归档文档。"""
        cfg = load_config()
        rel = choose_new_md_file(kb_root(cfg))
        if not rel:
            return {"ok": False, "cancelled": True}
        set_default_target(rel)
        return {
            "ok": True,
            "default_target": rel,
            "default_target_path": str(resolve_target_path(rel, cfg)),
            "default_target_display": display_target(rel),
        }

    # —— 反馈 / 问题报告 ——
    def feedback_status(self) -> dict:
        """返回反馈通道当前状态（前端用来决定按钮文案）。"""
        try:
            from feedback_collector import get_feedback_webhook, _resolve_user_handle
            webhook = get_feedback_webhook()
            name, machine = _resolve_user_handle()
            state = load_state()
            fb = state.get("feedback", {}) or {}
            return {
                "webhook_configured": bool(webhook),
                "channel": "feishu" if webhook else "",
                "user_handle": name,
                "machine": machine,
                "auto_error_enabled": bool(fb.get("auto_error_enabled", True)),
                "first_run_notified": bool(fb.get("first_run_notified", False)),
                "custom_webhook": fb.get("custom_webhook", ""),
            }
        except Exception as e:
            return {"webhook_configured": False, "error": str(e)[:200]}

    def feedback_preview(self, description: str = "") -> dict:
        """返回 payload 预览（用户看到「会发什么」）+ 卡片格式 JSON。"""
        try:
            from feedback_collector import build_payload, to_feishu_card
            payload = build_payload(kind="user_report", description=description)
            return {"ok": True, "payload": payload, "card": to_feishu_card(payload)}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def feedback_send(self, description: str) -> dict:
        """主动发送一份反馈。"""
        text = (description or "").strip()
        if not text:
            return {"ok": False, "error": "请先填写反馈内容"}
        try:
            from feedback_collector import build_payload, send_feedback
            payload = build_payload(kind="user_report", description=text)
            r = send_feedback(payload)
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}
        # 本地备份
        try:
            from datetime import datetime
            line = f"{datetime.now().isoformat(timespec='seconds')}\n{text}\n---\n"
            (data_dir() / "feedback.log").open("a", encoding="utf-8").write(line)
        except Exception:
            pass
        _track("click", "feedback_send", scope="dashboard",
               props={"ok": bool(r.get("ok")), "fallback": r.get("fallback", "")})
        return r

    def feedback_save_settings(self, opts: dict) -> dict:
        """保存反馈相关设置：user_handle / custom_webhook / auto_error_enabled / first_run_notified。"""
        opts = opts or {}
        state = load_state()
        fb = dict(state.get("feedback", {}) or {})
        for k in ("user_handle", "custom_webhook"):
            if k in opts:
                fb[k] = (opts.get(k) or "").strip()
        if "auto_error_enabled" in opts:
            fb["auto_error_enabled"] = bool(opts["auto_error_enabled"])
        if "first_run_notified" in opts:
            fb["first_run_notified"] = bool(opts["first_run_notified"])
        state["feedback"] = fb
        save_state(state)
        _track("click", "feedback_save_settings", scope="dashboard")
        return {"ok": True, "feedback": fb}

    def archive_text(self, text: str, target: str | None = None, mode: str = "auto") -> dict:
        """从后台手动归档某段文字（用于历史 Tab 的「再次归档」）。"""
        from settings_util import get_default_target

        if not text or not text.strip():
            return {"ok": False, "error": "空内容"}
        target = target or get_default_target()
        if not target:
            return {"ok": False, "error": "未设置默认文档"}

        from bootkit import child_cmd

        extra = ["--mode", "raw"] if mode == "raw" else []
        cmd = child_cmd(
            "archiver", "daily", "--target", target, "--from-stdin", "--no-notify", *extra,
        )
        try:
            r = subprocess.run(
                cmd, input=text, capture_output=True, text=True, timeout=180, cwd=str(data_dir()),
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "超时"}
        if r.returncode != 0:
            return {"ok": False, "error": (r.stderr or r.stdout)[:200]}
        try:
            bump_archived(1)
        except Exception:
            pass
        _track("click", "archive_from_history", scope="dashboard",
               props={"target": Path(target).name, "len": len(text)})
        return {"ok": True, "target": target}


def run_dashboard() -> int:
    if not DASHBOARD_DIR.joinpath("index.html").exists():
        raise FileNotFoundError(f"缺少 dashboard/index.html: {DASHBOARD_DIR}")
    # 启动时确保三层档案存在；出错只警告
    try:
        ensure_profile()
    except Exception as _e:
        print(f"[warn] ensure_profile failed: {_e}", flush=True)
    api = DashboardApi()
    index = DASHBOARD_DIR / "index.html"
    window = webview.create_window(
        "Skillless · 后台",
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
    parser = argparse.ArgumentParser(description="Skillless 后台 App")
    parser.parse_args(argv)
    print("正在打开后台窗口…（关闭窗口前终端会停在这里）", flush=True)
    return run_dashboard()


if __name__ == "__main__":
    raise SystemExit(main())
