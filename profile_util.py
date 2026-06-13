"""三层档案（profile）：SOUL / USER / TOOLS。

借鉴 Joyclaw 的人格记忆设计：把"AI 对你的持续认知"沉淀到三个 markdown 文件，
每次精简时都会读，告别冷启动。

存储路径（v0.4.5+，隐私顾虑友好）：
  `data_dir() / ".skillless_profile" / {s,u,t}.md`
  - 目录前缀点号：Finder 默认隐藏，dashboard 仍可一键打开
  - 文件名脱敏：避免「SOUL.md」直接出现在文件树/列表里太直白

模板路径：`resource_dir() / "profile_templates" / {SOUL,USER,TOOLS}.md`
            （打包后被 PyInstaller 带进 .app；首次启动从这里复制并改名到 data_dir）

向后兼容：
  老版本写在 `data_dir() / "profile" / {SOUL,USER,TOOLS}.md`。
  ensure_profile() 启动时检查老路径，发现就一次性迁移到新路径并删除老目录。

公共 API（保持不变）：
  - ensure_profile() -> None
  - load_profile() -> dict {"soul": "...", "user": "...", "tools": "..."}
  - save_profile_part(kind, content) -> dict
  - profile_dir_path() -> str
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from app_paths import data_dir, resource_dir


# 新路径（v0.4.5+）
PROFILE_DIR = data_dir() / ".skillless_profile"
TEMPLATE_DIR = resource_dir() / "profile_templates"

# 老路径（v0.4.4 及更早）：迁移用
LEGACY_PROFILE_DIR = data_dir() / "profile"

# kind → (新文件名, 老文件名 / 模板源文件名)
# 模板源文件名仍是 SOUL/USER/TOOLS.md（打包资源不变）；落到用户目录时改名
_KIND_FILES = {
    "soul":  {"new": "s.md", "legacy": "SOUL.md"},
    "user":  {"new": "u.md", "legacy": "USER.md"},
    "tools": {"new": "t.md", "legacy": "TOOLS.md"},
}


def _ensure_dir() -> Path:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    return PROFILE_DIR


def _migrate_legacy_if_needed() -> None:
    """一次性迁移：v0.4.4 及更早写在 data_dir/profile/{SOUL,USER,TOOLS}.md，
    搬到 data_dir/.skillless_profile/{s,u,t}.md，再删老目录。

    任意一步失败都静默：宁可让用户保留两份也不能丢数据。
    """
    if not LEGACY_PROFILE_DIR.exists() or not LEGACY_PROFILE_DIR.is_dir():
        return
    _ensure_dir()
    moved_any = False
    for spec in _KIND_FILES.values():
        src = LEGACY_PROFILE_DIR / spec["legacy"]
        dst = PROFILE_DIR / spec["new"]
        if not src.exists():
            continue
        if dst.exists():
            # 新位置已经有了（用户可能手动放过 / 第二次启动）→ 跳过，不覆盖
            continue
        try:
            shutil.move(str(src), str(dst))
            moved_any = True
        except Exception:
            try:
                shutil.copy2(src, dst)
                moved_any = True
            except Exception:
                pass
    # 残留的老目录里如果只有 .DS_Store 之类，尝试删掉
    try:
        leftover = [p for p in LEGACY_PROFILE_DIR.iterdir()
                    if p.name not in (".DS_Store",) and p.is_file()]
        if not leftover:
            try:
                shutil.rmtree(LEGACY_PROFILE_DIR, ignore_errors=True)
            except Exception:
                pass
    except Exception:
        pass


def ensure_profile() -> None:
    """确保 PROFILE_DIR 存在；任一文件缺失就从模板拷贝（已有的不动）。

    顺序：
      1. 老路径迁移（仅一次性）
      2. 缺失文件从模板补
    """
    _migrate_legacy_if_needed()
    _ensure_dir()
    for spec in _KIND_FILES.values():
        dst = PROFILE_DIR / spec["new"]
        if dst.exists():
            continue
        src = TEMPLATE_DIR / spec["legacy"]  # 模板源文件名仍是 SOUL/USER/TOOLS.md
        if not src.exists():
            try:
                dst.write_text(
                    f"# {spec['new']}\n\n_这里填你自己的内容。模板暂未提供。_\n",
                    encoding="utf-8",
                )
            except Exception:
                pass
            continue
        try:
            shutil.copy2(src, dst)
        except Exception:
            try:
                content = src.read_text(encoding="utf-8")
                dst.write_text(content, encoding="utf-8")
            except Exception:
                pass


def load_profile() -> dict:
    """读三个文件返回 dict；缺失/损坏返回空串，不抛异常。"""
    out = {"soul": "", "user": "", "tools": ""}
    for kind, spec in _KIND_FILES.items():
        p = PROFILE_DIR / spec["new"]
        if not p.exists():
            continue
        try:
            out[kind] = p.read_text(encoding="utf-8")
        except Exception:
            out[kind] = ""
    return out


def save_profile_part(kind: str, content: str) -> dict:
    """原子写某一份；kind 限定 soul|user|tools。"""
    k = (kind or "").strip().lower()
    if k not in _KIND_FILES:
        return {"ok": False, "error": f"未知 kind：{kind}"}
    _ensure_dir()
    p = PROFILE_DIR / _KIND_FILES[k]["new"]
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(content or "", encoding="utf-8")
        os.replace(tmp, p)
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}
    return {"ok": True, "kind": k, "len": len(content or "")}


def profile_dir_path() -> str:
    """前端展示用：profile 目录绝对路径。"""
    return str(_ensure_dir())
