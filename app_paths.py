"""Skillless 路径：开发态用项目目录；打包 .app 后资源只读、数据写入 Application Support。"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_APP_NAME = "Skillless"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    """只读资源：HTML/CSS、默认 config、prompts 等。"""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS"))  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent


def data_dir() -> Path:
    """可写数据：.state.json、.history、.env、用户 config。"""
    if is_frozen():
        d = Path.home() / "Library" / "Application Support" / _APP_NAME
        d.mkdir(parents=True, exist_ok=True)
        return d
    return Path(__file__).resolve().parent


def config_path() -> Path:
    """用户 config 优先；打包后首次从 bundle 复制一份到 Application Support。"""
    user_cfg = data_dir() / "config.yaml"
    if user_cfg.exists():
        return user_cfg
    bundled = resource_dir() / "config.yaml"
    if is_frozen() and bundled.exists():
        shutil.copy2(bundled, user_cfg)
        return user_cfg
    return bundled


def ensure_data_subdirs() -> None:
    (data_dir() / ".history").mkdir(parents=True, exist_ok=True)
