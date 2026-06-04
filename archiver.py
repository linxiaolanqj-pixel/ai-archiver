#!/usr/bin/env python3
"""AI Archiver — 选中文本 → 结构化 → 追加到本地 Markdown 知识库

用法：
    archiver.py <action> --text "原始文本"
    archiver.py <action> --from-stdin
    archiver.py <action> --from-clipboard
    archiver.py --list

可叠加：
    --dry-run        不写入文件，只把要写的东西打印出来
    --provider X     临时覆盖 config.yaml 里的 provider
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml  # 需要 pip install pyyaml


SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"


# ----------------------------- 通用工具 -----------------------------

def _expand(path_str: str) -> Path:
    return Path(os.path.expanduser(path_str)).resolve()


def _now_vars() -> dict[str, str]:
    now = _dt.datetime.now()
    iso_year, iso_week, _ = now.isocalendar()
    return {
        "date": now.strftime("%Y-%m-%d"),
        "datetime": now.strftime("%Y-%m-%d %H:%M"),
        "iso_week": f"{iso_year}W{iso_week:02d}",
    }


def _notify(title: str, body: str) -> None:
    """macOS 通知中心弹一条；失败静默。"""
    try:
        safe_title = title.replace('"', "'")
        safe_body = body.replace('"', "'")
        script = f'display notification "{safe_body}" with title "{safe_title}"'
        subprocess.run(["osascript", "-e", script], check=False, capture_output=True)
    except Exception:
        pass


def _load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        sys.exit(f"[archiver] 找不到配置文件: {CONFIG_PATH}")
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _read_text(args: argparse.Namespace) -> str:
    if args.text:
        return args.text
    if args.from_stdin:
        return sys.stdin.read()
    if args.from_clipboard:
        try:
            out = subprocess.run(["pbpaste"], check=True, capture_output=True, text=True)
            return out.stdout
        except Exception as e:
            sys.exit(f"[archiver] 读剪贴板失败: {e}")
    sys.exit("[archiver] 必须给输入：--text / --from-stdin / --from-clipboard")


# ----------------------------- LLM 调用 -----------------------------

def _http_json(url: str, headers: dict[str, str], body: dict[str, Any], timeout: int = 60) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", errors="replace")
        sys.exit(f"[archiver] LLM HTTP {e.code}: {msg[:500]}")
    except urllib.error.URLError as e:
        sys.exit(f"[archiver] 网络错误: {e}")


def _call_anthropic(cfg: dict[str, Any], system: str, user: str) -> str:
    api_key = os.environ.get(cfg["api_key_env"], "").strip()
    if not api_key:
        sys.exit(f"[archiver] 没有设置 {cfg['api_key_env']}（去 .env 里填）")
    body = {
        "model": cfg["model"],
        "max_tokens": 1500,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    resp = _http_json(cfg["base_url"], headers, body)
    parts = resp.get("content", [])
    return "".join(p.get("text", "") for p in parts if p.get("type") == "text")


def _call_openai_like(cfg: dict[str, Any], system: str, user: str) -> str:
    """OpenAI / DeepSeek / 其它兼容 OpenAI Chat Completions 的接口。"""
    api_key = os.environ.get(cfg["api_key_env"], "").strip()
    if not api_key:
        sys.exit(f"[archiver] 没有设置 {cfg['api_key_env']}（去 .env 里填）")
    body = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    resp = _http_json(cfg["base_url"], headers, body)
    return resp["choices"][0]["message"]["content"]


def _call_dryrun(action: str, user: str) -> str:
    """不调外部 API，返回一段假的结构化结果，便于联调 Shortcuts。"""
    preview = (user or "").strip().splitlines()[0][:60] if user else "(空)"
    return json.dumps({
        "summary": f"[dryrun] {action} 模拟归档：{preview}",
        "section_name": "供给",
        "markdown": (
            f"### [dryrun] {action} 测试条目\n"
            f"- **要点**: 这是一条 dryrun 模拟内容，没有真调 LLM\n"
            f"- **原文摘录**: > {preview}"
        ),
    }, ensure_ascii=False)


def _call_llm(provider: str, models_cfg: dict[str, Any], system: str, user: str, action: str) -> str:
    if provider == "dryrun":
        return _call_dryrun(action, user)
    if provider not in models_cfg:
        sys.exit(f"[archiver] 未知 provider: {provider}（config.yaml 里没配）")
    cfg = models_cfg[provider]
    if provider == "anthropic":
        return _call_anthropic(cfg, system, user)
    # openai / deepseek / 其它兼容
    return _call_openai_like(cfg, system, user)


# ----------------------------- JSON 容错解析 -----------------------------

def _extract_json(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    # 去掉常见的 ```json ... ``` 包裹
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    # 找第一个 { 到最后一个 }
    l, r = raw.find("{"), raw.rfind("}")
    if l == -1 or r == -1:
        sys.exit(f"[archiver] LLM 输出里找不到 JSON:\n{raw[:500]}")
    candidate = raw[l : r + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as e:
        sys.exit(f"[archiver] LLM 返回不是合法 JSON: {e}\n原文:\n{raw[:800]}")


# ----------------------------- 写入逻辑 -----------------------------

def _git_checkpoint(kb_root: Path, action: str) -> None:
    if not (kb_root / ".git").exists():
        return
    try:
        subprocess.run(
            ["git", "-C", str(kb_root), "add", "-A"], check=False, capture_output=True
        )
        # 只有有变更才 commit
        diff = subprocess.run(
            ["git", "-C", str(kb_root), "diff", "--cached", "--quiet"],
            capture_output=True,
        )
        if diff.returncode != 0:
            subprocess.run(
                [
                    "git", "-C", str(kb_root), "commit",
                    "-m", f"checkpoint before archiver:{action}",
                    "--quiet",
                ],
                check=False, capture_output=True,
            )
    except Exception:
        pass


def _resolve_section(section_template: str, llm_section: str | None) -> str:
    if section_template == "auto":
        name = (llm_section or "未分类").strip()
        return f"## {name}"
    return section_template.format(**_now_vars())


def _append_to_section(target: Path, section_heading: str, body: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_text(f"# {target.stem}\n\n", encoding="utf-8")

    content = target.read_text(encoding="utf-8")
    block = f"\n{body.rstrip()}\n"

    if section_heading in content:
        # 找到 section，把内容插到它的下一个同级或更高级 heading 之前
        lines = content.splitlines()
        idx = next(i for i, ln in enumerate(lines) if ln.strip() == section_heading)
        # 当前 heading 的层级
        cur_level = len(section_heading) - len(section_heading.lstrip("#"))
        insert_at = len(lines)
        for j in range(idx + 1, len(lines)):
            ln = lines[j]
            if ln.startswith("#"):
                lvl = len(ln) - len(ln.lstrip("#"))
                if lvl <= cur_level:
                    insert_at = j
                    break
        new_lines = lines[:insert_at] + block.splitlines() + [""] + lines[insert_at:]
        target.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")
    else:
        # section 不存在，追加到文件末尾
        suffix = "" if content.endswith("\n") else "\n"
        target.write_text(content + suffix + f"\n{section_heading}\n{block}", encoding="utf-8")


def _write_archive_log(kb_root: Path, action: str, summary: str, target_rel: str) -> None:
    log = kb_root / "_archive_log.md"
    if not log.exists():
        log.write_text("# 归档日志\n\n", encoding="utf-8")
    stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    line = f"- `{stamp}` **{action}** → `{target_rel}` — {summary}\n"
    with log.open("a", encoding="utf-8") as f:
        f.write(line)


# ----------------------------- 主流程 -----------------------------

def _build_raw_markdown(text: str) -> tuple[str, str]:
    """原文模式：返回 (summary, markdown_body)。不调 LLM，直接包装。"""
    ts = _dt.datetime.now().strftime("%H:%M")
    preview = re.sub(r"\s+", " ", text.strip())[:40]
    body_lines = [f"### {ts} · 原文记录"]
    for line in text.strip().splitlines():
        body_lines.append(line)
    body = "\n".join(body_lines)
    summary = f"原文已存：{preview}…"
    return summary, body


def run(
    action: str,
    raw_text: str,
    *,
    dry_run: bool,
    provider_override: str | None,
    mode: str = "ai",
) -> None:
    config = _load_config()
    kb_root = _expand(config["knowledge_base"]["root"])

    actions = config["actions"]
    if action not in actions:
        sys.exit(f"[archiver] 未知 action: {action}\n可用: {', '.join(actions)}")
    action_cfg = actions[action]

    if mode == "raw":
        # 原文模式：跳过 LLM
        summary, md_body = _build_raw_markdown(raw_text)
        # 原文模式下，section 模板里如果是 "auto"（让 LLM 判断）就退化成日期
        section_template = action_cfg["section"]
        if section_template == "auto":
            section_template = "## {date}"
        section_heading = section_template.format(**_now_vars())
        parsed = {"summary": summary}
    else:
        # AI 模式：走原来的 LLM 流程
        prompt_path = SCRIPT_DIR / action_cfg["prompt"]
        if not prompt_path.exists():
            sys.exit(f"[archiver] 找不到 prompt 文件: {prompt_path}")
        system_prompt = prompt_path.read_text(encoding="utf-8")

        provider = provider_override or os.environ.get("ARCHIVER_PROVIDER") or config.get("provider", "dryrun")
        raw_output = _call_llm(provider, config["models"], system_prompt, raw_text, action)
        parsed = _extract_json(raw_output)

        md_body = (parsed.get("markdown") or "").strip()
        if not md_body:
            msg = parsed.get("summary") or "LLM 没产出可追加的内容"
            print(f"[archiver] 跳过写入：{msg}")
            if config["behavior"].get("notify", True):
                _notify("AI Archiver · 跳过", msg)
            return

        section_heading = _resolve_section(action_cfg["section"], parsed.get("section_name"))

    target = kb_root / action_cfg["target"]

    if dry_run:
        print("=" * 60)
        print(f"[dry-run] action      : {action}  (mode={mode})")
        print(f"[dry-run] target file : {target}")
        print(f"[dry-run] section     : {section_heading}")
        print(f"[dry-run] summary     : {parsed.get('summary')}")
        print("[dry-run] markdown 预览 ↓")
        print(md_body)
        print("=" * 60)
        return

    if config["behavior"].get("auto_git_checkpoint", True):
        _git_checkpoint(kb_root, action)

    _append_to_section(target, section_heading, md_body)

    if config["behavior"].get("write_archive_log", True):
        _write_archive_log(kb_root, action, parsed.get("summary", ""), action_cfg["target"])

    summary = parsed.get("summary") or "已追加"
    print(f"[archiver] ✓ {summary}\n  → {target}\n  ↳ {section_heading}")
    if config["behavior"].get("notify", True):
        _notify(f"AI Archiver · {action_cfg.get('label', action)}", summary)


def list_actions() -> None:
    config = _load_config()
    print(f"知识库根目录: {config['knowledge_base']['root']}")
    print(f"当前 provider: {os.environ.get('ARCHIVER_PROVIDER') or config.get('provider')}")
    print("\n可用操作:")
    for key, a in config["actions"].items():
        print(f"  {key:14s}  {a['label']:20s}  → {a['target']}")


def main() -> None:
    p = argparse.ArgumentParser(description="AI Archiver")
    p.add_argument("action", nargs="?", help="操作名，例如 daily / shunshoumai / todo")
    p.add_argument("--text", help="直接传入原始文本")
    p.add_argument("--from-stdin", action="store_true", help="从 stdin 读取")
    p.add_argument("--from-clipboard", action="store_true", help="从 macOS 剪贴板读取")
    p.add_argument("--dry-run", action="store_true", help="不写文件，只打印")
    p.add_argument("--provider", help="临时覆盖 provider")
    p.add_argument("--mode", choices=["ai", "raw"], default="ai",
                   help="ai=调 LLM 结构化（默认），raw=原文模式不调 LLM 直接追加")
    p.add_argument("--list", action="store_true", help="列出所有操作")
    args = p.parse_args()

    if args.list or not args.action:
        list_actions()
        return

    raw_text = _read_text(args)
    if not raw_text.strip():
        sys.exit("[archiver] 输入文本为空")

    run(args.action, raw_text, dry_run=args.dry_run, provider_override=args.provider, mode=args.mode)


if __name__ == "__main__":
    main()
