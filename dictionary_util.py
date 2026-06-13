"""纠错词典：硬替换 + 持久化（路线 A）。

存储路径：`data_dir() / "dictionary.json"`
结构：
  {
    "entries": [
      {"wrong": "项目 X", "right": "项目 X 正式名", "ctx": "项目 X.md",
       "ts": "2026-06-08T17:30:00", "hits": 0}
    ]
  }

公共 API：
  - load_dictionary() -> dict
  - save_dictionary(d) -> None         # 原子写
  - add_entry(wrong, right, ctx="") -> dict
  - delete_entry(wrong) -> dict
  - apply_dictionary(text) -> (text, hits)  # 按词条做硬替换，同步累加 hits
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

from app_paths import data_dir


DICT_FILENAME = "dictionary.json"


def _dict_path() -> Path:
    return data_dir() / DICT_FILENAME


def load_dictionary() -> dict:
    p = _dict_path()
    if not p.exists():
        return {"entries": []}
    try:
        raw = p.read_text(encoding="utf-8")
        obj = json.loads(raw)
    except Exception:
        return {"entries": []}
    if not isinstance(obj, dict):
        return {"entries": []}
    entries = obj.get("entries")
    if not isinstance(entries, list):
        return {"entries": []}
    # 兜底：保留可序列化的 dict 元素
    cleaned = []
    for e in entries:
        if isinstance(e, dict) and e.get("wrong") and e.get("right"):
            cleaned.append(e)
    return {"entries": cleaned}


def save_dictionary(d: dict) -> None:
    """原子写：先写 .tmp 再 rename。"""
    p = _dict_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    payload = json.dumps(d or {"entries": []}, ensure_ascii=False, indent=2)
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, p)


# source 优先级：manual > auto。一旦人工确认过，自动学习不要把它降级回 auto。
_SOURCE_PRIORITY = {"manual": 2, "auto": 1}


def _normalize_source(src: str | None) -> str:
    s = (src or "").strip().lower()
    return s if s in _SOURCE_PRIORITY else "manual"


def add_entry(wrong: str, right: str, ctx: str = "", source: str = "manual") -> dict:
    w = (wrong or "").strip()
    r = (right or "").strip()
    if not w or not r:
        return {"ok": False, "error": "wrong/right 不能为空"}
    if w == r:
        return {"ok": False, "error": "wrong 和 right 不能相同"}

    new_src = _normalize_source(source)
    d = load_dictionary()
    entries = list(d.get("entries", []))
    now = datetime.now().isoformat(timespec="seconds")
    found = None
    for e in entries:
        if e.get("wrong") == w:
            found = e
            break
    if found is not None:
        old_src = _normalize_source(found.get("source"))
        old_prio = _SOURCE_PRIORITY.get(old_src, 0)
        new_prio = _SOURCE_PRIORITY.get(new_src, 0)
        # 高优先级 source（如 manual）不被低优先级（auto）覆盖：
        # right/ctx 也一并保留，避免 manual 的钦定写法被 auto 改掉
        if new_prio >= old_prio:
            found["right"] = r
            found["ctx"] = ctx or found.get("ctx", "")
            found["source"] = new_src
        else:
            found.setdefault("source", old_src)
        found["ts"] = now
        # 保留已有 hits
        found.setdefault("hits", 0)
        entry = found
    else:
        entry = {
            "wrong": w,
            "right": r,
            "ctx": ctx,
            "ts": now,
            "hits": 0,
            "source": new_src,
        }
        entries.append(entry)

    d["entries"] = entries
    try:
        save_dictionary(d)
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}
    return {"ok": True, "entry": entry}


def delete_entry(wrong: str) -> dict:
    w = (wrong or "").strip()
    if not w:
        return {"ok": False, "error": "wrong 不能为空"}
    d = load_dictionary()
    entries = d.get("entries", [])
    new_entries = [e for e in entries if e.get("wrong") != w]
    if len(new_entries) == len(entries):
        return {"ok": False, "error": "未找到该词条"}
    d["entries"] = new_entries
    try:
        save_dictionary(d)
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}
    return {"ok": True}


_ASCII_ONLY = re.compile(r"^[\x00-\x7F]+$")


def _is_pure_ascii(s: str) -> bool:
    return bool(_ASCII_ONLY.match(s or ""))


def apply_dictionary(text: str) -> tuple[str, list[dict]]:
    """按词条对 text 做硬替换。

    - 词条按 wrong 长度倒序处理，避免短串先替换破坏长串
    - 纯 ASCII wrong 用 `\\b...\\b` 做全词边界匹配
    - 含 CJK 的 wrong 用直接 `text.replace`
    - 替换次数同步加到对应 entry 的 hits 字段，并 save 回 json

    返回 (替换后文本, 命中列表[{wrong, right, n}])。
    """
    if not text:
        return text, []

    d = load_dictionary()
    entries = d.get("entries", [])
    if not entries:
        return text, []

    sorted_entries = sorted(
        entries,
        key=lambda e: -len(str(e.get("wrong", "") or "")),
    )

    out = text
    hits: list[dict] = []
    changed = False

    for e in sorted_entries:
        w = str(e.get("wrong", "") or "")
        r = str(e.get("right", "") or "")
        if not w or not r or w == r:
            continue

        if _is_pure_ascii(w):
            try:
                pattern = re.compile(r"\b" + re.escape(w) + r"\b")
                new_out, n = pattern.subn(r, out)
            except re.error:
                new_out, n = out, 0
        else:
            n = out.count(w)
            new_out = out.replace(w, r) if n else out

        if n > 0:
            out = new_out
            hits.append({"wrong": w, "right": r, "n": n})
            try:
                e["hits"] = int(e.get("hits", 0) or 0) + n
            except Exception:
                e["hits"] = n
            changed = True

    if changed:
        d["entries"] = entries
        try:
            save_dictionary(d)
        except Exception:
            pass

    return out, hits
