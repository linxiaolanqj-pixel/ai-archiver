"""配置 / 状态 / 黑名单 读写（菜单栏与 archiver 共用）"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_PATH = SCRIPT_DIR / "config.yaml"
STATE_PATH = SCRIPT_DIR / ".state.json"
ENV_PATH = SCRIPT_DIR / ".env"

DEEPSEEK_API_KEYS_URL = "https://platform.deepseek.com/api_keys"

# 扫描知识库时跳过的目录名
_SKIP_DIR_NAMES = {".git", ".venv", "node_modules", ".obsidian", "__pycache__", ".cursor"}
_SKIP_FILE_NAMES = {"readme.md", "_archive_log.md"}

# 内置：常见应跳过的内容
BUILTIN_SKIP_PATTERNS = [
    r"^https?://\S+$",                    # 整段就是一个 URL
    r"^www\.\S+$",
    r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$",  # 整段是邮箱
]


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_config(cfg: dict[str, Any]) -> None:
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def kb_root(cfg: dict | None = None) -> Path:
    cfg = cfg or load_config()
    return Path(os.path.expanduser(cfg["knowledge_base"]["root"])).resolve()


def get_blacklist(cfg: dict | None = None) -> list[str]:
    cfg = cfg or load_config()
    beh = cfg.get("behavior", {}) or {}
    extra = list(beh.get("skip_blacklist", []) or [])
    state_extra = load_state().get("skip_blacklist_extra", []) or []
    merged: list[str] = []
    for p in BUILTIN_SKIP_PATTERNS + extra + state_extra:
        if p and p not in merged:
            merged.append(p)
    return merged


def should_skip_text(text: str, min_length: int, cfg: dict | None = None) -> bool:
    t = text.strip()
    if len(t) < min_length:
        return True
    for pat in get_blacklist(cfg):
        try:
            if re.search(pat, t, re.IGNORECASE | re.MULTILINE):
                return True
        except re.error:
            continue
    return False


def add_to_blacklist_extra(pattern: str) -> None:
    pattern = pattern.strip()
    if not pattern:
        return
    state = load_state()
    extra: list[str] = state.get("skip_blacklist_extra", []) or []
    if pattern not in extra:
        extra.append(pattern)
    state["skip_blacklist_extra"] = extra
    save_state(state)


def remove_from_blacklist_extra(pattern: str) -> None:
    state = load_state()
    extra: list[str] = state.get("skip_blacklist_extra", []) or []
    state["skip_blacklist_extra"] = [p for p in extra if p != pattern]
    save_state(state)


def onboarding_done() -> bool:
    return bool(load_state().get("onboarding_complete"))


def _sanitize_target_rel(rel: str | None) -> str | None:
    """过滤误写入的 AppleScript 返回值等非法路径。"""
    if not rel:
        return None
    s = str(rel).strip()
    if not s or "button returned" in s or "text returned" in s:
        return None
    if s.startswith("/") or "\n" in s:
        return None
    if not s.lower().endswith(".md"):
        return None
    return s


def _repair_state_targets(state: dict[str, Any]) -> bool:
    """清理 state 里损坏的 default / favorites / usage 键。"""
    changed = False
    clean_default = _sanitize_target_rel(state.get("default_target"))
    if state.get("default_target") != clean_default:
        if clean_default:
            state["default_target"] = clean_default
        else:
            state.pop("default_target", None)
        changed = True
    fav = [_sanitize_target_rel(f) for f in (state.get("favorite_targets") or [])]
    fav_clean = []
    for f in fav:
        if f and f not in fav_clean:
            fav_clean.append(f)
    if fav_clean != state.get("favorite_targets"):
        state["favorite_targets"] = fav_clean
        changed = True
    usage = state.get("target_usage") or {}
    usage_clean = {k: v for k, v in usage.items() if _sanitize_target_rel(k)}
    if usage_clean != usage:
        state["target_usage"] = usage_clean
        changed = True
    return changed


def mark_onboarding_done(*, default_target: str | None = None) -> None:
    state = load_state()
    state["onboarding_complete"] = True
    rel = _sanitize_target_rel(default_target)
    if rel:
        set_default_target(rel, state=state)
    save_state(state)


def get_default_target() -> str | None:
    state = load_state()
    if _repair_state_targets(state):
        save_state(state)
    return _sanitize_target_rel(state.get("default_target"))


def set_default_target(rel: str, *, state: dict | None = None) -> None:
    """设置唯一默认归档文档，并置顶到常用列表。"""
    clean = _sanitize_target_rel(rel)
    if not clean:
        return
    state = state if state is not None else load_state()
    state["default_target"] = clean
    fav: list[str] = list(state.get("favorite_targets") or [])
    fav = [clean] + [_sanitize_target_rel(f) for f in fav if _sanitize_target_rel(f) and f != clean]
    state["favorite_targets"] = fav[:8]
    save_state(state)


def record_target_usage(rel: str) -> None:
    """记录写入次数，用于「常用」排序。"""
    import time

    state = load_state()
    usage: dict = dict(state.get("target_usage") or {})
    row = usage.get(rel, {"count": 0, "last": 0})
    row["count"] = int(row.get("count", 0)) + 1
    row["last"] = int(time.time())
    usage[rel] = row
    state["target_usage"] = usage
    # 把高频使用的自动加入常用（最多 8 个）
    ranked = sorted(usage.items(), key=lambda x: (-x[1].get("count", 0), -x[1].get("last", 0)))
    fav = list(state.get("favorite_targets") or [])
    default = state.get("default_target")
    merged: list[str] = []
    if default:
        merged.append(default)
    for f in fav:
        if f not in merged:
            merged.append(f)
    for path, _ in ranked[:6]:
        if path not in merged:
            merged.append(path)
    state["favorite_targets"] = merged[:8]
    save_state(state)


def get_quick_pick_targets(max_n: int = 6) -> list[str]:
    """常用归档目标（默认文档优先 + 收藏 + 最近使用）。"""
    state = load_state()
    default = state.get("default_target")
    fav: list[str] = list(state.get("favorite_targets") or [])
    usage: dict = state.get("target_usage") or {}
    ranked = sorted(
        usage.keys(),
        key=lambda k: (-usage[k].get("count", 0), -usage[k].get("last", 0)),
    )
    out: list[str] = []
    for rel in [default, *fav, *ranked]:
        if rel and rel not in out:
            out.append(rel)
        if len(out) >= max_n:
            break
    return out


# 首次引导：只允许从这几个里选一个当「默认归档文档」
ONBOARDING_MD_CHOICES: list[tuple[str, str]] = [
    ("今日杂记 🌤", "今日杂记.md"),
    ("顺手买知识库 🛒", "顺手买信息.md"),
    ("会议纪要 📋", "会议纪要.md"),
    ("产品分歧 ⚖️", "产品分歧.md"),
    ("周报素材 📊", "周报素材.md"),
    ("龙虾日记 🦞", "龙虾日记素材.md"),
]


def get_api_key() -> str:
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DEEPSEEK_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("DEEPSEEK_API_KEY", "").strip()


def save_api_key(key: str) -> None:
    key = key.strip()
    lines: list[str] = []
    found = False
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("DEEPSEEK_API_KEY="):
                lines.append(f"DEEPSEEK_API_KEY={key}")
                found = True
            else:
                lines.append(line)
    if not found:
        if not lines and ENV_PATH.exists():
            lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
        lines.append(f"DEEPSEEK_API_KEY={key}")
    if not lines:
        lines = [
            "# AI Archiver API Key",
            "ANTHROPIC_API_KEY=",
            "OPENAI_API_KEY=",
            f"DEEPSEEK_API_KEY={key}",
        ]
    ENV_PATH.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    os.environ["DEEPSEEK_API_KEY"] = key


def set_kb_root(path_str: str) -> None:
    cfg = load_config()
    cfg.setdefault("knowledge_base", {})["root"] = path_str
    save_config(cfg)


def set_min_length(n: int) -> None:
    cfg = load_config()
    cfg.setdefault("behavior", {})["auto_prompt_min_length"] = max(1, int(n))
    save_config(cfg)


def list_custom_prompts(cfg: dict | None = None) -> list[dict[str, str]]:
    cfg = cfg or load_config()
    return list(cfg.get("custom_prompts", []) or [])


def iter_kb_markdown_files(root: Path) -> list[tuple[str, str]]:
    """递归扫描知识库下所有 .md。

    返回 [(展示名, 相对路径)], 例如 ("projects/顺手买/笔记", "projects/顺手买/笔记.md")
    """
    if not root.exists():
        return []
    found: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*.md")):
        if path.name.lower() in _SKIP_FILE_NAMES:
            continue
        if any(part in _SKIP_DIR_NAMES for part in path.relative_to(root).parts):
            continue
        rel = path.relative_to(root).as_posix()
        display = rel[:-3] if rel.endswith(".md") else rel
        found.append((display, rel))
    return found


def create_knowledge_base(name: str, *, base_parent: Path | None = None) -> Path:
    """没有知识库时：按用户取名自动创建目录（~/knowledge/名称）。"""
    import re

    base = (base_parent or (Path.home() / "knowledge")).expanduser()
    safe = re.sub(r"[^\w\u4e00-\u9fff\- ]", "", (name or "").strip()) or "我的知识库"
    root = (base / safe).resolve()
    root.mkdir(parents=True, exist_ok=True)
    ensure_starter_files(root)
    return root


def ensure_starter_files(root: Path) -> None:
    """首次引导：自动创建常用 .md（用户不用自己会建 Markdown）"""
    root.mkdir(parents=True, exist_ok=True)
    starters = {
        "今日杂记.md": "# 今日杂记\n\n",
        "顺手买信息.md": "# 顺手买信息\n\n## 供给\n\n## 实验\n\n## 埋点\n\n## 版本\n\n## 业务方沟通\n\n",
        "会议纪要.md": "# 会议纪要\n\n",
        "产品分歧.md": "# 产品分歧\n\n",
        "周报素材.md": "# 周报素材\n\n",
        "龙虾日记素材.md": "# 龙虾日记素材\n\n",
    }
    for name, content in starters.items():
        p = root / name
        if not p.exists():
            p.write_text(content, encoding="utf-8")
