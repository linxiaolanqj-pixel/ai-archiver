"""归档目标选择：用系统 Finder 直接点选 .md（不用手输路径、不列长清单）"""

from __future__ import annotations

import subprocess
from pathlib import Path

NEW_FILE_LABEL = "➕ 新建文件…"


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _run_apple(script: str) -> str:
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=300)
        return (r.stdout or "").strip()
    except Exception:
        return ""


def _to_relative(root: Path, abs_path: Path) -> str | None:
    try:
        rel = abs_path.resolve().relative_to(root.resolve())
        if rel.suffix.lower() != ".md":
            return None
        return rel.as_posix()
    except ValueError:
        return None


def choose_md_file(
    kb_root: Path,
    *,
    prompt: str = "选择要写入的 Markdown 文档",
) -> str | None:
    """打开系统文件选择器，用户在文件夹里直接点选 .md。返回相对知识库根的路径。"""
    kb_root = kb_root.resolve()
    kb_root.mkdir(parents=True, exist_ok=True)
    script = f'''
    set kbRoot to POSIX file "{_escape(str(kb_root))}"
    try
      set theFile to choose file with prompt "{_escape(prompt)}" default location kbRoot without invisibles
      return POSIX path of theFile
    on error
      return ""
    end try
    '''
    raw = _run_apple(script)
    if not raw:
        return None
    rel = _to_relative(kb_root, Path(raw))
    return rel


def choose_new_md_file(
    kb_root: Path,
    *,
    prompt: str = "新建 Markdown 文档（可建在子文件夹里）",
    default_name: str = "我的笔记.md",
) -> str | None:
    """系统「存储为」面板：选位置 + 文件名，自动落在知识库内。"""
    kb_root = kb_root.resolve()
    kb_root.mkdir(parents=True, exist_ok=True)
    script = f'''
    set kbRoot to POSIX file "{_escape(str(kb_root))}"
    try
      set newFile to choose file name with prompt "{_escape(prompt)}" default name "{_escape(default_name)}" default location kbRoot
      return POSIX path of newFile
    on error
      return ""
    end try
    '''
    raw = _run_apple(script)
    if not raw:
        return None
    path = Path(raw)
    if path.suffix.lower() != ".md":
        path = path.with_suffix(".md")
    rel = _to_relative(kb_root, path)
    if not rel:
        return None
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {path.stem}\n\n", encoding="utf-8")
    return rel


def choose_archive_target(
    kb_root: Path,
    *,
    prompt: str = "选择 Markdown 文档",
) -> str | None:
    """归档时选目标：Finder 点选已有 .md，或新建。"""
    items = f'"{_escape("📄 在文件夹里选择 .md")}", "{_escape(NEW_FILE_LABEL)}"'
    script = (
        f'set L to {{{items}}}\n'
        f'set c to choose from list L with prompt "{_escape(prompt)}" '
        f'with title "📂 选择写入目标" OK button name "下一步" cancel button name "取消"\n'
        f'if c is false then return ""\n'
        f'return item 1 of c'
    )
    picked = _run_apple(script)
    if not picked:
        return None
    if picked == NEW_FILE_LABEL:
        return choose_new_md_file(kb_root)
    return choose_md_file(kb_root, prompt=prompt)
