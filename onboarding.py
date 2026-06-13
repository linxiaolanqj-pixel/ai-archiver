#!/usr/bin/env python3
"""新客引导：HTML 左右对比 → 取名建库 → Finder 选 md → 演示 → Agent 对比"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from picker_util import choose_md_file, choose_new_md_file
from settings_util import (
    DEEPSEEK_API_KEYS_URL,
    create_knowledge_base,
    get_api_key,
    kb_root,
    load_config,
    mark_onboarding_done,
    save_api_key,
    set_kb_root,
)
from ui_util import (
    one_line_summary,
    open_html,
    open_in_textedit,
    show_long_text_preview,
    truncate_for_dialog,
)

from app_paths import data_dir as DATA_DIR, resource_dir

SCRIPT_DIR = resource_dir()
ARCHIVER_PY = SCRIPT_DIR / "archiver.py"
ENV_PATH = DATA_DIR() / ".env"
PY = str(SCRIPT_DIR / ".venv/bin/python") if (SCRIPT_DIR / ".venv/bin/python").exists() else sys.executable

DEMO_SAMPLE_TEXT = (
    "【群聊摘录】今天和供给方@张三对齐：顺手买 v2 计划下周三灰度 30%，"
    "KPI 加购转化率从 3% 提到 5%。@李四 周五前补齐埋点。"
    "王总主张上新人券，李总担心薅羊毛，分歧留待下周复盘。会后已同步产品群。"
)


def _load_env_file() -> None:
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _escape_dialog(s: str) -> str:
    return (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "")
        .replace("\n", "\\n")
    )


def _display_dialog(
    message: str,
    *,
    title: str,
    buttons: tuple[str, ...] = ("取消", "确定"),
    default_button: str | None = None,
    default_answer: str | None = None,
) -> str | None:
    btn_apple = ", ".join(f'"{_escape_dialog(b)}"' for b in buttons)
    default_btn = default_button or buttons[-1]
    body = f'display dialog "{_escape_dialog(message)}" with title "{_escape_dialog(title)}"'
    if default_answer is not None:
        body += f' default answer "{_escape_dialog(default_answer)}"'
    body += f' buttons {{{btn_apple}}} default button "{_escape_dialog(default_btn)}"'
    try:
        r = subprocess.run(["osascript", "-e", body], capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            return None
        return (r.stdout or "").strip()
    except Exception:
        return None


def _choose_list(items: list[str], *, title: str, prompt: str, ok: str = "下一步", cancel: str = "取消") -> str | None:
    if not items:
        return None
    apple = ", ".join(f'"{_escape_dialog(x)}"' for x in items)
    script = (
        f'set L to {{{apple}}}\n'
        f'set c to choose from list L with prompt "{_escape_dialog(prompt)}" '
        f'with title "{_escape_dialog(title)}" OK button name "{_escape_dialog(ok)}" '
        f'cancel button name "{_escape_dialog(cancel)}"\n'
        f'if c is false then return ""\n'
        f'return item 1 of c'
    )
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=120)
    except Exception:
        return None
    raw = (r.stdout or "").strip()
    return raw or None


def _action_for_target(cfg: dict, target: str) -> str:
    bn = Path(target).name
    for key, conf in cfg.get("actions", {}).items():
        t = conf.get("target", "")
        if t == target or t == bn or Path(t).name == bn:
            return key
    return "daily"


def show_workflow_comparison() -> bool:
    """浏览器左右对比（老 7 步 vs 新 2 步），小弹窗只负责点继续。"""
    open_html("compare.html")
    out = _display_dialog(
        "已在浏览器打开「左右对比」页面。\n\n左边老流程，右边新流程（带动画）。\n\n看完后点继续。",
        title="🦞 先看一眼差别",
        buttons=("下次再说", "看完了，继续 →"),
        default_button="看完了，继续 →",
    )
    return out is not None and "继续" in out


def ask_knowledge_base_name() -> str | None:
    out = _display_dialog(
        "给你的知识库起个名字：\n\n会自动创建文件夹，不用自己建。\n例如：顺手买、个人笔记",
        title="📁 知识库名称",
        default_answer="我的知识库",
        buttons=("取消", "创建"),
        default_button="创建",
    )
    if not out:
        return None
    name = out
    if name.startswith("text returned:"):
        name = name.split(":", 1)[1].strip()
    name = re.sub(r"[^\w\u4e00-\u9fff\- ]", "", name).strip()
    return name or None


def setup_default_md_in_finder(root: Path) -> str | None:
    """Finder 一个窗口：可进子文件夹、可点选 .md、可新建。"""
    _display_dialog(
        "下一步会打开 Finder。\n\n在窗口里直接点选一个 .md 即可\n（文件夹和文档都能浏览，不用分两步）。",
        title="📄 默认归档文档",
        buttons=("取消", "知道了"),
        default_button="知道了",
    )
    picked = _choose_list(
        ["📄 在 Finder 里选择已有 .md", "✨ 新建一个 .md"],
        title="选文档方式",
        prompt="演示和日常归档都会写入这个文件",
        ok="打开",
        cancel="取消",
    )
    if not picked:
        return None
    if picked.startswith("✨"):
        return choose_new_md_file(root, prompt="新建默认文档", default_name="默认归档.md")
    return choose_md_file(root, prompt="选择默认归档的 Markdown 文档")


def api_key_dialog() -> str | None:
    msg = f"""粘贴 DeepSeek API Key（sk- 开头）

没有？浏览器打开：
{DEEPSEEK_API_KEYS_URL}

可先跳过（跳过则演示用原文模式）"""
    out = _display_dialog(
        msg,
        title="🔑 API Key",
        buttons=("跳过", "保存"),
        default_button="保存",
        default_answer=get_api_key() or "",
    )
    if not out:
        return None
    key = out
    if key.startswith("text returned:"):
        key = key.split(":", 1)[1].strip()
    if not key or key.endswith("…"):
        return get_api_key() or None
    return key


def demo_intro_dialog() -> bool:
    out = _display_dialog(
        f"接下来用 {len(DEMO_SAMPLE_TEXT)} 字模拟群聊，走一遍真实归档。\n\n原文会在 TextEdit 里打开（不挤小弹窗）。",
        title="🎬 现场演示",
        buttons=("跳过", "开始"),
        default_button="开始",
    )
    return out is not None and "开始" in out


def demo_show_sample_and_confirm() -> bool:
    subprocess.run(["pbcopy"], input=DEMO_SAMPLE_TEXT.encode("utf-8"), check=False)
    snippet = truncate_for_dialog(DEMO_SAMPLE_TEXT)
    summary = one_line_summary(DEMO_SAMPLE_TEXT)
    show_long_text_preview(
        DEMO_SAMPLE_TEXT,
        filename="demo_sample_original.md",
        dialog_title="演示原文",
    )
    out = _display_dialog(
        f"体验原文已在 TextEdit 打开（完整内容）。\n\n一句话：{summary}\n\n弹窗摘要（≤300字）：\n{snippet}",
        title="📋 确认开始写入演示",
        buttons=("取消", "写入演示"),
        default_button="写入演示",
    )
    return out is not None and "写入" in out


def run_live_demo_archive(root: Path, default_md: str) -> tuple[bool, str, bool]:
    _load_env_file()
    cfg = load_config()
    action = _action_for_target(cfg, default_md)
    use_ai = bool(get_api_key().startswith("sk-"))

    cmd = [PY, str(ARCHIVER_PY), action, "--target", default_md, "--from-stdin", "--no-notify"]
    if not use_ai:
        cmd.extend(["--mode", "raw"])

    try:
        r = subprocess.run(
            cmd, input=DEMO_SAMPLE_TEXT, capture_output=True, text=True, timeout=120, cwd=str(DATA_DIR()),
        )
    except subprocess.TimeoutExpired:
        return False, "演示超时", use_ai

    if r.returncode != 0:
        return False, (r.stderr or r.stdout or "错误")[:200], use_ai

    summary = ""
    for line in (r.stdout or "").splitlines():
        if line.startswith("[archiver]"):
            summary = line.replace("[archiver]", "").strip()
            break
    return True, summary or "演示写入成功", use_ai


def demo_result_dialog(root: Path, default_md: str, ok: bool, msg: str, used_ai: bool) -> None:
    target = root / default_md
    if ok:
        _display_dialog(
            f"演示成功 · {msg}\n\n完整结果请在打开的文档中查看。",
            title="✅ 演示完成",
            buttons=("好", "打开文档"),
            default_button="打开文档",
        )
        subprocess.run(["open", str(target)], check=False)
    else:
        _display_dialog(f"演示未完成：\n{msg}", title="提示", buttons=("继续",), default_button="继续")


def show_agent_comparison() -> None:
    open_html("agent_compare.html")
    _display_dialog(
        "已在浏览器打开 Agent 前后对比（左右两栏）。\n\n看完点继续完成设置。",
        title="🧠 Agent 对比",
        buttons=("继续",),
        default_button="继续",
    )


def finish_dialog(kb: str, default_md: str, *, demo_ran: bool) -> None:
    stem = Path(default_md).stem
    _display_dialog(
        f"全部完成 🦞\n\n知识库：{kb}\n默认文档：{stem}\n\n"
        f"{'已跑通演示。' if demo_ran else ''}\n现在起可复制文字触发归档。",
        title="🎊 完成",
        buttons=("太好啦",),
        default_button="太好啦",
    )


def run_onboarding(force: bool = False) -> bool:
    """在独立子进程打开 pywebview 引导（避免菜单栏线程/NSApp 冲突）。"""
    from settings_util import onboarding_done

    if onboarding_done() and not force:
        return False

    from app_paths import is_frozen, resource_dir, data_dir
    from bootkit import child_cmd

    if not is_frozen():
        win_script = SCRIPT_DIR / "onboarding_window.py"
        if not win_script.exists():
            _display_dialog(
                f"缺少 {win_script}\n\n请确认 onboarding_window.py 存在。",
                title="新客引导",
                buttons=("好",),
                default_button="好",
            )
            return False

    extra = ["--force"] if force else []
    cmd = child_cmd("onboarding", *extra)
    print("[onboarding] 正在打开引导窗口…", flush=True)
    try:
        r = subprocess.run(cmd, cwd=str(data_dir()), timeout=7200)
    except FileNotFoundError:
        return _run_onboarding_legacy()
    except subprocess.TimeoutExpired:
        return False
    if r.returncode == 2 and not force:
        return False
    if r.returncode != 0 and not (resource_dir() / "onboarding" / "index.html").exists():
        _display_dialog(
            "引导界面文件缺失，请确认 onboarding/ 目录完整。",
            title="新客引导",
            buttons=("好",),
            default_button="好",
        )
    return r.returncode == 0


def _run_onboarding_legacy() -> bool:
    """无 pywebview 时的备用流程（Safari + 系统弹窗）。"""
    if not show_workflow_comparison():
        return False

    name = ask_knowledge_base_name()
    if not name:
        return False

    root = create_knowledge_base(name)
    set_kb_root(str(root))

    default_md = setup_default_md_in_finder(root)
    if not default_md:
        return False

    key = api_key_dialog()
    if key and key.startswith("sk-"):
        save_api_key(key)
    _load_env_file()

    demo_ran = False

    if demo_intro_dialog() and demo_show_sample_and_confirm():
        ok, msg, used_ai = run_live_demo_archive(root, default_md)
        demo_result_dialog(root, default_md, ok, msg, used_ai)
        demo_ran = ok

    show_agent_comparison()

    mark_onboarding_done(default_target=default_md)
    finish_dialog(str(root), default_md, demo_ran=demo_ran)
    return True


if __name__ == "__main__":
    raise SystemExit(0 if run_onboarding(force=True) else 1)
