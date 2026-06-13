#!/usr/bin/env python3
"""极简对比浮层：左侧原文 / 右侧 AI 结构化结果 → 一键写入默认文档。

设计：
- 浮层打开后立即显示原文，右侧 loading；前端立刻发起 `request_refined(mode)` 异步生成
- 用户选择写入模式 / 重新生成 / 直接确认
- 确认时：如果右侧已经有 refined 文本就直接以 raw 模式写入这段；否则按 mode 走原 prompt
- ❌ / Esc 取消

CLI：
  quick_archive.py                         默认 polish 模式
  quick_archive.py --target xx.md          指定写入目标
  quick_archive.py --mode raw|polish|...   初始模式
  quick_archive.py --raw                   原文模式（不调 LLM）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import traceback
import urllib.request
from pathlib import Path

import webview

from app_paths import data_dir, resource_dir

SCRIPT_DIR = resource_dir()
QUICK_UI = resource_dir() / "quick"
PY = str(resource_dir() / ".venv/bin/python") if (resource_dir() / ".venv/bin/python").exists() else sys.executable
ARCHIVER_PY = resource_dir() / "archiver.py"
PROMPTS_DIR = resource_dir() / "prompts"

from history import bump_archived, record_text  # noqa: E402
from settings_util import (  # noqa: E402
    get_default_target,
    kb_root,
    load_config,
    record_target_usage,
    resolve_target_path,
)


MODE_LABELS = {
    "polish": "润色",
    "structure": "结构化整理",
    "i18n": "翻译",
    "raw": "原文",
}


def md_to_plain(md: str) -> str:
    """把 Markdown 转成肉眼可读的纯文本（用于复制到其他 App 时不带 `**` `##` `-`）。"""
    if not md:
        return ""
    s = md
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)             # 图片
    s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1（\2）", s)  # 链接
    s = re.sub(r"`([^`]+)`", r"\1", s)                      # 行内代码
    s = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", s)             # 加粗
    s = re.sub(r"__([^_\n]+)__", r"\1", s)                  # 另一种加粗
    s = re.sub(r"(?m)^\s*#{1,6}\s*", "", s)                # 标题
    s = re.sub(r"(?m)^\s*>\s*", "", s)                      # 引用
    s = re.sub(r"(?m)^(\s*)[-*]\s+", r"\1• ", s)           # bullet -> •
    s = re.sub(r"(?m)^\s*\|.*\|\s*$", "", s)               # 表格行
    s = re.sub(r"(?m)^\s*-{3,}\s*$", "", s)                # 分隔线
    s = re.sub(r"\n{3,}", "\n\n", s)                        # 压缩多空行
    return s.strip()


def _load_env() -> None:
    env = data_dir() / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _read_clip() -> str:
    """v0.4.15：从剪贴板读纯文本，**绝不调 pbpaste**。

    pbpaste 在剪贴板带图片时会触发 macOS 图→文转换，每次都卡几秒；
    胶囊冷启动里只调一次也照样会拖体感。这里直接用 NSPasteboard 的
    `stringForType_` —— 是图片就返回 ""，零等待。

    AppKit 在打包后必然存在；万一开发态环境异常 import 失败，再走
    pbpaste 兜底（保留兼容性，不让胶囊裸退）。
    """
    try:
        from AppKit import NSPasteboard, NSPasteboardTypeString
        pb = NSPasteboard.generalPasteboard()
        s = pb.stringForType_(NSPasteboardTypeString)
        return s if s else ""
    except Exception:
        try:
            r = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=5)
            return r.stdout
        except Exception:
            return ""


def _notify(title: str, body: str) -> None:
    try:
        body = body.replace('"', "'")
        title = title.replace('"', "'")
        subprocess.run(
            ["osascript", "-e", f'display notification "{body}" with title "{title}"'],
            check=False, capture_output=True, timeout=5,
        )
    except Exception:
        pass


def _resolve_target(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    return get_default_target()


def _read_prompt(mode: str) -> str:
    p = PROMPTS_DIR / f"translate_{mode}.md"
    if p.exists():
        return p.read_text(encoding="utf-8")
    return ""


def _deepseek_model_cfg() -> tuple[str, str, str]:
    """返回 (api_key, url, model)。"""
    cfg = load_config()
    models = cfg.get("models", {}) or {}
    model_cfg = models.get(cfg.get("provider", "deepseek"), models.get("deepseek", {})) or {}
    key = os.environ.get(model_cfg.get("api_key_env", "DEEPSEEK_API_KEY"), "")
    url = model_cfg.get("base_url") or "https://api.deepseek.com/v1/chat/completions"
    model = model_cfg.get("model") or "deepseek-chat"
    return key, url, model


def _call_deepseek_stream(
    system: str,
    user: str,
    *,
    timeout: int = 45,
    max_tokens: int = 800,
    first_chunk_timeout: int = 15,
    idle_chunk_timeout: int = 25,
):
    """SSE 流式生成器：yield ('chunk', text) 或 ('error', msg)。

    v0.4.8 重写：之前用 `urlopen` + `fp.raw._sock` hack 设 timeout，但这路径在
    PyInstaller 打包后 / 某些 Python 版本上拿不到底层 socket，settimeout **静默
    失败**，结果胶囊「一直 thinking 无 error」。

    现在改用 `http.client.HTTPSConnection`，`conn.sock` 是显式 attribute，
    100% 可控：
    - 建连超时由 HTTPSConnection(timeout=...) 控制
    - 建连后 conn.sock.settimeout(first_chunk_timeout) 控制首 chunk 等待
    - 收到首 chunk 后改成 idle_chunk_timeout（给生成阶段宽松一点）
    """
    import http.client
    import socket as _socket
    import urllib.parse as _urlparse

    key, url, model = _deepseek_model_cfg()
    if not key.startswith("sk-"):
        yield ("error", "NO_API_KEY")
        return

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.4,
        "stream": True,
        "max_tokens": max_tokens,
        # v0.4.14：要求 DeepSeek 在最后一帧返回 usage（含 prompt_cache_hit_tokens
        # / prompt_cache_miss_tokens），用于监控 prefix cache 命中率。
        "stream_options": {"include_usage": True},
    }).encode("utf-8")

    parsed = _urlparse.urlparse(url)
    host = parsed.netloc
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query

    if parsed.scheme == "http":
        conn = http.client.HTTPConnection(host, timeout=timeout)
    else:
        conn = http.client.HTTPSConnection(host, timeout=timeout)

    try:
        conn.connect()
        conn.sock.settimeout(first_chunk_timeout)
        conn.request(
            "POST", path, body=payload,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
        )
        r = conn.getresponse()
        if r.status != 200:
            err_body = r.read(500).decode("utf-8", errors="replace")
            yield ("error", f"HTTP {r.status}: {err_body[:120]}")
            return

        got_first = False
        while True:
            try:
                raw = r.readline()
            except (TimeoutError, _socket.timeout):
                phase = "首 chunk" if not got_first else "后续 chunk"
                limit = first_chunk_timeout if not got_first else idle_chunk_timeout
                yield ("error", f"流式超时（{phase}等待 >{limit}s）：DeepSeek 假活")
                return
            if not raw:
                break
            if not got_first:
                got_first = True
                conn.sock.settimeout(idle_chunk_timeout)
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data_str = line[len("data:"):].strip()
            if not data_str or data_str == "[DONE]":
                continue
            try:
                obj = json.loads(data_str)
                # v0.4.14：DeepSeek 在 stream_options.include_usage=true 时，最后一帧
                # 的 choices=[]，但带 usage 字段（prompt_cache_hit_tokens / *_miss_tokens）
                usage = obj.get("usage")
                if isinstance(usage, dict):
                    yield ("usage", usage)
                delta = (obj.get("choices") or [{}])[0].get("delta", {}).get("content", "")
                if delta:
                    yield ("chunk", delta)
            except Exception:
                continue
    except Exception as e:
        yield ("error", f"请求失败：{type(e).__name__} {str(e)[:120]}")
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _call_deepseek(system: str, user: str, *, timeout: int = 90) -> tuple[bool, str]:
    cfg = load_config()
    models = cfg.get("models", {}) or {}
    model_cfg = models.get(cfg.get("provider", "deepseek"), models.get("deepseek", {})) or {}
    key = os.environ.get(model_cfg.get("api_key_env", "DEEPSEEK_API_KEY"), "")
    if not key.startswith("sk-"):
        return False, "NO_API_KEY"
    url = model_cfg.get("base_url") or "https://api.deepseek.com/v1/chat/completions"
    model = model_cfg.get("model") or "deepseek-chat"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.4,
        "max_tokens": 800,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        return True, content
    except Exception as e:
        return False, f"请求失败：{type(e).__name__} {str(e)[:120]}"


def _refine(text: str, mode: str) -> tuple[bool, str]:
    """根据 mode 调 LLM 生成精炼文本。

    prompts/translate_{mode}.md 要求模型返回 JSON {ok, summary, section_title, body}，
    我们只取 body 给前端展示。失败时回退到把整段 raw content 当 body。
    """
    if mode == "raw":
        return True, text.strip()
    sys_prompt = _read_prompt(mode) or "请把用户的原文整理成清晰的 Markdown 笔记。"
    ok, content = _call_deepseek(sys_prompt, text)
    if not ok:
        return False, content
    body = _extract_body(content)
    return True, body or content.strip()


def _extract_body(content: str) -> str:
    """从模型输出里抽 body 字段；prompt 要求返回 JSON，做容错。"""
    s = content.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```$", "", s)
    try:
        obj = json.loads(s)
        return (obj.get("body") or "").strip()
    except Exception:
        return ""


class QuickApi:
    def __init__(self, text: str, target: str, mode: str, preset_refined: str = "") -> None:
        self.text = text
        self.target = target
        self.mode = mode if mode in MODE_LABELS else "polish"
        self.preset_refined = preset_refined  # 胶囊传过来已生成好的；非空时大窗直接渲染
        self.done = False

    def get_payload(self) -> dict:
        body = self.text.rstrip()
        return {
            "text": body,
            "len": len(body),
            "target_label": Path(self.target).name if self.target else "未设置默认文档",
            "target": self.target or "",
            "mode": self.mode,
            "mode_label": MODE_LABELS.get(self.mode, self.mode),
            "modes": [{"id": k, "label": v} for k, v in MODE_LABELS.items()],
            "preset_refined": self.preset_refined or "",
        }

    def request_refined(self, mode: str) -> dict:
        if mode not in MODE_LABELS:
            mode = "polish"
        self.mode = mode
        if mode == "raw":
            return {"ok": True, "body": self.text.strip(), "mode": mode}
        ok, body = _refine(self.text, mode)
        return {"ok": ok, "body": body, "mode": mode}

    def confirm(self, body: str | None = None, mode: str | None = None) -> dict:
        if not self.target:
            return {"ok": False, "error": "未设置默认文档"}
        cfg = load_config()
        write_text = (body or "").strip() or self.text.strip()
        write_mode = mode or self.mode

        action = _action_for_target(cfg, self.target) or next(iter(cfg.get("actions", {})), "daily")
        cmd = [PY, str(ARCHIVER_PY), action,
               "--target", self.target, "--from-stdin", "--no-notify", "--mode", "raw"]

        try:
            r = subprocess.run(
                cmd, input=write_text, capture_output=True, text=True, timeout=60, cwd=str(data_dir()),
                env=os.environ.copy(),
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
        msg = f"已写入 {Path(self.target).name}（{MODE_LABELS.get(write_mode, write_mode)}），位于文件末尾。"
        return {
            "ok": True,
            "target": self.target,
            "target_path": target_path,
            "message": msg,
        }

    def cancel(self) -> dict:
        self.done = False
        return {"ok": True}

    def close(self) -> dict:
        for w in webview.windows:
            w.destroy()
        return {"ok": True}


def _action_for_target(cfg: dict, target: str) -> str | None:
    bn = Path(target).name
    for key, conf in cfg.get("actions", {}).items():
        t = conf.get("target", "")
        if t == target or t == bn or Path(t).name == bn:
            return key
    return None


def show_quick(text: str, *, target: str | None, mode: str, preset_refined: str = "") -> int:
    api = QuickApi(text=text, target=target or "", mode=mode, preset_refined=preset_refined)
    if not QUICK_UI.joinpath("index.html").exists():
        raise FileNotFoundError(f"缺少 {QUICK_UI / 'index.html'}")

    window = webview.create_window(
        "Quick Archive",
        url=(QUICK_UI / "index.html").resolve().as_uri(),
        js_api=api,
        width=820,
        height=520,
        frameless=True,
        on_top=True,
        easy_drag=True,
        resizable=False,
        transparent=False,
        background_color="#ffffff",
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
    return 0 if api.done else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="左原文 / 右 AI 对比的归档浮层")
    parser.add_argument("--target", help="指定目标 md 相对路径，默认 default_target")
    parser.add_argument("--mode", default="polish",
                        choices=list(MODE_LABELS.keys()),
                        help="默认 polish；raw 表示不调 LLM，直接显示原文")
    parser.add_argument("--raw", action="store_true", help="等同 --mode raw")
    parser.add_argument(
        "--preset",
        help="预生成结果 json 文件路径（{text, refined, mode, target}），有则跳过剪贴板和 LLM",
    )
    args = parser.parse_args(argv)

    if args.raw:
        args.mode = "raw"

    _load_env()

    preset_refined = ""
    if args.preset:
        try:
            data = json.loads(Path(args.preset).read_text(encoding="utf-8"))
            text = data.get("text", "")
            preset_refined = data.get("refined", "") or ""
            args.mode = data.get("mode") or args.mode
            args.target = data.get("target") or args.target
            try:
                Path(args.preset).unlink(missing_ok=True)
            except Exception:
                pass
        except Exception as e:
            _notify("Skillless", f"读取 preset 失败：{type(e).__name__}")
            return 2
    else:
        text = _read_clip()
        if not text.strip():
            _notify("Skillless", "剪贴板为空，先 Cmd+C")
            return 2
        try:
            record_text(text, source="quick")
        except Exception:
            pass

    target = _resolve_target(args.target)
    if not target:
        _notify("Skillless", "尚未设置默认文档")
        return 2

    return show_quick(text, target=target, mode=args.mode, preset_refined=preset_refined)


if __name__ == "__main__":
    raise SystemExit(main())
