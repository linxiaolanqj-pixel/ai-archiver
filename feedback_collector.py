"""远程反馈/错误上报。

核心场景：
- 给陌生人（小红书）/ 朋友分发 .app 后，需要能收到他们的报错日志、版本、系统信息
- 隐私优先：不传剪贴板原文、笔记内容、词典；只传日志摘要 + 系统信息 + 用户描述
- 用户主动反馈（A 路径） + 严重错误自动上报（B 路径，可关）
- 接收端：飞书机器人 webhook（国内直连、免费、富文本卡片）
- Webhook URL 不入 git；通过 build.sh 加密打包到 .app 里（复用 platform_crypto 机制）

使用方式（开发者）：
1. 飞书群里加机器人，拿到 webhook URL（形如 https://open.feishu.cn/open-apis/bot/v2/hook/xxxx）
2. 写到 secrets/feedback_webhook.txt（不要提交 git）
3. 运行 ./build.sh，build 时会把它加密为 feedback_webhook.enc 打包进 .app
4. 用户用你的 .app → 出错时自动上报到你飞书群

使用方式（用户端）：
- 菜单栏「反馈意见」 → 弹后台反馈页 → 写一句话 → 发送
- 严重错误（traceback / 401 / API 网络挂）会自动上报一条精简事件（首启动告知）

不打包 webhook URL 时：发送会 fallback 到「复制到剪贴板」
"""

from __future__ import annotations

import getpass
import json
import platform
import socket
import time
import traceback
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from app_paths import data_dir, resource_dir
from platform_crypto import _xor_bytes  # 复用 xor 引擎，但用不同的 key 派生
import base64
import hashlib


# ============================================================
# Webhook URL 加密：和 platform key 隔离的派生 key
# ============================================================

def _feedback_key() -> bytes:
    material = "Skillless·feedback·webhook·v1|com.skillless.app"
    return hashlib.sha256(material.encode("utf-8")).digest()


def encrypt_webhook(plain: str) -> str:
    plain = (plain or "").strip()
    if not plain:
        return ""
    return base64.urlsafe_b64encode(_xor_bytes(plain.encode("utf-8"), _feedback_key())).decode("ascii")


def decrypt_webhook(blob: str) -> str:
    blob = (blob or "").strip()
    if not blob:
        return ""
    try:
        ct = base64.urlsafe_b64decode(blob.encode("ascii"))
        return _xor_bytes(ct, _feedback_key()).decode("utf-8")
    except Exception:
        return ""


def get_feedback_webhook() -> str:
    """优先打包的 .enc，次之 user 自填的 webhook（后台设置里），都没有 → 空。"""
    # 1. 用户在设置里手动填的 webhook（覆盖打包的）
    try:
        from settings_util import load_state
        state = load_state()
        user_url = (state.get("feedback", {}) or {}).get("custom_webhook", "").strip()
        if user_url:
            return user_url
    except Exception:
        pass
    # 2. 打包时加密的 webhook
    enc_path = resource_dir() / "feedback_webhook.enc"
    if enc_path.exists():
        try:
            return decrypt_webhook(enc_path.read_text(encoding="utf-8").strip())
        except Exception:
            return ""
    # 3. 开发态用户写在 secrets/ 里的明文（仅本机调试用）
    dev_path = Path(__file__).resolve().parent / "secrets" / "feedback_webhook.txt"
    if dev_path.exists():
        try:
            return dev_path.read_text(encoding="utf-8").strip().splitlines()[0].strip()
        except Exception:
            return ""
    return ""


# ============================================================
# 用户身份（兜底层级）
# ============================================================

def _resolve_user_handle() -> tuple[str, str]:
    """返回 (展示名, 机器账户名)。展示名优先：USER.md > settings 里的 user_handle > macOS account。"""
    machine = ""
    try:
        machine = getpass.getuser()
    except Exception:
        machine = ""

    # USER.md 里第一行 markdown 标题或 "想被怎么称呼" / "名字" 字段
    try:
        from profile_util import load_profile
        prof = load_profile()
        user_md = prof.get("user", "") or ""
        # 找 "**想被怎么称呼**：xxx" 或 "**名字**：xxx" 或 "**Name:** xxx"
        import re
        for pat in [
            r"\*\*想被怎么称呼\*\*[:：]\s*([^\n]+)",
            r"\*\*名字\*\*[:：]\s*([^\n]+)",
            r"\*\*Name\*\*[:：]\s*([^\n]+)",
            r"^-\s*\*\*Name\*\*[:：]\s*([^\n]+)",
        ]:
            m = re.search(pat, user_md, re.MULTILINE)
            if m:
                name = m.group(1).strip().strip("`").strip()
                if name and name not in ("", "你", "Your name"):
                    return name, machine
    except Exception:
        pass

    # state 里设置的反馈昵称
    try:
        from settings_util import load_state
        h = (load_state().get("feedback", {}) or {}).get("user_handle", "").strip()
        if h:
            return h, machine
    except Exception:
        pass

    return machine or "anonymous", machine


# ============================================================
# 日志 / 系统信息收集
# ============================================================

_LOG_FILES = [
    ("clip_watcher", 30),
    ("capsule_errors", 10),
    ("capsule_spawn", 10),
    ("startup", 20),
]


def _tail(path: Path, n: int) -> list[str]:
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        return lines[-n:] if len(lines) > n else lines
    except Exception:
        return []


def collect_logs() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    base = data_dir()
    for name, n in _LOG_FILES:
        out[name] = _tail(base / f"{name}.log", n)
    return out


def collect_system_info() -> dict[str, Any]:
    try:
        osver = platform.mac_ver()[0] or platform.release()
    except Exception:
        osver = ""
    try:
        host = socket.gethostname()
    except Exception:
        host = ""
    return {
        "os": f"macOS {osver}".strip() or platform.platform(),
        "arch": platform.machine(),
        "python": platform.python_version(),
        "host": host,  # 主机名（不是用户名），用于区分多机
        "locale": "",
    }


def collect_app_info() -> dict[str, Any]:
    try:
        from version import VERSION, BUILD_DATE
    except Exception:
        VERSION, BUILD_DATE = "unknown", ""
    return {"version": VERSION, "build_date": BUILD_DATE}


def collect_telemetry_summary() -> dict[str, Any]:
    """从 state.json 读 counters，用户行为概览（不带原文）。"""
    try:
        from settings_util import load_state
        s = load_state()
        return {
            "total_archived": int(s.get("total_archived", 0) or 0),
            "total_capsule_opens": int(s.get("total_capsule_opens", 0) or 0),
            "onboarding_done": bool(s.get("onboarding_done", False)),
            "default_target": Path(s.get("default_target", "") or "").name,  # 仅文件名，不带路径
        }
    except Exception:
        return {}


# ============================================================
# Payload 构造
# ============================================================

def build_payload(
    *,
    kind: str = "user_report",
    description: str = "",
    error_brief: dict | None = None,
) -> dict[str, Any]:
    """组装 schema=skillless.feedback.v1 的反馈包。

    kind:
      - "user_report"：用户主动报问题（带描述）
      - "auto_error"：严重错误自动上报（带 error_brief）
    """
    name, machine = _resolve_user_handle()
    payload = {
        "schema": "skillless.feedback.v1",
        "kind": kind,
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "user": {"name": name, "machine": machine},
        "system": collect_system_info(),
        "app": collect_app_info(),
        "telemetry": collect_telemetry_summary(),
        "description": (description or "")[:600],
        "logs": collect_logs(),
    }
    if error_brief:
        payload["error"] = error_brief
    return payload


# ============================================================
# 飞书富文本卡片格式化
# ============================================================

def _truncate(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[:n] + "…"


def _format_logs_block(logs: dict[str, list[str]]) -> str:
    """日志摘要：取每类最近几行。"""
    parts: list[str] = []
    for name, lines in logs.items():
        if not lines:
            continue
        parts.append(f"**{name}.log** (最近 {len(lines)} 行):")
        # 飞书卡片代码块：用 ``` 包裹更整洁
        joined = "\n".join(lines[-5:])  # 卡片里只给最近 5 行，避免太长
        parts.append(f"```\n{_truncate(joined, 800)}\n```")
    return "\n\n".join(parts) if parts else "_(无日志)_"


def to_feishu_card(payload: dict[str, Any]) -> dict[str, Any]:
    """飞书消息机器人富文本卡片：好读、能折叠。"""
    kind = payload.get("kind", "")
    is_user = kind == "user_report"
    title_emoji = "🗣️" if is_user else "🚨"
    title_text = "用户反馈" if is_user else "自动错误上报"
    color = "blue" if is_user else "red"

    user = payload.get("user", {}) or {}
    sysinfo = payload.get("system", {}) or {}
    appinfo = payload.get("app", {}) or {}
    telem = payload.get("telemetry", {}) or {}
    desc = (payload.get("description") or "").strip()
    err = payload.get("error") or {}
    logs = payload.get("logs", {}) or {}

    # 头部摘要
    header_md = (
        f"**用户**：{user.get('name','?')} · `{user.get('machine','?')}`\n"
        f"**版本**：v{appinfo.get('version','?')} · {sysinfo.get('os','?')} · {sysinfo.get('arch','?')}\n"
        f"**主机**：`{sysinfo.get('host','?')}`\n"
        f"**时间**：{payload.get('ts','?')}"
    )

    # 用法/累计
    if telem:
        header_md += (
            f"\n**累计**：归档 {telem.get('total_archived',0)} · "
            f"胶囊 {telem.get('total_capsule_opens',0)} · "
            f"目标 `{telem.get('default_target','?') or '(未设)'}`"
        )

    elements: list[dict[str, Any]] = [
        {"tag": "div", "text": {"tag": "lark_md", "content": header_md}},
        {"tag": "hr"},
    ]

    if desc:
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"💬 **用户描述**\n\n{_truncate(desc, 400)}"},
        })
        elements.append({"tag": "hr"})

    if err:
        err_md = (
            f"**错误类型**：`{err.get('type','?')}`\n"
            f"**错误位置**：`{err.get('where','?')}`\n"
            f"**消息**：{_truncate(err.get('message',''), 200)}"
        )
        if err.get("traceback"):
            err_md += f"\n\n```\n{_truncate(err['traceback'], 600)}\n```"
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": err_md}})
        elements.append({"tag": "hr"})

    elements.append({
        "tag": "div",
        "text": {"tag": "lark_md", "content": f"📋 **日志摘要**\n\n{_format_logs_block(logs)}"},
    })

    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "template": color,
                "title": {"tag": "plain_text", "content": f"{title_emoji} Skillless · {title_text}"},
            },
            "elements": elements,
        },
    }


# ============================================================
# 发送
# ============================================================

def send_feedback(payload: dict[str, Any], *, timeout: float = 8.0) -> dict[str, Any]:
    """POST 飞书 webhook。返回 {ok, error?, fallback?}：
    - ok=True：发送成功
    - ok=False, fallback="clipboard"：webhook 不通，已复制到剪贴板
    - ok=False, fallback=None：webhook 也没配，无法发送
    """
    webhook = get_feedback_webhook()
    if not webhook:
        # 没有 webhook → 降级到剪贴板
        return _fallback_to_clipboard(payload, reason="no_webhook")

    try:
        body = json.dumps(to_feishu_card(payload), ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            webhook,
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = r.read().decode("utf-8", errors="replace")[:200]
            try:
                rj = json.loads(resp)
                # 飞书机器人成功返回 {"StatusCode":0,"StatusMessage":"success"} 或 {"code":0,"msg":"success"}
                ok = (rj.get("StatusCode") == 0) or (rj.get("code") == 0)
                if ok:
                    return {"ok": True, "channel": "feishu"}
                return _fallback_to_clipboard(payload, reason=f"feishu_reject: {resp}")
            except Exception:
                return {"ok": True, "channel": "feishu", "raw": resp}
    except urllib.error.HTTPError as e:
        return _fallback_to_clipboard(payload, reason=f"http_{e.code}")
    except Exception as e:
        return _fallback_to_clipboard(payload, reason=f"{type(e).__name__}: {e}")


def _fallback_to_clipboard(payload: dict[str, Any], *, reason: str) -> dict[str, Any]:
    """webhook 不通 → 把整个 payload 复制到剪贴板，用户自己粘给开发者。"""
    try:
        import subprocess
        text = (
            "=== Skillless 反馈包（webhook 发送失败，请复制粘贴给开发者）===\n"
            f"失败原因：{reason}\n\n"
            f"```\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"
        )
        subprocess.run(["pbcopy"], input=text, text=True, timeout=5, check=False)
        return {"ok": False, "fallback": "clipboard", "reason": reason}
    except Exception as e:
        return {"ok": False, "fallback": None, "reason": f"{reason} | clipboard_fail: {e}"}


# ============================================================
# 严重错误捕获 hook（B 路径）
# ============================================================

def _auto_error_enabled() -> bool:
    try:
        from settings_util import load_state
        return bool((load_state().get("feedback", {}) or {}).get("auto_error_enabled", True))
    except Exception:
        return True


_LAST_AUTO_TS: dict[str, float] = {}


def report_auto_error(where: str, exc: BaseException | None = None, *, message: str = "") -> dict[str, Any]:
    """严重错误自动上报。带速率限流：同一 where 30 秒内只发一次。"""
    if not _auto_error_enabled():
        return {"ok": False, "skipped": "disabled"}

    # 速率限流：避免同一 bug 刷屏
    now = time.time()
    last = _LAST_AUTO_TS.get(where, 0)
    if now - last < 30:
        return {"ok": False, "skipped": "rate_limit"}
    _LAST_AUTO_TS[where] = now

    err: dict[str, Any] = {"where": where, "message": message[:300]}
    if exc is not None:
        err["type"] = type(exc).__name__
        err["message"] = (message or str(exc))[:300]
        try:
            err["traceback"] = traceback.format_exc()[-1500:]
        except Exception:
            pass
    payload = build_payload(kind="auto_error", error_brief=err)
    return send_feedback(payload, timeout=4.0)
