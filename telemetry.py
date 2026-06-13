"""轻量本地埋点：曝光 + 点击，写 jsonl，永不阻塞主流程。

存储：.history/events.jsonl  (一行一条 JSON)

事件格式：
  {"ts": 1733400000, "kind": "view"|"click", "scope": "dashboard"|"capsule"|"menubar",
   "name": "home"|"click_archive"|..., "props": {...optional}}

使用：
  from telemetry import track
  track("view", "home")
  track("click", "archive", scope="capsule", props={"target": "daily.md"})

聚合：summary(days=7) 返回过去 N 天每个 event 的计数。
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from app_paths import data_dir

EVENTS_PATH = data_dir() / ".history" / "events.jsonl"
MAX_LINES = 10_000  # 防止无限增长，超出则保留尾部 8000 条

_lock = threading.Lock()


def track(
    kind: str,
    name: str,
    *,
    scope: str = "dashboard",
    props: dict[str, Any] | None = None,
) -> None:
    """非阻塞、never raise。kind in {view, click}。"""
    rec: dict[str, Any] = {
        "ts": int(time.time()),
        "kind": kind,
        "scope": scope,
        "name": name,
    }
    if props:
        rec["props"] = props
    try:
        EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            with EVENTS_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            _rotate_if_needed()
    except Exception:
        pass


def _rotate_if_needed() -> None:
    if not EVENTS_PATH.exists():
        return
    try:
        sz = EVENTS_PATH.stat().st_size
    except Exception:
        return
    # 50KB 以下不查行数
    if sz < 50 * 1024:
        return
    lines = EVENTS_PATH.read_text(encoding="utf-8").splitlines()
    if len(lines) <= MAX_LINES:
        return
    EVENTS_PATH.write_text("\n".join(lines[-8000:]) + "\n", encoding="utf-8")


def summary(days: int = 7) -> dict[str, Any]:
    """过去 N 天每个 event 的计数。返回：
    {"total": int, "since_ts": int, "by_name": {scope.kind.name: count}, "top": [...]}
    """
    if not EVENTS_PATH.exists():
        return {"total": 0, "since_ts": 0, "by_name": {}, "top": []}
    cutoff = int(time.time()) - days * 86400
    by_name: dict[str, int] = {}
    total = 0
    try:
        with EVENTS_PATH.open("r", encoding="utf-8") as f:
            for ln in f:
                try:
                    r = json.loads(ln)
                except Exception:
                    continue
                if r.get("ts", 0) < cutoff:
                    continue
                key = f"{r.get('scope', '?')}.{r.get('kind', '?')}.{r.get('name', '?')}"
                by_name[key] = by_name.get(key, 0) + 1
                total += 1
    except Exception:
        pass
    top = sorted(by_name.items(), key=lambda kv: kv[1], reverse=True)[:20]
    return {
        "total": total,
        "since_ts": cutoff,
        "days": days,
        "by_name": by_name,
        "top": [{"name": k, "count": v} for k, v in top],
    }


def recent(limit: int = 50) -> list[dict[str, Any]]:
    """返回最近 N 条事件，时间倒序。"""
    if not EVENTS_PATH.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        lines = EVENTS_PATH.read_text(encoding="utf-8").splitlines()
        for ln in reversed(lines):
            try:
                out.append(json.loads(ln))
            except Exception:
                continue
            if len(out) >= limit:
                break
    except Exception:
        pass
    return out
