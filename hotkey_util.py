"""全局快捷键解析与格式化。

后台里用户直接按键录入，菜单栏进程用同一套格式匹配 NSEvent。
统一格式示例：⌃⌥⌘A、⇧⌘K、⌃⌥T。
"""

from __future__ import annotations

import re
from typing import Any

MOD_ORDER = ("⌃", "⌥", "⇧", "⌘")

_ALIASES = {
    "ctrl": "⌃",
    "control": "⌃",
    "⌃": "⌃",
    "^": "⌃",
    "opt": "⌥",
    "option": "⌥",
    "alt": "⌥",
    "⌥": "⌥",
    "shift": "⇧",
    "⇧": "⇧",
    "cmd": "⌘",
    "command": "⌘",
    "meta": "⌘",
    "⌘": "⌘",
}


def normalize_hotkey(value: str | None) -> str:
    """把用户输入的 Ctrl+Option+Cmd+A / ⌃⌥⌘A 统一成符号格式。"""
    if not value:
        return ""
    raw = str(value).strip()
    if not raw:
        return ""

    compact = raw.replace(" ", "")
    if any(sym in compact for sym in MOD_ORDER):
        mods = [sym for sym in MOD_ORDER if sym in compact]
        key = compact
        for sym in MOD_ORDER:
            key = key.replace(sym, "")
        key = key.replace("+", "").upper()
        return "".join(mods) + key if key else ""

    parts = [p for p in re.split(r"[+\-_\s]+", raw.lower()) if p]
    mods: list[str] = []
    key = ""
    for p in parts:
        if p in _ALIASES:
            m = _ALIASES[p]
            if m not in mods:
                mods.append(m)
        else:
            key = p.upper()
    ordered = [m for m in MOD_ORDER if m in mods]
    return "".join(ordered) + key if key else ""


def event_to_hotkey(event: Any) -> str:
    """把 AppKit NSEvent 转成统一快捷键字符串。"""
    try:
        import AppKit
    except Exception:
        return ""

    flags = int(event.modifierFlags())
    mods: list[str] = []
    if flags & int(AppKit.NSEventModifierFlagControl):
        mods.append("⌃")
    if flags & int(AppKit.NSEventModifierFlagOption):
        mods.append("⌥")
    if flags & int(AppKit.NSEventModifierFlagShift):
        mods.append("⇧")
    if flags & int(AppKit.NSEventModifierFlagCommand):
        mods.append("⌘")

    try:
        chars = event.charactersIgnoringModifiers() or event.characters() or ""
    except Exception:
        chars = ""
    if not chars:
        return ""
    key = chars.upper()
    if key == "\r":
        key = "↩"
    elif key == "\x1b":
        key = "ESC"
    elif len(key) > 1:
        # 功能键等暂不支持，避免误判。
        return ""

    return "".join([m for m in MOD_ORDER if m in mods]) + key


def is_reasonable_hotkey(value: str | None) -> bool:
    """至少包含一个修饰键和一个普通键，避免单键误触。"""
    h = normalize_hotkey(value)
    if not h:
        return False
    return any(m in h for m in MOD_ORDER) and len(h) > 1
