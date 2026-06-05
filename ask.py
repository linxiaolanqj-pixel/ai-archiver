#!/usr/bin/env python3
"""随便问：把默认文档喂给 LLM，回答用户输入的问题。

MVP：
- 弹一个浮窗，上半截显示当前默认 md 的最近 6000 字
- 下半截输入框 + 回答区
- 不做长对话历史
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import traceback
import urllib.request
from pathlib import Path

import webview
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
ASK_UI = SCRIPT_DIR / "ask"

from settings_util import get_default_target, kb_root, load_config  # noqa: E402

CONTEXT_LIMIT = 6000


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


def _read_md(target: str | None) -> tuple[str, str]:
    if not target:
        return "", "未设置默认文档"
    cfg = load_config()
    p = kb_root(cfg) / target
    if not p.exists():
        return "", f"文件不存在：{p}"
    text = p.read_text(encoding="utf-8")
    if len(text) > CONTEXT_LIMIT:
        text = "（…仅取最近 6000 字…）\n\n" + text[-CONTEXT_LIMIT:]
    return text, str(p)


def _call_deepseek(system: str, user: str, *, timeout: int = 90) -> str:
    cfg = load_config()
    models = cfg.get("models", {}) or {}
    model_cfg = models.get(cfg.get("provider", "deepseek"), models.get("deepseek", {})) or {}
    key = os.environ.get(model_cfg.get("api_key_env", "DEEPSEEK_API_KEY"), "")
    if not key.startswith("sk-"):
        return "（未配置 DeepSeek API Key，去后台 → API Key 设置）"
    url = model_cfg.get("base_url") or "https://api.deepseek.com/v1/chat/completions"
    model = model_cfg.get("model") or "deepseek-chat"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.4,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"（请求失败：{type(e).__name__} {str(e)[:120]}）"


class AskApi:
    def __init__(self, target: str | None) -> None:
        self.target = target
        self.context, self.target_path = _read_md(target)

    def get_meta(self) -> dict:
        return {
            "target": self.target or "",
            "target_path": self.target_path,
            "has_context": bool(self.context),
            "context_len": len(self.context),
        }

    def ask(self, question: str) -> dict:
        q = (question or "").strip()
        if not q:
            return {"ok": False, "error": "请输入问题"}
        if not self.context:
            return {"ok": True, "answer": "（当前文档为空或不存在，先在里面归档点东西吧）"}
        sys_prompt = (
            "你是一个忠实于资料的助手。仅根据下面提供的资料回答问题；"
            "如果资料没有相关信息，明确说「资料中未提及」。回答简洁，结构化（用 Markdown）。"
        )
        user_prompt = f"=== 资料（来自 {self.target}）===\n{self.context}\n\n=== 问题 ===\n{q}"
        answer = _call_deepseek(sys_prompt, user_prompt)
        return {"ok": True, "answer": answer}

    def close(self) -> dict:
        for w in webview.windows:
            w.destroy()
        return {"ok": True}


def show_ask(target: str | None) -> int:
    api = AskApi(target=target)
    if not ASK_UI.joinpath("index.html").exists():
        raise FileNotFoundError(f"缺少 {ASK_UI / 'index.html'}")
    window = webview.create_window(
        "随便问",
        url=(ASK_UI / "index.html").resolve().as_uri(),
        js_api=api,
        width=620,
        height=520,
        resizable=True,
        text_select=True,
    )

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
    parser = argparse.ArgumentParser(description="随便问：基于默认 md 的单轮 Q&A")
    parser.add_argument("--target", help="指定要问的 md 相对路径，缺省 default_target")
    args = parser.parse_args(argv)
    _load_env()
    target = args.target or get_default_target()
    return show_ask(target)


if __name__ == "__main__":
    raise SystemExit(main())
