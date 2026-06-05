"""剪贴板历史记录：文字 + 图片，统一 JSONL + sidecar 文件。

存储位置：
  .history/clips.jsonl    # 一行一条
  .history/img/<sha>.png  # 图片实体
  .history/stats.json     # 累计字数 / 条数（轻量缓存）

设计原则：
- 写入 append-only，不锁文件（macOS 单进程菜单栏 OK）
- preview 截 120 字，原文超过 800 字才落 sidecar txt
- 默认上限 1000 条，超过滚动
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
HISTORY_DIR = SCRIPT_DIR / ".history"
CLIPS_PATH = HISTORY_DIR / "clips.jsonl"
IMG_DIR = HISTORY_DIR / "img"
TXT_DIR = HISTORY_DIR / "txt"
STATS_PATH = HISTORY_DIR / "stats.json"

MAX_RECORDS = 1000
PREVIEW_CHARS = 120
INLINE_TEXT_LIMIT = 800


def _ensure_dirs() -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    TXT_DIR.mkdir(parents=True, exist_ok=True)


def _hash(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()[:16]


def _preview(text: str) -> str:
    flat = re.sub(r"\s+", " ", text.strip())
    return flat[:PREVIEW_CHARS] + ("…" if len(flat) > PREVIEW_CHARS else "")


def _load_stats() -> dict[str, Any]:
    if not STATS_PATH.exists():
        return {"chars": 0, "count": 0, "archived": 0, "first_at": 0}
    try:
        return json.loads(STATS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"chars": 0, "count": 0, "archived": 0, "first_at": 0}


def _save_stats(stats: dict[str, Any]) -> None:
    _ensure_dirs()
    STATS_PATH.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")


def get_stats() -> dict[str, Any]:
    """首页用：总字数、总条数、累计归档数、节省时间。"""
    s = _load_stats()
    minutes = int(s.get("archived", 0))
    return {
        "chars": int(s.get("chars", 0)),
        "count": int(s.get("count", 0)),
        "archived": int(s.get("archived", 0)),
        "first_at": int(s.get("first_at", 0)),
        "saved_minutes": minutes,
        "saved_hhmm": f"{minutes // 60:02d}:{minutes % 60:02d}",
    }


def bump_archived(n: int = 1) -> None:
    """每次成功写入 md 时调一次。"""
    s = _load_stats()
    s["archived"] = int(s.get("archived", 0)) + n
    _save_stats(s)


def _append(record: dict[str, Any]) -> None:
    _ensure_dirs()
    with CLIPS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    s = _load_stats()
    if not s.get("first_at"):
        s["first_at"] = int(record["ts"])
    s["count"] = int(s.get("count", 0)) + 1
    if record.get("type") == "text":
        s["chars"] = int(s.get("chars", 0)) + int(record.get("len", 0))
    _save_stats(s)

    _rotate_if_needed()


def _rotate_if_needed() -> None:
    if not CLIPS_PATH.exists():
        return
    lines = CLIPS_PATH.read_text(encoding="utf-8").splitlines()
    if len(lines) <= MAX_RECORDS:
        return
    keep = lines[-MAX_RECORDS:]
    drop = lines[:-MAX_RECORDS]
    CLIPS_PATH.write_text("\n".join(keep) + "\n", encoding="utf-8")
    for ln in drop:
        try:
            rec = json.loads(ln)
        except Exception:
            continue
        for k in ("img_path", "txt_path"):
            p = rec.get(k)
            if p:
                try:
                    Path(p).unlink(missing_ok=True)
                except Exception:
                    pass


def record_text(text: str, *, source: str = "clip") -> dict[str, Any]:
    """记录一次文字复制；返回写入的 record。"""
    text = text or ""
    if not text.strip():
        return {}
    digest = _hash(text.encode("utf-8"))
    record: dict[str, Any] = {
        "ts": int(time.time()),
        "type": "text",
        "source": source,
        "hash": digest,
        "len": len(text),
        "preview": _preview(text),
    }
    if len(text) > INLINE_TEXT_LIMIT:
        txt_path = TXT_DIR / f"{digest}.txt"
        if not txt_path.exists():
            txt_path.write_text(text, encoding="utf-8")
        record["txt_path"] = str(txt_path)
    else:
        record["text"] = text
    _append(record)
    return record


def read_clipboard_image() -> bytes | None:
    """尝试从剪贴板取图片（PNG bytes），失败返回 None。"""
    script = '''
    on run
        try
            set theData to (the clipboard as «class PNGf»)
        on error
            return ""
        end try
        set f to (POSIX file "{path}") as string
        set fh to open for access file f with write permission
        set eof fh to 0
        write theData to fh
        close access fh
        return "{path}"
    end run
    '''
    out_path = HISTORY_DIR / "_tmp_clip.png"
    _ensure_dirs()
    script = script.replace("{path}", str(out_path))
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=8)
    except Exception:
        return None
    if r.returncode != 0 or not out_path.exists():
        return None
    try:
        data = out_path.read_bytes()
    finally:
        try:
            out_path.unlink(missing_ok=True)
        except Exception:
            pass
    return data if data else None


def record_image(data: bytes, *, source: str = "clip") -> dict[str, Any]:
    if not data:
        return {}
    digest = _hash(data)
    img_path = IMG_DIR / f"{digest}.png"
    if not img_path.exists():
        img_path.write_bytes(data)
    record = {
        "ts": int(time.time()),
        "type": "image",
        "source": source,
        "hash": digest,
        "size": len(data),
        "img_path": str(img_path),
        "preview": f"图片 {len(data) // 1024} KB",
    }
    _append(record)
    return record


# mtime-based cache：避免 dashboard 反复全量读 + parse jsonl
_records_cache: dict[str, Any] = {"mtime_ns": -1, "size": -1, "records": []}


def _read_all_records() -> list[dict[str, Any]]:
    """返回按时间正序的所有记录，命中 mtime 缓存时直接复用。"""
    if not CLIPS_PATH.exists():
        return []
    try:
        st = CLIPS_PATH.stat()
    except FileNotFoundError:
        return []
    if (
        _records_cache["mtime_ns"] == st.st_mtime_ns
        and _records_cache["size"] == st.st_size
    ):
        return _records_cache["records"]

    out: list[dict[str, Any]] = []
    try:
        with CLIPS_PATH.open("r", encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    out.append(json.loads(ln))
                except Exception:
                    continue
    except Exception:
        return _records_cache["records"]

    _records_cache["mtime_ns"] = st.st_mtime_ns
    _records_cache["size"] = st.st_size
    _records_cache["records"] = out
    return out


def list_records(
    *, limit: int = 100, kind: str | None = None, offset: int = 0
) -> list[dict[str, Any]]:
    """按时间倒序返回；支持分页 (offset, limit)。"""
    recs = _read_all_records()
    out: list[dict[str, Any]] = []
    skipped = 0
    for rec in reversed(recs):
        if kind and rec.get("type") != kind:
            continue
        if skipped < offset:
            skipped += 1
            continue
        out.append(rec)
        if len(out) >= limit:
            break
    return out


def count_records(kind: str | None = None) -> int:
    recs = _read_all_records()
    if not kind:
        return len(recs)
    return sum(1 for r in recs if r.get("type") == kind)


def get_last_record() -> dict[str, Any] | None:
    rs = list_records(limit=1)
    return rs[0] if rs else None


def clear_history() -> None:
    if CLIPS_PATH.exists():
        CLIPS_PATH.unlink()
    for p in IMG_DIR.glob("*.png"):
        p.unlink(missing_ok=True)
    for p in TXT_DIR.glob("*.txt"):
        p.unlink(missing_ok=True)
    _save_stats({"chars": 0, "count": 0, "archived": _load_stats().get("archived", 0), "first_at": 0})


def get_text_for(record: dict[str, Any]) -> str:
    if record.get("text"):
        return record["text"]
    p = record.get("txt_path")
    if p and Path(p).exists():
        return Path(p).read_text(encoding="utf-8")
    return record.get("preview", "")
