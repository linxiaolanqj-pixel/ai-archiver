"""弹窗 / 预览展示工具（避免 AppleScript 小框塞长文）"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

PREVIEW_DIR = Path(__file__).resolve().parent
MAX_DIALOG_SNIPPET = 300


def truncate_for_dialog(text: str, max_len: int = MAX_DIALOG_SNIPPET) -> str:
    t = re.sub(r"\s+", " ", text.strip())
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


def one_line_summary(text: str, max_len: int = 80) -> str:
    """取第一句或一行摘要。"""
    t = text.strip()
    for sep in ("。", "！", "？", "\n", ". "):
        if sep in t:
            t = t.split(sep)[0] + (sep if sep in "。！？" else "")
            break
    return truncate_for_dialog(t, max_len)


def open_in_textedit(path: Path) -> None:
    path = path.resolve()
    subprocess.run(["open", "-a", "TextEdit", str(path)], check=False)


def open_html(name: str) -> None:
    """打开 onboarding_ui 下的对比页。"""
    p = PREVIEW_DIR / "onboarding_ui" / name
    if p.exists():
        subprocess.run(["open", str(p)], check=False)


def show_long_text_preview(
    content: str,
    *,
    filename: str = "archiver_preview.md",
    dialog_title: str = "预览",
    dialog_prompt: str = "完整内容已在 TextEdit 打开",
) -> Path:
    """长文进 TextEdit，返回临时文件路径。"""
    tmp = PREVIEW_DIR / filename
    tmp.write_text(content, encoding="utf-8")
    open_in_textedit(tmp)
    return tmp
