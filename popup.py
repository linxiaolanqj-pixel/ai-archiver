#!/usr/bin/env python3
"""快捷键 / Shortcuts 调用入口：读剪贴板 → 弹文件选择 → 直接归档。

设计目标：
  - 不依赖菜单栏 App 是否在跑
  - 弹窗只有一步：常用列表 + 「在 Finder 选 .md」+ 「新建 .md」
  - 默认走 config.yaml 里的模式（AI/raw），可用 --raw 强制原文
  - 配合 macOS Shortcuts 绑定全局快捷键：
      Shortcut → Run Shell Script → bash ~/tools/ai-archiver/run.sh popup
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

from picker_util import NEW_FILE_LABEL, choose_md_file, choose_new_md_file
from settings_util import (
    get_default_target,
    get_quick_pick_targets,
    kb_root,
    load_config,
    should_skip_text,
)

SCRIPT_DIR = Path(__file__).resolve().parent
ARCHIVER_PY = SCRIPT_DIR / "archiver.py"
PY = str(SCRIPT_DIR / ".venv/bin/python") if (SCRIPT_DIR / ".venv/bin/python").exists() else sys.executable

FINDER_LABEL = "📂 在 Finder 选其他 .md"


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


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _read_clip() -> str:
    try:
        r = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=5)
        return r.stdout
    except Exception:
        return ""


def _notify(title: str, body: str) -> None:
    try:
        subprocess.run(
            ["osascript", "-e", f'display notification "{_escape(body)}" with title "{_escape(title)}"'],
            check=False,
            capture_output=True,
            timeout=5,
        )
    except Exception:
        pass


def _choose_list(items: list[str], *, title: str, prompt: str) -> str | None:
    apple = ", ".join(f'"{_escape(x)}"' for x in items)
    script = (
        f'set L to {{{apple}}}\n'
        f'set c to choose from list L with prompt "{_escape(prompt)}" '
        f'with title "{_escape(title)}" OK button name "归档" cancel button name "取消"\n'
        f'if c is false then return ""\n'
        f'return item 1 of c'
    )
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=300)
    raw = (r.stdout or "").strip()
    return raw or None


def _action_for_target(cfg: dict, target: str) -> str:
    bn = Path(target).name
    for key, conf in cfg.get("actions", {}).items():
        t = conf.get("target", "")
        if t == target or t == bn or Path(t).name == bn:
            return key
    return "daily"


def _short_label(rel: str) -> str:
    p = Path(rel)
    if len(p.parts) == 1:
        return p.stem
    return f"{p.stem} · {p.parent}"


def _scan_existing_targets(root: Path) -> list[str]:
    out: list[str] = []
    for p in sorted(root.rglob("*.md")):
        if any(part in {".git", ".venv", "node_modules", ".obsidian"} for part in p.parts):
            continue
        if p.name.startswith("_"):
            continue
        rel = p.resolve().relative_to(root.resolve()).as_posix()
        out.append(rel)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="读剪贴板 → 选 md → 归档")
    parser.add_argument("--raw", action="store_true", help="强制原文追加（不调 LLM）")
    parser.add_argument("--target", help="跳过选择，直接归档到这个相对路径")
    parser.add_argument("--no-min-check", action="store_true", help="忽略最小字数限制")
    args = parser.parse_args(argv)

    _load_env()
    cfg = load_config()
    root = kb_root(cfg)
    root.mkdir(parents=True, exist_ok=True)

    text = _read_clip()
    if not text.strip():
        _notify("Skillless", "剪贴板为空，先 Cmd+C")
        return 2
    min_len = int((cfg.get("behavior", {}) or {}).get("auto_prompt_min_length", 1))
    if not args.no_min_check and should_skip_text(text, min_len, cfg):
        if len(text.strip()) < min_len:
            _notify("Skillless", f"内容 {len(text.strip())} 字，少于门槛 {min_len}")
        else:
            _notify("Skillless", "剪贴板内容被防误触跳过（代码/超长/黑名单）")
        return 2

    target = args.target
    if not target:
        existing = set(_scan_existing_targets(root))
        quick = [r for r in get_quick_pick_targets(8) if r in existing]
        default = get_default_target()
        labels: list[str] = []
        rel_map: dict[str, str] = {}
        if default and default in existing:
            lab = f"🌟 {_short_label(default)}"
            labels.append(lab)
            rel_map[lab] = default
        for rel in quick:
            if rel == default:
                continue
            lab = f"⭐ {_short_label(rel)}"
            labels.append(lab)
            rel_map[lab] = rel
        labels.append(FINDER_LABEL)
        labels.append(NEW_FILE_LABEL)

        preview = re.sub(r"\s+", " ", text.strip())[:60]
        picked = _choose_list(
            labels,
            title=f"📥 归档（{len(text.strip())} 字）",
            prompt=f"{preview}…",
        )
        if not picked:
            return 1
        if picked == FINDER_LABEL:
            target = choose_md_file(root, prompt="选 .md 写入")
        elif picked == NEW_FILE_LABEL:
            target = choose_new_md_file(root, prompt="新建 .md")
        else:
            target = rel_map.get(picked)
        if not target:
            return 1

    action = _action_for_target(cfg, target)
    cmd = [PY, str(ARCHIVER_PY), action, "--target", target, "--from-stdin"]
    if args.raw or not os.environ.get("DEEPSEEK_API_KEY", "").startswith("sk-"):
        cmd += ["--mode", "raw"]
    try:
        r = subprocess.run(cmd, input=text, capture_output=True, text=True, timeout=300, cwd=str(SCRIPT_DIR))
    except subprocess.TimeoutExpired:
        _notify("Skillless", "归档超时")
        return 1
    if r.returncode != 0:
        _notify("Skillless · 失败", (r.stderr or r.stdout or "未知错误")[:120])
        return 1
    msg = ""
    for line in (r.stdout or "").splitlines():
        if line.startswith("[archiver]"):
            msg = line.replace("[archiver]", "").strip()
            break
    _notify("Skillless ✅", msg or f"已写入 {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
