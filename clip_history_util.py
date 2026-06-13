"""复制历史指纹库：记录已精简过的文本指纹，供下次复制时做重复检测。

存储：~/Library/Application Support/Skillless/clip_history.jsonl
- 每行一条 JSON：{ts, sha1, head, tail, len, preview, target}
- 上限 1000 条；超出时滚动丢弃最老的 200 条（一次性截断到 800 行）
- 指纹基于「归一化空白后」的文本（多空格 / 换行折叠为 1 个空格）

设计取舍：
- 不存原文（隐私：用户复制的可能是会议记录、密码、私人内容）
- 只存 sha1 全文 + 头/尾 sha1 + 长度，做精确匹配 + 容错近似匹配
- preview 只存头部 30 字，仅用于在吐槽里给用户看「上次复制开头是啥」
- 任何 IO 失败都静默退化（返回空 / None），绝不抛给上游 worker
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from app_paths import data_dir


HISTORY_PATH = data_dir() / "clip_history.jsonl"
MAX_LINES = 1000
TRIM_KEEP = 800
PREVIEW_LEN = 30
HEAD_TAIL_LEN = 200
MIN_LEN_FOR_TRACK = 30
NEAR_LEN_TOLERANCE = 0.05

_WS_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    """归一化：折叠所有空白为单空格，去首尾。短指纹更稳。"""
    if not text:
        return ""
    return _WS_RE.sub(" ", text).strip()


def _sha1(text: str, length: int = 0) -> str:
    h = hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()
    return h[:length] if length else h


def fingerprint(text: str) -> dict:
    """返回 {len, sha1, head, tail}：
    - sha1: 归一化后全文 sha1[:16]
    - head: 归一化后前 200 字的 sha1[:12]
    - tail: 归一化后后 200 字的 sha1[:12]
    - len:  归一化后长度（用来做近似匹配的长度差）
    短文本时 head 和 tail 可能 hash 同一份内容，这是预期行为。
    """
    norm = _normalize(text or "")
    return {
        "len": len(norm),
        "sha1": _sha1(norm, 16),
        "head": _sha1(norm[:HEAD_TAIL_LEN], 12),
        "tail": _sha1(norm[-HEAD_TAIL_LEN:], 12),
    }


def _human_ago(minutes: int) -> str:
    """把分钟差换成「N 分钟前 / N 小时前 / N 天前 / N 周前」。"""
    if minutes < 1:
        return "刚刚"
    if minutes < 60:
        return f"{minutes} 分钟前"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} 小时前"
    days = hours // 24
    if days < 7:
        return f"{days} 天前"
    weeks = days // 7
    return f"{weeks} 周前"


def _atomic_write_lines(path: Path, lines: list[str]) -> None:
    """临时文件 + os.replace 原子覆盖，避免读到半截文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".clip_history.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for ln in lines:
                if not ln.endswith("\n"):
                    ln = ln + "\n"
                f.write(ln)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def _maybe_trim(path: Path) -> None:
    """超过 MAX_LINES 时一次性截到 TRIM_KEEP 行（保留最新）。"""
    try:
        if not path.exists():
            return
        with path.open("r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        if len(lines) <= MAX_LINES:
            return
        kept = lines[-TRIM_KEEP:]
        _atomic_write_lines(path, kept)
    except Exception:
        pass


def append_clip(text: str, target: str = "") -> None:
    """记一条指纹。无效输入（空 / 过短）静默跳过；任何写失败静默吞掉。"""
    norm = _normalize(text or "")
    if len(norm) < MIN_LEN_FOR_TRACK:
        return
    fp = fingerprint(text)
    row = {
        "ts": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "sha1": fp["sha1"],
        "head": fp["head"],
        "tail": fp["tail"],
        "len": fp["len"],
        "preview": norm[:PREVIEW_LEN],
        "target": target or "",
    }
    try:
        HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with HISTORY_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:
        return
    _maybe_trim(HISTORY_PATH)


def _parse_ts(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def find_duplicate(text: str, max_age_days: int = 30) -> dict | None:
    """扫历史找重复条目，倒序（最新先）。

    匹配规则：
      - exact: 归一化后 sha1 完全一致
      - near : head + tail 一致 且 长度差 < 5%
    返回 {match, ts, preview, minutes_ago, human_ago}；找不到 / 出错均返回 None。
    """
    norm = _normalize(text or "")
    if len(norm) < MIN_LEN_FOR_TRACK:
        return None
    if not HISTORY_PATH.exists():
        return None

    cur = fingerprint(text)
    cutoff = datetime.now(timezone.utc).astimezone() - _td_days(max_age_days)

    try:
        with HISTORY_PATH.open("r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception:
        return None

    for raw in reversed(lines):
        s = raw.strip()
        if not s:
            continue
        try:
            row = json.loads(s)
        except Exception:
            continue
        ts = _parse_ts(row.get("ts", ""))
        if ts is None:
            continue
        if ts < cutoff:
            break

        match: str | None = None
        if row.get("sha1") and row["sha1"] == cur["sha1"]:
            match = "exact"
        elif (
            row.get("head") and row.get("tail")
            and row["head"] == cur["head"]
            and row["tail"] == cur["tail"]
        ):
            old_len = int(row.get("len") or 0)
            if old_len > 0:
                diff = abs(old_len - cur["len"]) / max(old_len, cur["len"])
                if diff < NEAR_LEN_TOLERANCE:
                    match = "near"

        if match is None:
            continue

        now = datetime.now(timezone.utc).astimezone()
        minutes = max(0, int((now - ts).total_seconds() // 60))
        return {
            "match": match,
            "ts": row.get("ts", ""),
            "preview": row.get("preview", ""),
            "minutes_ago": minutes,
            "human_ago": _human_ago(minutes),
        }

    return None


def _td_days(n: int):
    from datetime import timedelta
    return timedelta(days=max(0, int(n)))
