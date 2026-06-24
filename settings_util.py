"""配置 / 状态 / 黑名单 读写（菜单栏与 archiver 共用）"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import yaml

from app_paths import config_path, data_dir, ensure_data_subdirs, resource_dir

SCRIPT_DIR = resource_dir()  # 兼容旧代码：指向资源根（开发=项目目录，打包=_MEIPASS）
CONFIG_PATH = config_path()
STATE_PATH = data_dir() / ".state.json"
ENV_PATH = data_dir() / ".env"

ensure_data_subdirs()

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
    global CONFIG_PATH
    CONFIG_PATH = config_path()
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_config(cfg: dict[str, Any]) -> None:
    global CONFIG_PATH
    CONFIG_PATH = config_path()
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def auto_prompt_enabled() -> bool:
    """复制即弹胶囊（⌘C 监听），默认开启 —— 这是主路径。"""
    state = load_state()
    if "auto_prompt_enabled" in state:
        return bool(state["auto_prompt_enabled"])
    return True


# 主路径是「⌘C 复制 → 剪贴板监听 → 弹胶囊」（⌘C 系统先吃没法当全局 hotkey，
# 这里这个值只是文案上的"默认快捷键"，实际由 auto_prompt_enabled 触发）。
DEFAULT_INPUT_HOTKEY = "⌘C"


def hotkey_enabled() -> bool:
    """全局快捷键监听开关。默认开启用作 ⌘C 之外的备份键。"""
    return bool(load_state().get("hotkey_enabled", True))


def migrate_state_defaults() -> None:
    """默认：⌘C 复制即弹胶囊；全局 hotkey 字段记 ⌘C 仅作文案对齐。"""
    state = load_state()
    changed = False
    if "auto_prompt_enabled" not in state:
        state["auto_prompt_enabled"] = True
        changed = True
    # v3 迁移：之前曾把 auto_prompt_enabled 自动关掉，这里一次性还原
    if not state.get("_migrated_copy_v3"):
        state["auto_prompt_enabled"] = True
        state["prefer_copy_mode"] = True
        state["_migrated_copy_v3"] = True
        changed = True
    if not state.get("hotkey_enabled", True):
        state["hotkey_enabled"] = True
        changed = True
    # v4 迁移：把"备份 hotkey 字段"从 ⌘E 统一到 ⌘C，跟文案一致
    hk = dict(state.get("hotkeys") or {})
    inp = dict(hk.get("input") or {})
    if not inp.get("shortcut") or inp.get("shortcut") in ("⌃⌥E", "⇧⌘E", "⌘E"):
        inp["shortcut"] = DEFAULT_INPUT_HOTKEY
        changed = True
    inp["name"] = inp.get("name") or "弹胶囊"
    state["hotkeys"] = {"input": inp}
    if hk.get("translate") or hk.get("ask"):
        changed = True
    # v5 迁移：老用户存档里 auto_prompt_max_length=2500 把长会议转录全拦了，升到 20000
    # 只动一次，用户后来若主动改回 2500 不再覆盖
    if not state.get("_migrated_max_v2"):
        try:
            cfg = load_config()
            beh = cfg.get("behavior", {}) or {}
            if int(beh.get("auto_prompt_max_length", 0) or 0) == 2500:
                beh["auto_prompt_max_length"] = 20000
                cfg["behavior"] = beh
                save_config(cfg)
        except Exception:
            pass
        state["_migrated_max_v2"] = True
        changed = True
    if changed:
        save_state(state)


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def kb_root(cfg: dict | None = None) -> Path:
    cfg = cfg or load_config()
    return Path(os.path.expanduser(cfg["knowledge_base"]["root"])).resolve()


def get_blacklist(cfg: dict | None = None) -> list[str]:
    cfg = cfg or load_config()
    beh = cfg.get("behavior", {}) or {}
    extra = list(beh.get("skip_blacklist", []) or [])
    state = load_state()
    auto = list(state.get("skip_blacklist_auto") or state.get("skip_blacklist_extra") or [])
    manual = list(state.get("skip_blacklist_manual") or [])
    merged: list[str] = []
    for p in BUILTIN_SKIP_PATTERNS + extra + manual + auto:
        if p and p not in merged:
            merged.append(p)
    return merged


def get_dictionary() -> dict[str, list[str]]:
    """词典视图：内置 / config / manual / auto，分组返回。"""
    cfg = load_config()
    state = load_state()
    return {
        "builtin": list(BUILTIN_SKIP_PATTERNS),
        "config": list((cfg.get("behavior", {}) or {}).get("skip_blacklist") or []),
        "manual": list(state.get("skip_blacklist_manual") or []),
        "auto": list(state.get("skip_blacklist_auto") or state.get("skip_blacklist_extra") or []),
    }


def add_manual_skip(pattern: str) -> bool:
    pattern = (pattern or "").strip()
    if not pattern:
        return False
    state = load_state()
    manual: list[str] = list(state.get("skip_blacklist_manual") or [])
    if pattern in manual:
        return False
    manual.append(pattern)
    state["skip_blacklist_manual"] = manual
    save_state(state)
    return True


def remove_skip(pattern: str, *, scope: str = "manual") -> bool:
    state = load_state()
    key = "skip_blacklist_manual" if scope == "manual" else "skip_blacklist_auto"
    items: list[str] = list(state.get(key) or [])
    if pattern not in items:
        if scope == "auto" and pattern in (state.get("skip_blacklist_extra") or []):
            extras = [p for p in (state.get("skip_blacklist_extra") or []) if p != pattern]
            state["skip_blacklist_extra"] = extras
            save_state(state)
            return True
        return False
    state[key] = [p for p in items if p != pattern]
    save_state(state)
    return True


def get_hotkeys() -> dict[str, dict[str, str]]:
    state = load_state()
    hk = state.get("hotkeys") or {}
    inp = dict(hk.get("input") or {})
    default = {"name": "弹胶囊", "shortcut": DEFAULT_INPUT_HOTKEY}
    return {"input": {**default, **inp}}


def set_hotkey(key: str, *, name: str | None = None, shortcut: str | None = None) -> dict:
    from hotkey_util import normalize_hotkey

    state = load_state()
    hk = dict(state.get("hotkeys") or {})
    cur = dict(hk.get(key) or {})
    if name is not None:
        cur["name"] = name
    if shortcut is not None:
        cur["shortcut"] = normalize_hotkey(shortcut)
    hk[key] = cur
    state["hotkeys"] = hk
    save_state(state)
    return get_hotkeys()[key]


_CODE_SIGNS = [
    r"^\s*(def|class|function|const|let|var|public|private|import|from)\s+\w",
    r"^\s*(if|for|while|switch|return|try|catch|elif|else if)\s*[\(:{]",
    r"^\s*[#/]{2,}\s",
    r"^\s*(<[A-Za-z!][^>]*>|</[A-Za-z]+>)",
    r"=>\s*[\({]",
    r";\s*$",
]


def looks_like_code(text: str) -> bool:
    """启发式：复制内容像不像代码 / 长配置 / 命令。

    中文笔记里常出现：表格 `|---|`、列表 `• item`、缩进的子条目，
    这些都不算代码。判定时先看中文占比，再看代码特征。
    """
    t = text.strip()
    if not t:
        return False
    if "```" in t:
        # markdown 笔记里也常贴 ```bash 这种围栏代码块 → 看比例而非一刀切
        fenced = re.findall(r"```[\s\S]*?```", t)
        if fenced and sum(len(f) for f in fenced) / max(len(t), 1) > 0.6:
            return True
    # 中文占比 ≥ 25% → 当作中文内容（含 markdown 笔记），不再判代码
    cjk = sum(1 for c in t if "\u4e00" <= c <= "\u9fff")
    if cjk / max(len(t), 1) >= 0.25:
        return False
    lines = [ln for ln in t.splitlines() if ln.strip()]
    if len(lines) < 3:
        return False
    indented = sum(1 for ln in lines if ln.startswith((" " * 2, "\t")))
    if indented / len(lines) >= 0.65:
        return True
    hits = 0
    sample = lines[:80]
    for ln in sample:
        for pat in _CODE_SIGNS:
            try:
                if re.search(pat, ln):
                    hits += 1
                    break
            except re.error:
                continue
    return hits / max(len(sample), 1) >= 0.25


def get_behavior(cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    return cfg.get("behavior", {}) or {}


def should_skip_text(text: str, min_length: int, cfg: dict | None = None) -> bool:
    t = text.strip()
    if len(t) < min_length:
        return True

    beh = get_behavior(cfg)
    max_length = int(beh.get("auto_prompt_max_length", 0) or 0)
    if max_length > 0 and len(t) > max_length:
        return True
    if bool(beh.get("skip_code_like", True)) and looks_like_code(t):
        return True

    for pat in get_blacklist(cfg):
        try:
            if re.search(pat, t, re.IGNORECASE | re.MULTILINE):
                return True
        except re.error:
            continue
    return False


def add_to_blacklist_extra(pattern: str) -> None:
    """自动加入跳过名单（来自连续跳过等场景，标记为 auto 组）。"""
    pattern = pattern.strip()
    if not pattern:
        return
    state = load_state()
    auto: list[str] = list(state.get("skip_blacklist_auto") or state.get("skip_blacklist_extra") or [])
    if pattern not in auto:
        auto.append(pattern)
    state["skip_blacklist_auto"] = auto
    state.pop("skip_blacklist_extra", None)
    save_state(state)


def remove_from_blacklist_extra(pattern: str) -> None:
    state = load_state()
    for key in ("skip_blacklist_auto", "skip_blacklist_extra", "skip_blacklist_manual"):
        items = list(state.get(key) or [])
        if pattern in items:
            state[key] = [p for p in items if p != pattern]
    save_state(state)


def onboarding_done() -> bool:
    return bool(load_state().get("onboarding_complete"))


def _sanitize_target_rel(rel: str | None) -> str | None:
    """允许两种合法 target：
    - 相对路径：kb_root 内的相对路径，如 `daily.md` / `work/会议.md`
    - 绝对路径：kb_root 外的 `.md` 文件，如 `/Users/xxx/Desktop/temp.md`

    只过滤 AppleScript 错误返回 / 换行 / 非 .md。
    """
    if not rel:
        return None
    s = str(rel).strip()
    if not s or "button returned" in s or "text returned" in s:
        return None
    if "\n" in s:
        return None
    if not s.lower().endswith(".md"):
        return None
    return s


def resolve_target_path(rel_or_abs: str, cfg: dict | None = None) -> Path:
    """把 default_target / favorites 里的字符串解析成完整绝对 Path。

    - 以 `/` 开头 → 直接 resolve
    - 否则 → 视为 kb_root 内相对路径
    """
    s = (rel_or_abs or "").strip()
    if not s:
        raise ValueError("空 target")
    p = Path(s).expanduser()
    if p.is_absolute():
        return p.resolve()
    cfg = cfg if cfg is not None else load_config()
    return (kb_root(cfg) / p).resolve()


def display_target(rel_or_abs: str | None) -> str:
    """UI 展示用：绝对路径优先把 $HOME 替换为 ~ 让长度更友好。"""
    if not rel_or_abs:
        return ""
    s = str(rel_or_abs)
    p = Path(s).expanduser()
    if p.is_absolute():
        try:
            home = str(Path.home())
            if s.startswith(home):
                return "~" + s[len(home):]
        except Exception:
            pass
        return s
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
    state["auto_prompt_enabled"] = True
    state["hotkey_enabled"] = True
    state["prefer_copy_mode"] = True
    state["hotkeys"] = {
        "input": {"name": "弹胶囊", "shortcut": DEFAULT_INPUT_HOTKEY},
    }
    rel = _sanitize_target_rel(default_target)
    if rel:
        set_default_target(rel, state=state)
    save_state(state)


def get_capsule_size() -> tuple[int, int] | None:
    """胶囊浮层用户上次调整的尺寸；返回 (w, h) 或 None。"""
    s = load_state()
    cs = s.get("capsule_size") or {}
    try:
        w = int(cs.get("w") or 0)
        h = int(cs.get("h") or 0)
        if w >= 280 and h >= 120:
            return (w, h)
    except Exception:
        pass
    return None


def set_capsule_size(w: int, h: int) -> None:
    s = load_state()
    s["capsule_size"] = {"w": int(w), "h": int(h)}
    save_state(s)


def get_capsule_kb_enabled() -> bool:
    """胶囊「📚 笔记参考」开关。默认 False — 快是默认体验，需要 KB 时显式开。

    开启后胶囊会注入 KB 节选 + 三层档案 + 视角补充指令，prompt 体积 ~6500 字（5-8s）；
    关闭则走极速模式 prompt ~1300 字（1-3s）。
    """
    s = load_state()
    return bool(s.get("capsule_kb_enabled", False))


def set_capsule_kb_enabled(enabled: bool) -> None:
    s = load_state()
    s["capsule_kb_enabled"] = bool(enabled)
    save_state(s)


APP_THEMES = ("light", "dark")


def get_app_theme() -> str:
    """全局主题（dashboard + 胶囊共用）：light（默认）或 dark。

    向后兼容旧 key `capsule_theme`：white→light，dark→dark。
    """
    s = load_state()
    v = (s.get("app_theme") or "").strip().lower()
    if not v:
        # 兼容旧 capsule_theme
        old = (s.get("capsule_theme") or "").strip().lower()
        if old == "white":
            v = "light"
        elif old == "dark":
            v = "dark"
        else:
            v = "light"
    if v == "white":
        v = "light"
    return v if v in APP_THEMES else "light"


def set_app_theme(theme: str) -> str:
    """设置全局主题，返回归一化后的值。"""
    t = (theme or "light").strip().lower()
    if t == "white":
        t = "light"
    if t not in APP_THEMES:
        t = "light"
    s = load_state()
    s["app_theme"] = t
    s.pop("capsule_theme", None)  # 清掉旧 key，避免歧义
    save_state(s)
    return t


# —— 向后兼容（保留旧名，逐步淘汰）——
def get_capsule_theme() -> str:
    """已废弃：用 get_app_theme()。返回胶囊用 dark|white。"""
    return "dark" if get_app_theme() == "dark" else "white"


def set_capsule_theme(theme: str) -> str:
    """已废弃：用 set_app_theme()。接受 dark|white，转 app_theme。"""
    return set_app_theme("dark" if theme == "dark" else "light")


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


def _read_key_from_env_file(path: Path, var: str = "DEEPSEEK_API_KEY") -> str:
    if not path.exists():
        return ""
    prefix = f"{var}="
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(prefix):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def get_user_api_key() -> str:
    """用户自己在菜单栏 / 引导里配置的 Key（优先级最高）。"""
    key = _read_key_from_env_file(ENV_PATH)
    if key:
        return key
    return os.environ.get("DEEPSEEK_API_KEY", "").strip()


def get_platform_api_key() -> str:
    """开发者打包时内置的 Key，供所有用户免费试用（暂不投币）。"""
    try:
        from platform_crypto import read_encrypted_key
    except Exception:
        read_encrypted_key = None  # type: ignore

    enc_paths: list[Path] = []
    plain_paths: list[Path] = []
    try:
        root = resource_dir()
        enc_paths.append(root / "platform.key.enc")
        plain_paths.append(root / "platform.env")
    except Exception:
        pass
    enc_paths.append(SCRIPT_DIR / "secrets" / "platform.key.enc")
    plain_paths.append(SCRIPT_DIR / "secrets" / "platform.env")

    if read_encrypted_key:
        for p in enc_paths:
            key = read_encrypted_key(p)
            if key.startswith("sk-"):
                return key
    for p in plain_paths:
        key = _read_key_from_env_file(p)
        if key.startswith("sk-"):
            return key
    return ""


def get_api_key() -> str:
    """用户 Key > 内置平台 Key > 环境变量。"""
    user = get_user_api_key()
    if user.startswith("sk-"):
        return user
    platform = get_platform_api_key()
    if platform.startswith("sk-"):
        os.environ.setdefault("DEEPSEEK_API_KEY", platform)
        return platform
    return os.environ.get("DEEPSEEK_API_KEY", "").strip()


def has_api_key() -> bool:
    k = (get_api_key() or "").strip()
    return k.startswith("sk-") and len(k) >= 20


def api_key_status() -> dict[str, Any]:
    """给引导 / 胶囊 / 后台用的统一状态。"""
    user = (get_user_api_key() or "").strip()
    platform = (get_platform_api_key() or "").strip()
    active = (get_api_key() or "").strip()
    ok = active.startswith("sk-") and len(active) >= 10
    masked = ""
    if ok and len(active) > 10:
        masked = active[:5] + "…" + active[-4:]
    if user.startswith("sk-"):
        source = "user"
    elif platform.startswith("sk-"):
        source = "platform"
    else:
        source = "none"
    return {
        "has_key": ok,
        "masked": masked,
        "source": source,
        "platform_provided": platform.startswith("sk-"),
        "free_tier": platform.startswith("sk-") or ok,
    }


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
            "# Skillless API Key",
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
