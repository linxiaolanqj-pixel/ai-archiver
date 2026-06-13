#!/usr/bin/env python3
"""轻量胶囊浮层（Raycast 风格）：

3 个状态：
  1. Thinking 小胶囊（~160×44）出现在鼠标附近
  2. AI 完成 → 展开成「精简结果 + [精简] [复制] [归档] [⤢ 详细对比]」
  3. 用户点击操作 → 显示绿色 ✓ 反馈 → 1.5s 自动关

设计原则：
  - 不打断、不抢焦点（不调 frontmost / on_top=True 只是浮在最上不抢键盘）
  - 默认随鼠标位置；超出屏幕时贴边
  - LLM 失败时仍可点[复制]/[归档]（用原文）

CLI：
  quick_capsule.py                  默认 polish 模式，target=default
  quick_capsule.py --mode structure
  quick_capsule.py --target xx.md
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import threading
import traceback
from pathlib import Path

import webview

from app_paths import data_dir, resource_dir

SCRIPT_DIR = resource_dir()
QUICK_UI = resource_dir() / "quick"
PY = str(resource_dir() / ".venv/bin/python") if (resource_dir() / ".venv/bin/python").exists() else sys.executable
ARCHIVER_PY = resource_dir() / "archiver.py"

from history import bump_archived, record_text  # noqa: E402
from settings_util import (  # noqa: E402
    DEEPSEEK_API_KEYS_URL,
    display_target,
    api_key_status,
    get_api_key,
    has_api_key,
    get_app_theme,
    get_capsule_kb_enabled,
    get_capsule_size,
    get_default_target,
    kb_root,
    load_config,
    record_target_usage,
    resolve_target_path,
    save_api_key,
    set_capsule_kb_enabled,
    set_capsule_size,
    set_default_target,
)
# 上手引导「立即试精简」专用：不走 API，模拟流式输出
ONBOARDING_DEMO_REFINED = (
    "**顺手买 v2 灰度**\n\n"
    "- 下周三 11:00 灰度 30%（李四已确认）\n"
    "- **指标**：加购率 3% → 5%，转化率不能掉\n"
    "- **周五 18:00 前**：补埋点 `button_v2_click`（王五）\n"
    "- **分歧**：新人券方案 → 下周复盘"
)

from quick_archive import (  # noqa: E402  复用 LLM 调用 / 模式标签
    MODE_LABELS,
    _call_deepseek_stream,
    _load_env,
    _refine,
    _read_clip,
    _read_prompt,
    _resolve_target,
    _notify,
    _action_for_target,
    md_to_plain,
)
from telemetry import track as _track  # noqa: E402
from dictionary_util import (  # noqa: E402
    apply_dictionary,
    load_dictionary,
    add_entry as dict_add_entry,
    delete_entry as dict_delete_entry,
    save_dictionary,
)
from profile_util import (  # noqa: E402
    ensure_profile,
    load_profile,
    profile_dir_path,
    save_profile_part as _profile_save_part,
)
from clip_history_util import find_duplicate, append_clip  # noqa: E402
from kb_index import chunks_by_h2, bm25_search, render_top_chunks  # noqa: E402


def _capsule_size_tier(input_len: int) -> tuple[int, int, int]:
    """v0.4.16：放开主精简字数上限（用户实测原档位过紧丢信息）。

    设计取舍（产品原则「不让你多读一个字」依然成立，只是松一档）：
      - 极短（≤ 100 字）：3 条 × 30 字，总 ≤ 80 字
      - 短文（≤ 300 字）：4 条 × 40 字，总 ≤ 150 字
      - 中等（≤ 1500 字）：6 条 × 50 字，总 ≤ 280 字
      - 长文（> 1500 字）：8 条 × 55 字，总 ≤ 400 字
    总字数是「软上限」：prompt 里允许超出至多 20%，但严禁展开成步骤列表/小作文。

    视角补充段同步放开（见 CAPSULE_ASIDE_MAX = 250、≤ 3 条）。
    """
    if input_len <= 100:
        return (3, 30, 80)
    if input_len <= 300:
        return (4, 40, 150)
    if input_len <= 1500:
        return (6, 50, 280)
    return (8, 55, 400)


CAPSULE_INITIAL = (248, 60)
# 胶囊场景：截断超长输入、限制生成长度，降低首 token 与总耗时
# 1600 太短：会议转录 + 长文章经常被腰斩；4000 字 ≈ 1.5 千 tokens（中文），DeepSeek 仍能秒回
CAPSULE_INPUT_MAX = 4000
# v0.4.3：精简正文不再做字数硬限（用户实测 350 字太严丢信息），
# 视角补充 v0.4.16 放到 250 字。max_tokens 回到 800 给正文更多空间。
CAPSULE_MAX_TOKENS = 800
CAPSULE_STREAM_TIMEOUT = 60

# ==== v0.4.9 自适应延迟模式 ====
# 短输入（≤ 200 字）走极速模式：跳过 KB / profile / 视角补充指令，max_tokens 200，
# 目标 ≤ 3s 出结果。长输入走完整模式（KB + 视角补充）。
# 阈值定在 200 是因为：≤ 200 字的输入用户通常是「快速记一句话」，本来也不需要视角补充。
FAST_MODE_THRESHOLD = 200
FAST_MAX_TOKENS = 200
# ==== 字数纪律 ====
# 产品原则：
# - 精简正文：尺寸跟随原文 + AI 自判断，不做硬上限（防御性最大 1500 字，纯防 AI 失控）
# - 视角补充：硬上限 250 字 / 最多 3 条（v0.4.16 从 150/2 放开）
# 超过 → 后端 _enforce_length_limit 兜底截断 + 标题角标提示「已收短」（仅当视角补充被截）
CAPSULE_BODY_MAX = 1500   # 防御性上限，正常输出远低于此
CAPSULE_ASIDE_MAX = 250
CAPSULE_BODY_HARD = 1800
CAPSULE_ASIDE_HARD = 290
def _build_prompt_suffix(input_len: int = 500, *, aside: bool = True) -> str:
    """v0.4.12：动态生成胶囊精简 prompt 后缀。

    input_len：(压缩后)原文长度，决定条数/每条字数/总字数软上限（_capsule_size_tier）。
    aside=True：完整模式，输出结构含「--- + 视角补充」两段式（由 _build_kb_system_prompt 调用）。
    aside=False：极速模式 / 无 KB 上下文，只允许主精简，**明确禁止** `---` 与「视角补充」段
    （v0.4.11 及之前极速模式也带两段式指令，导致笔记 OFF 时模型自发输出视角补充）。
    """
    body_n, body_chars, body_total = _capsule_size_tier(input_len)
    head = (
        "\n\n"
        "============================================\n"
        "【你的任务 · 不可逾越的边界】\n"
        "============================================\n"
        "你是【改写者】，不是【回答者】。\n"
        "- 任务：把用户给你的原文「精简改写」成更短的 Markdown 笔记。\n"
        "- 原文里有问题 → 笔记里照样写成问题（“咱们对新品有什么策略？”），\n"
        "  不要给“答案”。会议里没回答的问题就是悬而未决，原样保留。\n"
        "- 原文里有讨论/争论 → 把双方观点都呈现（“A 主张 X，B 担心 Y”），\n"
        "  不要替他们下结论。\n"
        "- 原文里有未决事项 → 笔记里照样标“待定/未确认”，不要发明结论。\n"
        "- 原文没说的事不要写。你不知道的事不要补充。\n"
        "- 这是【精简改写】，不是【总结回答】、不是【答疑】、不是【分析报告】。\n"
        "- 把自己想象成一个速记员，把冗长的口水话变成结构清晰的笔记，仅此而已。\n"
        "\n【胶囊快速模式】结论前置，删口水话，输出尽量精炼；直接 Markdown 正文，不要开场白。\n"
    )
    if aside:
        structure = (
            "\n============================================\n"
            "【输出结构 · 严格执行（主精简 vs 视角补充 真分区）】\n"
            "============================================\n"
            "你的输出必须分两段。两段之间用一个独立的 `---` 行分隔（没有视角补充就不输出 `---`）：\n"
            "\n# 第一段：主精简（必填，要克制）\n"
            f"- 必须是「一句话级别的结论」或「≤ {body_n} 条要点」，每条 ≤ {body_chars} 个汉字。\n"
            "- 【绝不允许】出现：功能细节、步骤展开、待办列表、上下文交代、背景铺垫、SKU/接口/字段名、操作流程。\n"
            "  这些东西全部归“视角补充”段；主精简里**只放结论 / 决定 / 关键数字**。\n"
            "- 评判标准：用户只读主精简就能立刻知道“这条内容讲什么、要不要做什么”——做到了就够了。\n"
            "- 范例（好）：\n"
            "    - 方案可行，需评估成本\n"
            "    - 下周三 11:00 灰度 30%，转化率不能掉\n"
            "    - 三方分歧未解，下周复盘\n"
            "- 反例（不允许）：\n"
            "    ✗ 一上来罗列功能点 1/2/3 + 埋点 abc + 待办若干\n"
            "    ✗ 把整段会议按时间线缩写一遍\n"
            "    ✗ 给原文里没有的解释或推论\n"
            "\n# 第二段：视角补充（可选）\n"
            "- 主精简之后用一个独立 `---` 行分隔，然后才是视角补充。\n"
            "- 视角补充才是放展开的地方：细节、待办列表、风险提示、类比、反例、对比、对原文的延展。\n"
            "- 没东西可补就**整段省略**（连 `---` 都不输出）；宁可空着，不要硬凑。\n"
        )
    else:
        structure = (
            "\n============================================\n"
            "【输出结构 · 严格执行（极速模式：只有主精简）】\n"
            "============================================\n"
            f"只输出主精简正文（Markdown）：「一句话级别的结论」或「≤ {body_n} 条要点」，每条 ≤ {body_chars} 个汉字，"
            "**只放结论 / 决定 / 关键数字**。\n"
            "【硬禁止】以下内容一个都不准出现：\n"
            "- `---` 分隔行；「视角补充」「补充说明」「操作步骤」「下一步」之类的附加段落或标题；\n"
            "- 功能细节、步骤展开、待办列表、背景铺垫、操作流程——精简是改写不是回答，不新增原文没有的信息。\n"
        )
    discipline = (
        "\n【字数纪律 · 软上限】\n"
        f"- 主精简总字数 ≤ {body_total} 字（已按原文长度分档），最多可超出 20%，绝不允许翻倍。\n"
        f"- ≤ {body_n} 条 / 每条 ≤ {body_chars} 字；一句话能说清就不要列条。\n"
        "- 严禁把内容展开成步骤列表 / 部署清单 / 长文小作文。\n"
        "- 删口水：“以上”“仅供参考”“综上”“非常重要”“值得我们注意”这类全删。\n"
        "- 同义条目必须合并；不要把同一件事换个说法再写一遍。"
    )
    return head + structure + discipline
# 「参考知识库」上下文最大字符数。
# v0.4.14：从「尾部硬切」改成「BM25 检索 top-3 段」的总字符上限。
# 命中段总字数超过该值时按相关度顺序截断；未命中（query 为空）时退回老逻辑取尾部 N 字。
KB_CONTEXT_MAX = 2400

# (path, mtime) → list[chunk]：避免每次复制都重切大 KB。
# 单进程 / 单胶囊会话足够用，不引 functools.lru_cache 是因为 mtime 是判失效的天然 key。
_KB_CHUNK_CACHE: dict[tuple[str, float], list[dict]] = {}


def _kb_chunks_cached(p: Path) -> list[dict]:
    """读 .md 文件 → chunks_by_h2，按 (path, mtime) 缓存。"""
    try:
        st = p.stat()
        key = (str(p), st.st_mtime)
    except Exception:
        return []
    cached = _KB_CHUNK_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    chunks = chunks_by_h2(text)
    # 控制内存：缓存最多记 4 个文件（用户在多个 KB 之间切换的边界场景）
    if len(_KB_CHUNK_CACHE) >= 4:
        _KB_CHUNK_CACHE.clear()
    _KB_CHUNK_CACHE[key] = chunks
    return chunks

# —— 会议转录预处理 ——
# 检测：行里出现 H:MM / H:MM:SS 时间戳的行数 ≥ MIN_TS_LINES 且占非空行 ≥ MIN_TS_RATIO → 视为会议转录
_TS_LINE_PATTERN = re.compile(r"^.{0,40}?\d{1,2}:\d{2}(:\d{2})?\s*$")
_TS_ANY_PATTERN = re.compile(r"\d{1,2}:\d{2}(:\d{2})?")
_TS_LEAD_PATTERN = re.compile(r"^\s*\d{1,2}:\d{2}(:\d{2})?\s+")
_TS_TRAIL_PATTERN = re.compile(r"\s+\d{1,2}:\d{2}(:\d{2})?\s*$")
_TRANSCRIPT_MIN_TS_LINES = 5
_TRANSCRIPT_MIN_TS_RATIO = 0.15
# 「嗯/啊/好/对」之类纯口水短句。允许出现少量标点（拆词时清掉）。
_FILLER_WORDS = {
    "嗯", "啊", "对", "对的", "好的", "好", "OK", "ok", "Ok", "可以",
    "是的", "没问题", "嗯嗯", "好嘞", "明白", "了解", "那个", "这个",
    "嗯啊", "对对", "好好",
}
# 中文标点：判定「短行是否是发言人姓名」时用
_CJK_PUNCT_CHARS = set("，。！？；：、""''《》（）…—")

TRANSCRIPT_HINT = (
    "【输入特征】这是一段会议转录（已去噪：去时间戳、发言人前缀、合并被换行打断的句子）。"
    "\n请按「会议纪要」改写：用简洁中文还原会议里**已经发生**的事——共识、决策、提问、争论、待办、负责人、数字。"
    "\n⚠️【关键边界】会议里有人**问的问题**，纪要里就写「<谁>问了 <什么问题>」或「待定：<什么问题>」，"
    "**不要替会议给出答案**。会议里没答的就是没答，原样保留这个状态。"
    "\n你是会议速记员，不是答疑顾问。"
)


def compress_meeting_transcript(text: str) -> tuple[str, dict]:
    """检测并压缩会议转录文本。

    检测：扫描时间戳行数，≥ 5 行且占非空行 ≥ 15% 才认为是会议转录；否则原样返回，
    避免误伤普通长文（书摘、文章、Markdown 段落）。

    清洗（仅对会议转录启用）：
      1. 删除「发言人前缀+时间戳」整行（如 "闽江(会议室)(发言人2)00:00:41"）
      2. 删除行首/行末的孤立时间戳（保留正文）
      3. 删除短于 12 字 且 不含中文标点的「发言人姓名」独占行
      4. 把剩余连续非空行合并成段落（会议转录里句子常被换行打断）
      5. 删纯口水短句（"嗯/对/好的/OK" 等 ≤ 6 字）
      6. 去除相邻完全重复的段
    """
    if not text:
        return text, {"is_transcript": False}
    lines = text.splitlines()
    if not lines:
        return text, {"is_transcript": False}

    non_empty = [ln for ln in lines if ln.strip()]
    if not non_empty:
        return text, {"is_transcript": False}
    ts_count = sum(1 for ln in non_empty if _TS_ANY_PATTERN.search(ln))
    if ts_count < _TRANSCRIPT_MIN_TS_LINES:
        return text, {"is_transcript": False}
    if ts_count / max(len(non_empty), 1) < _TRANSCRIPT_MIN_TS_RATIO:
        return text, {"is_transcript": False}

    orig_len = len(text)

    cleaned: list[str] = []
    for ln in lines:
        # Step 1: 把「prefix+时间戳整行」抹成空（如"闽江(会议室)(发言人2)00:00:41"）
        new_ln = _TS_LINE_PATTERN.sub("", ln)
        if not new_ln.strip():
            cleaned.append("")
            continue
        # Step 2: 行首行尾的孤立时间戳剥掉（保留正文）
        new_ln = _TS_LEAD_PATTERN.sub("", new_ln)
        new_ln = _TS_TRAIL_PATTERN.sub("", new_ln)
        cleaned.append(new_ln)

    # Step 3: 删发言人姓名独占行（短于 12 字 且 不含中文标点）
    after_names: list[str] = []
    for ln in cleaned:
        s = ln.strip()
        if not s:
            after_names.append("")
            continue
        if len(s) < 12 and not any(c in _CJK_PUNCT_CHARS for c in s):
            continue
        after_names.append(ln)

    # Step 4: 合并连续非空行成段落（被换行打断的会议句子合回去）
    paras: list[str] = []
    buf: list[str] = []
    for ln in after_names:
        s = ln.strip()
        if not s:
            if buf:
                paras.append(" ".join(buf))
                buf = []
        else:
            buf.append(s)
    if buf:
        paras.append(" ".join(buf))

    def _is_filler(p: str) -> bool:
        # 拆词：按空格 / 中英文标点切；只剩口水词组合，且总长 ≤ 6 字 → 砍
        s = p.strip()
        if len(s) > 6:
            return False
        tokens = [t for t in re.split(r"[\s,.，。！？!?；;：:、]+", s) if t]
        if not tokens:
            return True
        return all(t in _FILLER_WORDS for t in tokens)

    paras = [p for p in paras if not _is_filler(p)]

    # Step 6: 相邻段完全重复去重（速记常误重复）
    dedup: list[str] = []
    for p in paras:
        if dedup and dedup[-1] == p:
            continue
        dedup.append(p)

    compressed = "\n\n".join(dedup).strip()
    new_len = len(compressed)
    return compressed, {
        "is_transcript": True,
        "orig_len": orig_len,
        "new_len": new_len,
        "ratio": (new_len / orig_len) if orig_len else 1.0,
    }


def _load_kb_context(target: str | None, *, query: str | None = None) -> str:
    """加载默认归档 .md 的相关片段作为 AI 精简上下文。

    v0.4.14 行为：
    - query 非空（worker 调用路径）：用 BM25 在 chunks_by_h2 切出的段里检索 top-3，
      总字符上限 KB_CONTEXT_MAX，命中段渲染时带 heading + 行号帮助 LLM 定位来源。
      若 BM25 没命中任何段（query 与 KB 完全无交集）→ 兜底走尾部切片（保持 v0.4.13 行为）。
    - query 为空（get_payload "kb 是否可用" 探测路径）：直接走尾部切片，便于前端
      显示 kb_aware 状态，不额外切段消耗。

    切段结果按 (path, mtime) 缓存，避免每次复制都重切 141KB 的大 KB。
    """
    if not target:
        return ""
    try:
        p = resolve_target_path(target, load_config())
    except Exception:
        p = Path(target)
    if not p or not p.exists() or not p.is_file():
        return ""

    if query:
        chunks = _kb_chunks_cached(p)
        if chunks:
            top = bm25_search(query, chunks, k=3, max_chars=KB_CONTEXT_MAX)
            if top:
                return render_top_chunks(top)
        # 兜底（无段或无命中）：fallthrough 到尾部切片

    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    text = text.strip()
    if not text:
        return ""
    if len(text) <= KB_CONTEXT_MAX:
        return text
    return "…（前文略）\n\n" + text[-KB_CONTEXT_MAX:]


# v0.4.15：图片缩略图（前端预览用），≤ 600 px 宽。零依赖，仅用 PyObjC 自带的 NSImage / NSBitmapImageRep
# （AppKit 模块）。失败返回 ""，前端会回退用 file://<image_path>（webview 能本地加载）。
IMAGE_THUMB_MAX_W = 600


def _make_image_thumb_b64(image_path: Path) -> str:
    try:
        from AppKit import (
            NSImage,
            NSBitmapImageRep,
            NSBitmapImageFileTypePNG,
            NSMakeSize,
        )
        from Foundation import NSData
        import base64
    except Exception:
        return ""
    try:
        data = NSData.dataWithContentsOfFile_(str(image_path))
        if data is None:
            return ""
        img = NSImage.alloc().initWithData_(data)
        if img is None:
            return ""
        size = img.size()
        w, h = float(size.width), float(size.height)
        if w <= 0 or h <= 0:
            return ""
        # 不需要缩 → 直接读原文件 bytes（仍编 base64 让前端直接 data: 嵌入，免 file:// 路径）
        if w <= IMAGE_THUMB_MAX_W:
            return base64.b64encode(bytes(data)).decode("ascii")
        scale = IMAGE_THUMB_MAX_W / w
        new_w = int(w * scale)
        new_h = int(h * scale)
        # 用 NSImage 的 best representation 缩到目标尺寸，再 PNG 编码
        thumb = NSImage.alloc().initWithSize_(NSMakeSize(new_w, new_h))
        thumb.lockFocus()
        try:
            img.drawInRect_fromRect_operation_fraction_(
                ((0, 0), (new_w, new_h)), ((0, 0), (w, h)), 1, 1.0,
            )
        finally:
            thumb.unlockFocus()
        tiff = thumb.TIFFRepresentation()
        if tiff is None:
            return ""
        rep = NSBitmapImageRep.imageRepWithData_(tiff)
        if rep is None:
            return ""
        png = rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, {})
        if png is None:
            return ""
        return base64.b64encode(bytes(png)).decode("ascii")
    except Exception:
        return ""


# 👎 反馈分类 → 累计 ≥ FEEDBACK_LESSON_THRESHOLD 次 → 自动注入下次视角补充的 system prompt。
# 加新分类时同步改：FEEDBACK_REASONS / _FEEDBACK_LESSON_RULES / _FEEDBACK_LESSON_LABEL
# 以及 capsule.html 里的 reason chip + REASON_LABEL。
FEEDBACK_REASONS = ("wrong_link", "over_inference", "stale")
FEEDBACK_LESSON_THRESHOLD = 3
FEEDBACK_LESSON_DAYS = 30

_FEEDBACK_LESSON_RULES = {
    "wrong_link": "引用 KB 时必须确认实体名（人名/项目/数字）完全一致，不一致宁可不引。",
    "over_inference": "禁止做原文没有充分依据的推断；任何「可能 / 估计 / 我觉得」必须有原文直接出处。",
    "stale": "同一实体若 KB 里有时间冲突的信息，以最近日期为准，并在批注里明示日期。",
}
_FEEDBACK_LESSON_LABEL = {
    "wrong_link": "关联错误",
    "over_inference": "过度解读",
    "stale": "过时信息",
}


def _scan_feedback_rows(*, days: int = FEEDBACK_LESSON_DAYS):
    """扫最近 N 天 kb_feedback.jsonl，yield 每条 down + 有效 reason 的行。IO 失败静默吞掉。"""
    try:
        from datetime import datetime, timedelta
        import json as _json
        path = data_dir() / "kb_feedback.jsonl"
        if not path.exists():
            return
        cutoff = datetime.now() - timedelta(days=days)
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = _json.loads(line)
                except Exception:
                    continue
                if (row.get("thumb") or "").lower() != "down":
                    continue
                reason = (row.get("reason") or "").strip().lower()
                if reason not in FEEDBACK_REASONS:
                    continue
                ts = row.get("ts") or ""
                try:
                    when = datetime.fromisoformat(ts)
                    if when < cutoff:
                        continue
                except Exception:
                    pass
                yield row
    except Exception:
        return


def _count_feedback_reason(reason: str) -> int:
    """返回某个 reason 在最近 30 天里的累计次数（含刚写入的本条）。"""
    if not reason:
        return 0
    n = 0
    for row in _scan_feedback_rows():
        if (row.get("reason") or "").strip().lower() == reason:
            n += 1
    return n


def _load_feedback_lessons() -> list[dict]:
    """聚合最近 30 天反馈，返回累计 ≥ 阈值的 reason 列表（按次数倒序）。"""
    counts: dict[str, int] = {}
    for row in _scan_feedback_rows():
        r = (row.get("reason") or "").strip().lower()
        counts[r] = counts.get(r, 0) + 1
    out = []
    for reason, n in counts.items():
        if n >= FEEDBACK_LESSON_THRESHOLD:
            out.append({
                "reason": reason,
                "count": n,
                "label": _FEEDBACK_LESSON_LABEL.get(reason, reason),
                "rule": _FEEDBACK_LESSON_RULES.get(reason, ""),
            })
    out.sort(key=lambda x: -x["count"])
    return out


def _build_feedback_lessons_block() -> str:
    """根据累积反馈生成「学到的额外约束」prompt 段。无积累则返回空串。"""
    lessons = _load_feedback_lessons()
    if not lessons:
        return ""
    rules = "\n".join(
        f"  · {l['rule']}  （你已被反馈过 {l['count']} 次「{l['label']}」）"
        for l in lessons
    )
    return (
        "\n\n# 从用户反馈中学到的额外约束（视角补充优先服从这里）\n"
        f"{rules}\n"
        "  （这些是用户多次明确指出过的不准模式，写视角补充前必须先自查这几条；"
        "和下面的拼图原则冲突时以这里为准。）"
    )


def _build_kb_system_prompt(
    base_prompt: str,
    kb_ctx: str,
    kb_label: str,
    *,
    transcript: bool = False,
    dup: dict | None = None,
    input_len: int = 500,
) -> str:
    """把基础 prompt、三层档案、拼图原则、KB 上下文拼成最终 system prompt。

    **作用域隔离（关键）**：SOUL/USER/TOOLS 三个档案文件只服务于「📚 你的视角补充」段，
    精简正文必须按 base_prompt 走，不带姿态、不模仿用户文风、不引用人设描述。

    v0.4.14 顺序重排（DeepSeek prefix cache 友好化）：
      [head: base_prompt + suffix]              ← 同 tier 下完全静态
      [boundary_decl]                            ← 完全静态
      [profile_block: SOUL/USER/TOOLS]           ← 启动期内基本静态（用户改档案前不变）
      [aside_block: 拼图原则 / 示范 / 禁词]      ← 完全静态
      [lessons_block: 反馈学习注入]              ← 跨会话稳定，仅累积变化
      [dup_block: 剪贴板重复警告]                ← 偶尔变（命中重复时才有）
      [kb_block: KB 上下文 BM25 节选]            ← 每次都变（query 不同 → 检索结果不同）

    把所有静态 / 半静态内容前置，让 DeepSeek 的 disk-based prefix cache（命中条件：
    公共前缀 byte-by-byte 相同 ≥ 64 tokens）尽量在长 prefix 上命中；命中后 input
    token 单价 0.26×，TTFB 也大幅下降。

    纯精简模式（kb_ctx 为空）→ 直接返回 base_prompt + 无视角补充版后缀（aside=False），
    **完全不注入档案**；没有 KB 时视角补充本来就不存在，不该让模型输出 `---` 段。
    """
    head = base_prompt + _build_prompt_suffix(input_len, aside=bool(kb_ctx))
    # 会议转录：在 prompt 顶部加一段「按会议纪要角度精简」的提示。
    # 放最前面让模型最先看到这个语境，再读下面的精简规则，更不容易逐字复述。
    if transcript:
        head = TRANSCRIPT_HINT + "\n\n" + head

    # ----- 纯精简模式：没有 KB 上下文 → 不注入任何档案；走老逻辑 -----
    # 没设默认归档目标 / 默认文档不存在时 kb_ctx 为空；这时整段视角补充本来也不存在，
    # 也就没必要让 SOUL/USER/TOOLS 污染精简正文。
    if not kb_ctx:
        return head

    # ----- KB 节选（v0.4.14：BM25 检索 top-3 段，放在 prompt 末尾） -----
    # 用途收紧到「视角补充段引用事实」，不再宣称用于精简正文术语对齐
    # —— 因为它现在每次都变（query 不同 → BM25 命中段不同），放末尾才能让前面更长的
    # prefix 稳定命中 cache。术语对齐能力让位给整体延迟优化。
    kb_block = (
        "\n\n# 这次的笔记上下文（BM25 节选自「{label}」)\n"
        "用途：写视角补充段时引用笔记里的事实做因果链；不要把笔记原文抄进精简正文。\n"
        "```markdown\n{ctx}\n```"
    ).format(label=kb_label, ctx=kb_ctx)

    # ----- 边界声明：把后续 5 个 block（profile/aside/lessons/dup/kb）的作用域圈定 -----
    # v0.4.14：从「KB 在前 / boundary 在中」改成「boundary 在前 / KB 在尾」之后，
    # 必须在 boundary 里把末尾的 KB 也声明为「只用于视角补充段」，否则会和 KB block 内
    # 自带的「精简正文术语对齐」用途打架（这里同步收紧 KB 用途）。
    boundary_decl = (
        "\n\n────────────────────────────────────────\n"
        "⚠️ 以下系统信息【仅用于视角补充段（`---` 后面的「📚 你的视角补充」)】\n"
        "────────────────────────────────────────\n"
        "**精简正文必须按上面的「基础精简规则 + 字数纪律」严格执行**：\n"
        "  · 精简正文不带姿态、不模仿用户文风、不引用下面的人设描述、不把下面的档案/笔记内容写进正文\n"
        "  · 精简正文里不要出现 SOUL.md/USER.md/TOOLS.md 里的口头禅、人物画像、项目术语解释\n"
        "  · 末尾的「这次的笔记上下文」只用于视角补充段引用事实做因果链，不要把笔记原文抄进精简正文\n"
        "  · 下面这块（人格档案 / 视角补充指令 / 反馈教训 / 重复输入提醒 / 笔记上下文），\n"
        "    **整体只在 `---` 之后的「📚 你的视角补充」区块里启用**\n"
        "  · 如果本次没有写视角补充（拼不出因果链），就当下面这块不存在\n"
        "────────────────────────────────────────"
    )

    # ----- 三层档案 -----
    try:
        prof = load_profile()
    except Exception:
        prof = {"soul": "", "user": "", "tools": ""}
    soul_text = (prof.get("soul") or "").strip()
    user_text = (prof.get("user") or "").strip()
    tools_text = (prof.get("tools") or "").strip()
    profile_block = (
        "\n\n# Skillless 是谁（只在写视角补充时启用这个人格；精简正文里禁止套用）\n"
        f"{soul_text or '（用户尚未填写 SOUL.md）'}\n\n"
        "# 关于这个人（只在写视角补充时参考；精简正文里禁止引用人物画像）\n"
        f"{user_text or '（用户尚未填写 USER.md）'}\n\n"
        "# 项目 / 术语 / 人（只在写视角补充时参考；精简正文里禁止解释术语）\n"
        f"{tools_text or '（用户尚未填写 TOOLS.md）'}"
    )

    # ----- 重复输入提醒（只在 dup 命中时注入；位置在视角补充指令之前） -----
    dup_block = ""
    if dup:
        match_word = "完全一样的" if dup.get("match") == "exact" else "几乎一样的"
        human_ago = dup.get("human_ago") or "刚刚"
        prev_head = (dup.get("preview") or "").strip().replace("\n", " ")
        dup_block = (
            "\n\n【重复输入提醒】（这次的输入和过往复制有重复）\n"
            f"- 用户在 {human_ago} 复制过{match_word}内容\n"
            f"- 上次的开头：「{prev_head}…」\n"
            "- 你的任务变化：\n"
            "  · 精简正文还是认真做（用户可能就是想重新精简一份）\n"
            "  · 视角补充段【开头加一句吐槽】，一句话、≤ 30 字，"
            "像懂用户的同事看了又看会说的那种\n"
            "  · 吐槽示例（学姿态、不要照抄；time 替换成上面那个具体时间）：\n"
            f"    - \"这段你 {human_ago}刚精简过——还是同一个建议\"\n"
            "    - \"连标点都没改一个，是想我重看一遍？\"\n"
            f"    - \"你又来了，{human_ago}刚跑过这段\"\n"
            "  · 吐槽完接一行空，再写正常的视角补充"
            "（仍守 ≤ 200 字 / ≤ 3 条 / 每条带来源标注）\n"
            "- 禁忌：不要刻薄、不要\"哈哈\"、不要 emoji 满天飞、不要\"非常抱歉\"。"
            "就是同事日常那种轻吐槽。"
        )

    # 视角补充指令：精简版（v0.4.6 大瘦身，从 ~1700 字 → ~550 字）
    # 保留：拼图三件套（新输入事实 + 笔记事实 + 因果链）/ 字数硬限 / 1 个示范 / 2 条反例 / 禁词。
    # 删掉：第 2/3 个示范、第 3/4 条反例、「收尾再强调一次」整段（前面已说过）、写法 8 条压到 5 条。
    aside_block = (
        "\n\n# 视角补充怎么写（仅对 `---` 后的段落生效）\n"
        "\n【拼图原则】把笔记碎片 + 本次输入用**显式因果链**串起来还给用户。"
        "你不创造知识，只把碎片按形状拼好。\n"
        "\n每条必须包含三件事（缺一不写）：\n"
        "  · 📌 本次输入的一个具体事实\n"
        "  · 📚 KB 节选里的一个相关事实，用「依据：「<小节/日期>」」标出处\n"
        "  · 🔗 把两者用因果串起来：所以X / 等于复用Y / 和Z矛盾 / 漏了W回旋镖\n"
        "\n示范：\n"
        "  ✓ 你这次提的【方案 A】，跟笔记 4/15【方案 A 试点 +6% 订单】"
        "（依据：「## 4/15 数据回顾」）一个套路 → 效率证明可以直接搬。\n"
        "\n反例：\n"
        "  ✗ 「建议关注产品独立性」← AI 助手腔，没事实没因果\n"
        "  ✗ 「这次方案和上次有关联」← 只说有关联，没说怎么关联\n"
        "\n硬要求：\n"
        "  1. 【字数·死命令】整段 ≤ 250 汉字，最多 3 条；超就砍最弱那条，宁缺毋滥。\n"
        "  2. 每条结尾必须有「依据：「...」」。\n"
        "  3. 找不到 KB 事实 / 拼不出因果链 → 那条不写；整段都拼不出 → `---` 段一字不写。\n"
        "  4. 第二人称「你」直接对话；不要总结口吻。\n"
        "  5. 禁词：建议关注 / 值得思考 / 或许可以 / 经过分析 / 综上 / 仅供参考 / 有一定。\n"
        "\n输出格式：正文 Markdown → 有批注就加 `---` → 下面：\n"
        "```\n---\n### 📚 你的视角补充\n<≤ 250 字、≤ 3 条拼好的因果链>\n```\n"
        "\n【疑似拼写 · 可选】KB 里反复出现的人名/产品/缩写视为权威拼写；"
        "本次输入若有近似不同的写法（同音/形近/错别字），写独立一行：\n"
        "  💡 疑似拼写：<本次写法> → <KB 写法>\n"
        "最多 3 行，写在视角补充区块末尾，不确定就不写。"
    )

    lessons_block = _build_feedback_lessons_block()
    # v0.4.14：顺序按「稳定性递减」排，前缀越长的部分越稳定 → cache 命中段最大化
    # 静态: head, boundary, aside  (启动期完全不变)
    # 半静态: profile (用户改档案前不变), lessons (累积变化, 阈值触发新增)
    # 动态: dup (本次复制是否撞重复), kb (BM25 结果随每次输入变)
    return (
        head
        + boundary_decl
        + profile_block
        + aside_block
        + lessons_block
        + dup_block
        + kb_block
    )


def _smart_truncate(text: str, max_chars: int) -> str:
    """优先在自然边界（段落 / 句子 / 标点）截断，最差才硬切。"""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    # 从最不破坏到最破坏的边界顺序尝试
    for sep in ("\n\n", "\n", "。", "！", "？", "；", "…"):
        idx = cut.rfind(sep)
        # 截点不能太靠前（最多砍 30%），否则信息丢太多 → 退而求其次硬切
        if idx > max_chars * 0.7:
            return cut[: idx + len(sep)].rstrip() + "\n\n…"
    return cut.rstrip() + "…"


def _enforce_length_limit(text: str) -> tuple[str, dict]:
    """字数兜底：

    - **精简正文**不做硬限（让 AI 按信息密度自由发挥）。仅当超出 CAPSULE_BODY_HARD
      这个防御性上限（1800 字，正常远不会触达）才截断，防止 AI 失控写小作文。
    - **视角补充**保持硬限 ≤ CAPSULE_ASIDE_MAX（250 字，v0.4.16 从 150 放开）。

    返回 (新文本, info)；info["any"] 决定标题是否显示「已收短」角标。
    """
    info = {"body_cut": False, "aside_cut": False, "body_was": 0, "aside_was": 0, "any": False}
    if not text:
        return text, info
    raw = text.strip()
    parts = re.split(r"\n-{3,}\s*\n", raw, maxsplit=1)
    body = parts[0].rstrip()
    aside = parts[1].strip() if len(parts) > 1 else ""

    info["body_was"] = len(body)
    # 正文：仅在远超防御性上限时才截断（正常 AI 不会触发）
    if len(body) > CAPSULE_BODY_HARD:
        body = _smart_truncate(body, CAPSULE_BODY_MAX)
        info["body_cut"] = True

    if aside:
        info["aside_was"] = len(aside)
        # 视角补充：守住 250 字硬限（v0.4.16）
        if len(aside) > CAPSULE_ASIDE_HARD:
            aside = _smart_truncate(aside, CAPSULE_ASIDE_MAX)
            info["aside_cut"] = True
        result = body + "\n\n---\n\n" + aside
    else:
        result = body

    info["any"] = info["body_cut"] or info["aside_cut"]
    return result, info


def _mouse_anchor(window_size: tuple[int, int]) -> tuple[int, int]:
    """根据鼠标位置算窗口左上角坐标，预留展开后高度避免被屏幕底部裁掉。"""
    try:
        from AppKit import NSEvent, NSScreen
    except Exception:
        return (100, 100)

    try:
        mouse = NSEvent.mouseLocation()
        screen = NSScreen.mainScreen().frame()
        screen_w = int(screen.size.width)
        screen_h = int(screen.size.height)
        mx = int(mouse.x)
        my_from_bottom = int(mouse.y)
        my_from_top = screen_h - my_from_bottom

        w, h = window_size
        # 按"展开后"的常见尺寸预留空间：胶囊会从 248×60 长到 ~700×380
        # 不预留宽度会导致首次展开时 resize_to 把窗口从右边推到左边（用户体验上"飞走了"）
        EXPECTED_EXPANDED_W = 720
        EXPECTED_EXPANDED_H = 380
        x = mx - w // 2 + 30
        y = my_from_top + 18
        x = max(8, min(x, screen_w - EXPECTED_EXPANDED_W - 8))
        y = max(8, min(y, screen_h - EXPECTED_EXPANDED_H - 8))
        return (x, y)
    except Exception:
        return (100, 100)


class CapsuleApi:
    def __init__(
        self,
        text: str,
        target: str,
        mode: str,
        *,
        demo: bool = False,
        image_path: str = "",
    ) -> None:
        self.text = text
        self.target = target
        # v0.4.15 图片即附件归档：mode == "image" 时不调 AI / 不切原文，
        # 仅展示预览 + 用户拍板调 archive_image() 落盘
        if image_path:
            self.mode = "image"
            self.image_path = image_path
        else:
            self.mode = mode if mode in MODE_LABELS else "polish"
            self.image_path = ""
        self.demo = demo
        self.refined = ""
        self.done = False
        # 硬词典替换命中（路线 A）：worker 里跑 apply_dictionary 后赋值
        self.dict_hits: list[dict] = []
        # 会议转录预处理（路线 E）：检测一次，下游 worker 和 get_payload 都读这里
        try:
            compressed, info = compress_meeting_transcript(text or "")
        except Exception:
            compressed, info = (text or "", {"is_transcript": False})
        if info.get("is_transcript"):
            self.transcript_info: dict = info
            self._compressed_text = compressed
        else:
            self.transcript_info = {}
            self._compressed_text = (text or "").strip()
        self._cur_w = 0
        self._cur_h = 0
        self._cur_x = 0
        self._cur_y = 0
        # 流式状态：{text, done, ok, mode, seq}
        self._stream_lock = threading.Lock()
        self._stream = {"text": "", "done": True, "ok": True, "mode": "", "seq": 0}
        self._stream_thread: threading.Thread | None = None
        # 重复复制检测（同事级吐槽）：worker 启动时基于「原始 user_text」算
        # （不能用压缩后的，否则会议转录被压缩后哈希就漂走了）
        self.dup_info: dict | None = None
        # 性能 timing：每一次 refine 在 worker 里写，前端读 timings.first/total 显示
        # · build_ms: 从 worker 启动到 prompt 构建完（含 KB / dup / dict 等本地处理）
        # · first_ms: 从 worker 启动到 DeepSeek 吐出第一个 chunk（首 token 延迟）
        # · total_ms: 从 worker 启动到 stream 完全结束
        # · prompt_chars / input_chars: 实际发给 DeepSeek 的字符量（瓶颈定位）
        self.timings: dict = {}
        # v0.4.10：「📚 笔记参考」开关，默认 OFF（state.json 持久化跨胶囊会话）
        self.kb_enabled: bool = get_capsule_kb_enabled()

    def get_payload(self) -> dict:
        if self.mode == "image":
            return self._get_image_payload()
        body = self.text.rstrip()
        saved = get_capsule_size()
        _track("view", "opened", scope="capsule",
               props={"mode": self.mode, "len": len(body), "target": Path(self.target).name if self.target else ""})
        st = api_key_status()
        kb_ctx = _load_kb_context(self.target)
        return {
            "kb_aware": bool(kb_ctx),
            "kb_label": Path(self.target).stem if self.target else "",
            "text": body,
            "len": len(body),
            "target_label": Path(self.target).name if self.target else "未设置默认文档",
            "target_display": display_target(self.target),
            "target": self.target or "",
            "mode": self.mode,
            "mode_label": MODE_LABELS.get(self.mode, self.mode),
            "modes": [{"id": k, "label": v} for k, v in MODE_LABELS.items()],
            "saved_size": list(saved) if saved else None,
            "theme": "dark" if get_app_theme() == "dark" else "white",
            "demo": self.demo,
            "has_key": st.get("has_key", False),
            "platform_provided": st.get("platform_provided", False),
            "api_keys_url": DEEPSEEK_API_KEYS_URL,
            "dict_hits": getattr(self, "dict_hits", []),
            "transcript_info": getattr(self, "transcript_info", {}) or {},
            "dup_info": getattr(self, "dup_info", None),
            "kb_enabled": bool(getattr(self, "kb_enabled", False)),
        }

    def _get_image_payload(self) -> dict:
        """v0.4.15：图片预览模式（不调 AI），前端只渲染图 + 元数据 + 两个 action。

        额外字段：
          - mode="image"：前端走完全独立的模板分支
          - image_size_bytes：原图字节，前端展示「1.2 MB」
          - image_thumb_b64：缩略图 base64 PNG（≤ 600px 宽，PyObjC NSImage 自带缩，零依赖）；
            缩失败就直接 file:// 给前端（webview 能本地加载）
          - planned_rel：拟保存的 attachments/ 相对路径（前端展示用，archive 时再算一次防漂移）
        """
        from datetime import datetime
        size = 0
        thumb_b64 = ""
        try:
            p = Path(self.image_path)
            if p.exists():
                size = p.stat().st_size
                thumb_b64 = _make_image_thumb_b64(p)
        except Exception:
            pass
        stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        planned_rel = f"attachments/{stamp}.png"
        saved = get_capsule_size()
        _track("view", "opened", scope="capsule",
               props={"mode": "image", "size": size,
                      "target": Path(self.target).name if self.target else ""})
        return {
            "mode": "image",
            "image_path": self.image_path,
            "image_size_bytes": size,
            "image_thumb_b64": thumb_b64,
            "planned_rel": planned_rel,
            "target_label": Path(self.target).name if self.target else "未设置默认文档",
            "target_display": display_target(self.target),
            "target": self.target or "",
            "saved_size": list(saved) if saved else None,
            "theme": "dark" if get_app_theme() == "dark" else "white",
            # 文本路径里这些字段前端会读，给空值占位避免 JS 误访问
            "kb_aware": False,
            "kb_label": "",
            "kb_enabled": False,
            "dict_hits": [],
            "transcript_info": {},
            "dup_info": None,
            "has_key": True,  # 图片不调 AI，跳过「填 Key」面板
        }

    def get_api_status(self) -> dict:
        return {"ok": True, **api_key_status()}

    def save_api(self, key: str) -> dict:
        k = (key or "").strip()
        if not k.startswith("sk-"):
            return {"ok": False, "error": "Key 应以 sk- 开头"}
        if len(k) < 20:
            return {"ok": False, "error": "Key 太短，请粘贴完整 Key"}
        try:
            save_api_key(k)
            _load_env()
            _track("click", "save_api_key", scope="capsule")
            return {"ok": True, "masked": k[:5] + "…" + k[-4:]}
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}

    def open_api_keys_page(self) -> dict:
        try:
            subprocess.run(["open", DEEPSEEK_API_KEYS_URL], check=False)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}

    def toggle_kb(self, enabled: bool | None = None) -> dict:
        """切换「📚 笔记参考」开关并持久化到 state.json。
        enabled=None → 翻转当前值；否则按传入值设。
        """
        if enabled is None:
            new_val = not bool(getattr(self, "kb_enabled", False))
        else:
            new_val = bool(enabled)
        self.kb_enabled = new_val
        try:
            set_capsule_kb_enabled(new_val)
        except Exception:
            pass
        _track("click", "toggle_kb", scope="capsule", props={"enabled": new_val})
        return {"ok": True, "kb_enabled": new_val}

    def mark_kb_feedback(self, thumb: str, reason: str = "", note: str = "") -> dict:
        """胶囊里点 👍/👎 → 写入 kb_feedback.jsonl，并把累计次数返回给前端。

        reason ∈ {"wrong_link", "over_inference", "stale", ""}（仅 down 时有意义）。
        累计达到阈值后，prompt 会自动注入对应硬约束（见 _build_feedback_lessons_block）。
        """
        try:
            from datetime import datetime
            import json as _json
            import hashlib
            thumb = (thumb or "").strip().lower()
            if thumb not in ("up", "down"):
                return {"ok": False, "error": "thumb 应为 up / down"}
            reason = (reason or "").strip().lower()
            if reason and reason not in FEEDBACK_REASONS:
                reason = ""
            input_hash = hashlib.sha1((self.text or "").encode("utf-8")).hexdigest()[:10]
            refined_hash = hashlib.sha1((self.refined or "").encode("utf-8")).hexdigest()[:10]
            row = {
                "ts": datetime.now().isoformat(timespec="seconds"),
                "target": Path(self.target).name if self.target else "",
                "mode": self.mode,
                "thumb": thumb,
                "reason": reason,
                "note": (note or "")[:200],
                "input_len": len(self.text or ""),
                "refined_len": len(self.refined or ""),
                "input_hash": input_hash,
                "refined_hash": refined_hash,
            }
            (data_dir() / "kb_feedback.jsonl").open("a", encoding="utf-8").write(
                _json.dumps(row, ensure_ascii=False) + "\n"
            )
            _track("click", "kb_feedback", scope="capsule",
                   props={"thumb": thumb, "reason": reason or "none"})
            # 同步算出当前 reason 的累计次数（含本条），给前端显示「累计 N 次」+「已学习」
            reason_count = 0
            if thumb == "down" and reason:
                reason_count = _count_feedback_reason(reason)
            return {"ok": True, "reason_count": reason_count}
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}

    def open_dashboard(self) -> dict:
        """胶囊里点齿轮 → 拉起后台窗口（菜单栏不在也能用）。"""
        try:
            from bootkit import child_cmd
            subprocess.Popen(
                child_cmd("dashboard"),
                cwd=str(data_dir()),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            _track("click", "open_dashboard", scope="capsule")
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}

    def get_dictionary(self) -> dict:
        """前端读取当前纠错词典（路线 A）。"""
        try:
            return load_dictionary()
        except Exception:
            return {"entries": []}

    def add_dictionary_entry(self, wrong: str, right: str, source: str = "manual") -> dict:
        """写入纠错词典。
        source="auto" 用于 AI 检测疑似拼写后的自动学习；source="manual" 用于用户手动添加。
        """
        ctx = Path(self.target).name if self.target else ""
        try:
            r = dict_add_entry(wrong, right, ctx=ctx, source=source)
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}
        kind = "auto" if source == "auto" else "click"
        _track(kind, "dict_add", scope="capsule",
               props={"ok": bool(r.get("ok")), "source": source})
        return r

    def delete_dictionary_entry(self, wrong: str) -> dict:
        """前端删除某个词条。"""
        try:
            r = dict_delete_entry(wrong)
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}
        _track("click", "dict_del", scope="capsule",
               props={"ok": bool(r.get("ok"))})
        return r

    # —— 三层档案（SOUL / USER / TOOLS）——
    def get_profile(self) -> dict:
        """读取三层档案；前端展示用。"""
        try:
            return load_profile()
        except Exception:
            return {"soul": "", "user": "", "tools": ""}

    def save_profile_part(self, kind: str, content: str) -> dict:
        """写入某一份档案（kind 只能是 soul|user|tools）。"""
        try:
            r = _profile_save_part(kind, content)
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}
        _track("click", "save_profile", scope="capsule",
               props={"kind": kind, "ok": bool(r.get("ok"))})
        return r

    def open_profile_dir(self) -> dict:
        """在 Finder 中打开 profile 目录（用户能直接看到三个 .md）。"""
        try:
            subprocess.Popen(["open", profile_dir_path()])
            _track("click", "open_profile_dir", scope="capsule")
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}

    def resize_to(self, w: int, h: int) -> dict:
        """前端拖拽 / autofit 时实时调用。若窗口底部超出屏幕则自动上移。

        注意：NSWindow 操作必须在主线程，这里只能用 pywebview 的 win.resize/move，
        它们内部已 dispatch 到主线程；切勿直接调 native.setFrame_*（会 SIGTRAP）。
        """
        w = max(200, int(w))
        h = max(60, int(h))

        new_x: int | None = None
        new_y: int | None = None
        # 实时从 NSWindow.frame() 读出来的位置，用作 move 的 fallback。
        # 之前用 self._cur_x 的 fallback：init 时是 0、且只在水平溢出路径里更新，
        # 一旦只发生垂直溢出，会把窗口强行 move 到 (0, new_y) —— 从右"瞬移到左"。
        real_x: int | None = None
        real_top_y: int | None = None
        try:
            from AppKit import NSScreen  # type: ignore
            screen = NSScreen.mainScreen().frame()
            screen_w = int(screen.size.width)
            screen_h = int(screen.size.height)
            for win in webview.windows:
                native = getattr(win, "native", None)
                if native is not None:
                    frame = native.frame()
                    real_x = int(frame.origin.x)
                    real_top_y = int(screen_h - frame.origin.y - frame.size.height)
                    # 只有"真的"超出屏幕（>0 像素溢出）才推；预留 8 像素时不推，
                    # 否则用户从右上角展开，会被一路推到屏幕中间，看着像"飞到左边"
                    if real_x + w > screen_w:
                        new_x = max(8, screen_w - w - 8)
                    if real_top_y + h > screen_h:
                        new_y = max(8, screen_h - h - 8)
                    break
        except Exception:
            pass

        try:
            for win in webview.windows:
                if new_x is not None or new_y is not None:
                    # 关键：fallback 必须用实时 frame 读到的 real_x/real_top_y，
                    # 不能用 self._cur_x（可能从未被赋值过）。这就是历史上"垂直溢出
                    # 时窗口从右瞬移到左"的根本原因。
                    fx = new_x if new_x is not None else (real_x if real_x is not None else self._cur_x)
                    fy = new_y if new_y is not None else (real_top_y if real_top_y is not None else self._cur_y)
                    try:
                        win.move(int(fx), int(fy))
                        self._cur_x = int(fx)
                        self._cur_y = int(fy)
                    except Exception:
                        pass
                win.resize(w, h)
                break
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}
        self._cur_w = w
        self._cur_h = h
        return {"ok": True, "w": w, "h": h}

    def move_and_resize(self, x: int, y: int, w: int, h: int) -> dict:
        """拖左/上/左上/左下/右上边或角时使用：原子地同时改窗口位置 + 大小。

        关键：直接调 Cocoa `setFrame_display_animate_` 把 origin 和 size 一次性更新，
        避免 pywebview 的 win.move() + win.resize() 两步带来的视觉闪烁。
        """
        w = max(280, int(w))
        h = max(120, int(h))
        x = int(x)
        y = int(y)
        ok_native = False
        try:
            from AppKit import NSMakeRect, NSScreen  # type: ignore
            for win in webview.windows:
                native = getattr(win, "native", None)
                if native is not None:
                    screen_h = int(NSScreen.mainScreen().frame().size.height)
                    # JS / pywebview create_window 用 top-left + y 向下；
                    # Cocoa setFrame 用 bottom-left + y 向上，需翻转
                    cocoa_y = screen_h - y - h
                    rect = NSMakeRect(x, cocoa_y, w, h)
                    native.setFrame_display_animate_(rect, False, False)
                    ok_native = True
                break
        except Exception:
            ok_native = False

        if not ok_native:
            # fallback：pywebview 通用 API
            try:
                for win in webview.windows:
                    try:
                        win.move(x, y)
                    except Exception:
                        pass
                    win.resize(w, h)
                    break
            except Exception as e:
                return {"ok": False, "error": str(e)[:120]}

        self._cur_w = w
        self._cur_h = h
        self._cur_x = x
        self._cur_y = y
        return {"ok": True, "x": x, "y": y, "w": w, "h": h}

    def get_position(self) -> dict:
        """返回当前窗口在屏幕上的真实坐标（top-left 原点，y 向下）。

        JS 拖拽开始时调一次，避免用 `e.screenX - e.clientX` 这种不可靠的算法。
        """
        try:
            from AppKit import NSScreen  # type: ignore
            for win in webview.windows:
                native = getattr(win, "native", None)
                if native is None:
                    break
                frame = native.frame()
                screen_h = int(NSScreen.mainScreen().frame().size.height)
                top_y = int(screen_h - frame.origin.y - frame.size.height)
                return {
                    "ok": True,
                    "x": int(frame.origin.x),
                    "y": top_y,
                    "w": int(frame.size.width),
                    "h": int(frame.size.height),
                }
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}
        return {"ok": False, "error": "no window"}

    def save_size(self) -> dict:
        """拖拽结束后保存到 .state.json，下次启动恢复。"""
        if self._cur_w and self._cur_h:
            try:
                set_capsule_size(self._cur_w, self._cur_h)
            except Exception as e:
                return {"ok": False, "error": str(e)[:120]}
        return {"ok": True}

    def refine(self, mode: str | None = None) -> dict:
        """同步整理（保留兜底；正常路径用 start_refine 流式）。"""
        m = mode or self.mode
        if m not in MODE_LABELS:
            m = "polish"
        self.mode = m
        if m == "raw":
            self.refined = self.text.strip()
            return {"ok": True, "body": self.refined, "mode": m}
        ok, body = _refine(self.text, m)
        if ok:
            self.refined = body
        return {"ok": ok, "body": body, "mode": m}

    def _start_demo_refine(self, m: str) -> dict:
        """引导演示：用预制精简结果模拟流式输出，无需 API Key。"""
        import time

        demo_text = ONBOARDING_DEMO_REFINED
        self.mode = m
        with self._stream_lock:
            self._stream = {"text": "", "done": False, "ok": True, "mode": m, "seq": 0}

        def worker() -> None:
            acc = ""
            step = max(1, len(demo_text) // 24)
            for i, ch in enumerate(demo_text):
                acc += ch
                if i % step == 0 or i == len(demo_text) - 1:
                    with self._stream_lock:
                        self._stream["text"] = acc
                        self._stream["seq"] += 1
                    time.sleep(0.03)
            with self._stream_lock:
                self._stream["text"] = demo_text
                self._stream["done"] = True
                self._stream["seq"] += 1
            self.refined = demo_text

        self._stream_thread = threading.Thread(target=worker, daemon=True)
        self._stream_thread.start()
        return {"ok": True, "mode": m, "demo": True}

    def start_refine(self, mode: str | None = None) -> dict:
        """启动流式 LLM；前端调 get_progress 轮询读 chunk。"""
        # v0.4.15：图片模式不调 AI，直接 short-circuit
        if self.mode == "image":
            return {"ok": False, "mode": "image", "error": "image mode skips refine"}
        m = mode or self.mode
        if m not in MODE_LABELS:
            m = "polish"
        self.mode = m
        _track("click", "refine", scope="capsule", props={"mode": m, "len": len(self.text)})

        if self.demo:
            return self._start_demo_refine(m)

        if not has_api_key():
            with self._stream_lock:
                self._stream = {
                    "text": "NO_API_KEY",
                    "done": True,
                    "ok": False,
                    "mode": m,
                    "seq": 1,
                }
            return {"ok": True, "mode": m, "need_key": True}

        with self._stream_lock:
            self._stream = {"text": "", "done": False, "ok": True, "mode": m, "seq": 0}

        if m == "raw":
            with self._stream_lock:
                self._stream["text"] = self.text.strip()
                self._stream["done"] = True
                self._stream["seq"] = 1
            self.refined = self.text.strip()
            return {"ok": True, "mode": m}

        def worker() -> None:
            import time as _time
            t0 = _time.monotonic()
            self.timings = {}
            try:
                # 连接阶段由前端小药丸 thinking 展示，不向结果区推送占位文案
                base_prompt = _read_prompt(m) or "请把用户的原文整理成清晰的 Markdown 笔记。"
                is_transcript = bool(self.transcript_info.get("is_transcript"))
                # 重复输入检测：基于「原始 self.text」（未压缩、未截断），
                # 否则会议转录被预处理后哈希就跟历史记录对不上了。
                # 任何异常都吞掉，绝不阻断主流程。
                try:
                    self.dup_info = find_duplicate(self.text or "")
                except Exception:
                    self.dup_info = None

                # v0.4.10：是否走完整（KB + 视角补充）由两件事决定：
                # 1. 用户是否在胶囊里显式开了「📚 笔记参考」开关（self.kb_enabled，主导）
                # 2. 输入是否够长（≤ 200 字时 KB 帮助极小，强制走极速避免冗余 token）
                # `_compressed_text` 是 compress_meeting_transcript 处理后的净文本
                eff_text = self._compressed_text or self.text.strip()
                kb_on = bool(getattr(self, "kb_enabled", False))
                short_input = len(eff_text) <= FAST_MODE_THRESHOLD
                fast_mode = (not kb_on) or short_input
                if fast_mode:
                    # 极速模式：aside=False → 不教模型两段式，并硬禁止 `---` 与「视角补充」段
                    sys_prompt = base_prompt + _build_prompt_suffix(len(eff_text), aside=False)
                    max_tok = FAST_MAX_TOKENS
                else:
                    # v0.4.14：把本次（压缩后的）输入当 BM25 query 检索 KB top-3 段，
                    # 替代「取尾部 2400 字」。命中精度大幅高于尾部，检索结果放到 prompt 末尾
                    # 不影响前缀 cache 命中。
                    kb_ctx = _load_kb_context(self.target, query=eff_text)
                    kb_label = Path(self.target).stem if self.target else "笔记"
                    sys_prompt = _build_kb_system_prompt(
                        base_prompt, kb_ctx, kb_label,
                        transcript=is_transcript,
                        dup=self.dup_info,
                        input_len=len(eff_text),
                    )
                    max_tok = CAPSULE_MAX_TOKENS
                self.timings["mode"] = "fast" if fast_mode else "full"
                self.timings["kb_enabled"] = kb_on
                self.timings["build_ms"] = int((_time.monotonic() - t0) * 1000)
                self.timings["prompt_chars"] = len(sys_prompt)
                # __init__ 里已经跑过 compress_meeting_transcript：
                # - 会议转录 → _compressed_text 是压缩后的纯文本（通常比原文短 60%+）
                # - 普通长文 → _compressed_text 就是 self.text.strip()，未做任何改动
                user_text = self._compressed_text or self.text.strip()
                orig_input_len = len(self.text.strip())
                if len(user_text) > CAPSULE_INPUT_MAX:
                    user_text = user_text[:CAPSULE_INPUT_MAX] + (
                        f"\n\n…（原文 {orig_input_len} 字，胶囊只能处理前 {CAPSULE_INPUT_MAX} 字，超出部分忽略）"
                    )
                # 路线 A：硬词典纠错（在 AI 看到文本前替换）
                try:
                    fixed_text, fix_hits = apply_dictionary(user_text)
                    if fixed_text != user_text:
                        self.dict_hits = fix_hits
                        user_text = fixed_text
                        _track("auto", "dict_replace", scope="capsule",
                               props={"n_hits": len(fix_hits)})
                except Exception:
                    pass
                self.timings["input_chars"] = len(user_text)
                acc = ""
                ok = True
                got_first = False
                for kind, payload in _call_deepseek_stream(
                    sys_prompt,
                    user_text,
                    timeout=CAPSULE_STREAM_TIMEOUT,
                    max_tokens=max_tok,
                ):
                    if kind == "chunk" and not got_first:
                        self.timings["first_ms"] = int((_time.monotonic() - t0) * 1000)
                        got_first = True
                    if kind == "usage":
                        # v0.4.14：DeepSeek 流式末尾帧带 usage，记录 prefix cache 命中
                        # 数据用于监控（prompt_cache_hit_tokens / *_miss_tokens 由 DeepSeek
                        # 直接返回；命中段 input token 单价 0.26x）。前端 hover 时间标签
                        # 能看到所有 timings 字段。
                        try:
                            hit = int(payload.get("prompt_cache_hit_tokens") or 0)
                            miss = int(payload.get("prompt_cache_miss_tokens") or 0)
                            prompt_total = int(payload.get("prompt_tokens") or (hit + miss))
                            self.timings["cache_hit_tokens"] = hit
                            self.timings["cache_total_tokens"] = prompt_total
                            if prompt_total:
                                self.timings["cache_hit_ratio"] = round(hit / prompt_total, 3)
                            self.timings["completion_tokens"] = int(
                                payload.get("completion_tokens") or 0
                            )
                        except Exception:
                            pass
                        continue
                    if kind == "error":
                        ok = False
                        with self._stream_lock:
                            self._stream["ok"] = False
                            self._stream["text"] = payload
                            self._stream["seq"] += 1
                        try:
                            from datetime import datetime
                            (data_dir() / "capsule_errors.log").open("a", encoding="utf-8").write(
                                f"{datetime.now().isoformat(timespec='seconds')} "
                                f"target={Path(self.target).name if self.target else '-'} "
                                f"input_len={len(user_text)} max_tokens={max_tok} "
                                f"error={payload!r}\n"
                            )
                        except Exception:
                            pass
                        # 自动上报：DeepSeek API 错（401/403/超时/网络），非常关键的崩溃面
                        try:
                            from feedback_collector import report_auto_error
                            report_auto_error(
                                where="capsule.deepseek_stream",
                                message=f"input_len={len(user_text)} err={str(payload)[:200]}",
                            )
                        except Exception:
                            pass
                        break
                    acc += payload
                    with self._stream_lock:
                        self._stream["text"] = acc
                        self._stream["seq"] += 1
                final = acc.strip()
                if ok and final.startswith("{") and '"body"' in final:
                    try:
                        import json as _json
                        obj = _json.loads(final)
                        if isinstance(obj, dict) and obj.get("body"):
                            final = obj["body"].strip()
                    except Exception:
                        pass
                with self._stream_lock:
                    if ok:
                        self._stream["text"] = final
                    self._stream["done"] = True
                    self._stream["seq"] += 1
                if ok:
                    self.refined = final
                    # 只在精简成功时记一笔指纹，失败 / 中断不污染历史
                    try:
                        append_clip(self.text or "", self.target or "")
                    except Exception:
                        pass
            except Exception as e:
                with self._stream_lock:
                    self._stream["ok"] = False
                    self._stream["text"] = f"精简出错：{type(e).__name__} {str(e)[:100]}"
                    self._stream["done"] = True
                    self._stream["seq"] += 1
                # 自动上报：worker 崩溃，带 traceback
                try:
                    from feedback_collector import report_auto_error
                    report_auto_error(where="capsule.worker", exc=e)
                except Exception:
                    pass
            finally:
                self.timings["total_ms"] = int((_time.monotonic() - t0) * 1000)
                with self._stream_lock:
                    if not self._stream.get("done"):
                        self._stream["done"] = True
                        self._stream["seq"] += 1

        self._stream_thread = threading.Thread(target=worker, daemon=True)
        self._stream_thread.start()
        return {"ok": True, "mode": m}

    def get_progress(self) -> dict:
        with self._stream_lock:
            s = dict(self._stream)
        s["dict_hits"] = list(getattr(self, "dict_hits", []) or [])
        s["transcript_info"] = dict(getattr(self, "transcript_info", {}) or {})
        s["dup_info"] = getattr(self, "dup_info", None)
        s["timings"] = dict(getattr(self, "timings", {}) or {})
        s["kb_enabled"] = bool(getattr(self, "kb_enabled", False))
        # 字数死命令：仅在 done=True 时做兜底截断，避免流式过程中反复截
        s["length_info"] = {"any": False}
        if s.get("done") and s.get("ok", True) and s.get("text"):
            new_text, info = _enforce_length_limit(s["text"])
            if info["any"]:
                s["text"] = new_text
                # 同步覆盖到 self.refined，让 archive / copy 拿到截断版
                self.refined = new_text
            s["length_info"] = info
        return s

    def copy_result(self) -> dict:
        """把精简结果（没有就用原文）以**纯文本**复制回剪贴板，去掉 md 标记字符。"""
        if self.refined:
            self.refined, _ = _enforce_length_limit(self.refined)
        raw = (self.refined or self.text).strip()
        body = md_to_plain(raw) if self.refined else raw
        try:
            subprocess.run(["pbcopy"], input=body, text=True, timeout=5, check=False)
            _track("click", "copy_result", scope="capsule",
                   props={"len": len(body), "has_refined": bool(self.refined)})
            return {"ok": True, "len": len(body)}
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}

    def archive_image(self) -> dict:
        """v0.4.15「图片即附件归档」：

        - 把临时图片拷到 `<KB 同级>/attachments/<timestamp>.png`
        - KB 文件追加 markdown 引用 `![](attachments/<timestamp>.png)`（相对路径）
        - 计入 stats.archived（和文本归档同款指标）
        - **不动剪贴板**：用户原图还在，照样能粘到别处

        异常路径：
          - 没设 target → 直接报错（菜单栏入口已守，但 cli 直接 spawn 也得防一手）
          - 临时文件不在 → 报错（用户已经把图片清掉了）
          - 文件名秒级冲突（极端：同秒双击两次）→ 加 _2 / _3 后缀
        """
        if self.mode != "image":
            return {"ok": False, "error": "当前不是图片模式"}
        if not self.target:
            return {"ok": False, "error": "未设置默认文档"}
        src = Path(self.image_path)
        if not src.exists() or not src.is_file():
            return {"ok": False, "error": "图片临时文件不存在"}

        try:
            cfg = load_config()
            target_path = resolve_target_path(self.target, cfg)
        except Exception as e:
            return {"ok": False, "error": f"解析目标失败：{str(e)[:120]}"}

        # attachments/ 落在 KB 文件**同级**目录（用户跨设备 / git 同步走相对路径，无需重写）
        try:
            from datetime import datetime
            attach_dir = target_path.parent / "attachments"
            attach_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
            base = f"{stamp}.png"
            dest = attach_dir / base
            n = 2
            while dest.exists():
                dest = attach_dir / f"{stamp}_{n}.png"
                n += 1
            import shutil
            shutil.copyfile(src, dest)
        except Exception as e:
            return {"ok": False, "error": f"图片落盘失败：{str(e)[:120]}"}

        rel_path = f"attachments/{dest.name}"
        try:
            from archiver import append_image_ref
            append_image_ref(target_path, rel_path)
        except Exception as e:
            # 文件已经写到 attachments/ 了，但 KB 没更新 → 把图片也清掉，避免遗孤
            try:
                dest.unlink(missing_ok=True)
            except Exception:
                pass
            return {"ok": False, "error": f"写入 KB 失败：{str(e)[:120]}"}

        try:
            record_target_usage(self.target)
            bump_archived(1)
        except Exception:
            pass

        self.done = True
        _track("click", "archive_image", scope="capsule",
               props={
                   "target": Path(self.target).name,
                   "size": src.stat().st_size if src.exists() else 0,
               })
        return {
            "ok": True,
            "target": self.target,
            "saved_path": str(dest),
            "rel_path": rel_path,
            "message": f"已归档 → {Path(self.target).name}",
        }

    def copy_image_noop(self) -> dict:
        """v0.4.15：图片模式的「⌘ 仅复制」按钮。

        剪贴板里本来就是用户原图，**什么都不需要做**——保留按钮只是为了 UI 与文本模式对齐
        （用户的肌肉记忆是「↩ 归档+复制 / ⌘ 仅复制」一致）。
        """
        _track("click", "copy_image_noop", scope="capsule")
        return {"ok": True, "noop": True}

    def archive(self) -> dict:
        """写入默认 md：优先用 refined，没有就用原文。

        归档结构（v0.4.6）：
          ## 原文精简
          <主精简，--- 之前的部分；视角补充段不入笔记>

          ## 译文           ← 仅当本次会话用过翻译时才追加
          <翻译整段，保留 AI 输出的换行/段落>

        视角补充段保持「不归档」原则——只在胶囊里看。
        """
        if not self.target:
            return {"ok": False, "error": "未设置默认文档"}
        cfg = load_config()
        if self.refined:
            self.refined, _ = _enforce_length_limit(self.refined)
        raw = (self.refined or self.text).strip()
        # 砍掉 --- 之后的旁白区
        import re as _re
        parts = _re.split(r"\n-{3,}\s*\n", raw, maxsplit=1)
        body_only = parts[0].rstrip()
        had_aside = len(parts) > 1 and parts[1].strip()
        write_text = body_only

        action = _action_for_target(cfg, self.target) or next(iter(cfg.get("actions", {})), "daily")
        from bootkit import child_cmd

        cmd = child_cmd(
            "archiver", action,
            "--target", self.target, "--from-stdin", "--no-notify", "--mode", "raw",
        )
        try:
            r = subprocess.run(
                cmd, input=write_text, capture_output=True, text=True, timeout=60,
                cwd=str(data_dir()), env=os.environ.copy(),
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "写入超时"}
        if r.returncode != 0:
            return {"ok": False, "error": (r.stderr or r.stdout)[:160]}

        try:
            record_target_usage(self.target)
            bump_archived(1)
            from settings_util import get_default_target
            if self.target and self.target != (get_default_target() or ""):
                set_default_target(self.target)
        except Exception:
            pass

        self.done = True
        target_path = str(resolve_target_path(self.target, cfg))
        _track("click", "archive", scope="capsule",
               props={
                   "target": Path(self.target).name,
                   "len": len(write_text),
                   "mode": self.mode,
               })
        message = f"已写入 {Path(self.target).name}"
        if had_aside:
            message += "（📚 视角补充仅供你看，不入笔记）"
        return {
            "ok": True,
            "target": self.target,
            "target_path": target_path,
            "had_aside": bool(had_aside),
            "message": message,
        }

    def list_targets(self) -> dict:
        """返回胶囊切换面板用的常用 .md 列表（含当前）。"""
        from settings_util import get_quick_pick_targets
        cur = self.target or ""
        items = []
        seen = set()
        for raw in get_quick_pick_targets(8):
            if not raw or raw in seen:
                continue
            seen.add(raw)
            items.append({
                "raw": raw,
                "label": Path(raw).name,
                "display": display_target(raw),
                "current": raw == cur,
            })
        if cur and cur not in seen:
            items.insert(0, {
                "raw": cur,
                "label": Path(cur).name,
                "display": display_target(cur),
                "current": True,
            })
        return {"items": items, "current": cur}

    def switch_target_to(self, target: str) -> dict:
        """胶囊里点常用列表 → 不开 Finder 直接切换默认。"""
        from settings_util import resolve_target_path
        s = (target or "").strip()
        if not s:
            return {"ok": False, "error": "空 target"}
        try:
            cfg = load_config()
            abs_p = resolve_target_path(s, cfg)
            if not abs_p.exists():
                return {"ok": False, "error": f"文件不存在：{abs_p}"}
            set_default_target(s)
            self.target = s
            _track("click", "switch_target_quick", scope="capsule",
                   props={"target": Path(s).name})
            return {
                "ok": True,
                "target": s,
                "target_label": Path(s).name,
                "target_display": display_target(s),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}

    def pick_target(self) -> dict:
        """点击 › 弹 Finder 选 .md，同步更新默认归档文档。

        在 kb_root 内 → 存相对；在 kb_root 外 → 存绝对路径。
        """
        cfg = load_config()
        cur_kb = kb_root(cfg).resolve()
        script = f'''
        try
          set theFile to choose file with prompt "切换归档目标" of type {{"public.text", "net.daringfireball.markdown", "md"}} default location POSIX file "{cur_kb}" without invisibles
          return POSIX path of theFile
        on error
          return ""
        end try
        '''
        try:
            r = subprocess.run(
                ["osascript", "-e", script], capture_output=True, text=True, timeout=300
            )
            raw = (r.stdout or "").strip()
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}
        if not raw:
            return {"ok": False, "cancelled": True}
        if not raw.lower().endswith(".md"):
            return {"ok": False, "error": "请选 .md 文件"}
        abs_p = Path(raw).resolve()
        if not abs_p.exists():
            return {"ok": False, "error": "文件不存在"}
        try:
            stored = abs_p.relative_to(cur_kb).as_posix()
        except ValueError:
            stored = str(abs_p)
        try:
            set_default_target(stored)
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}
        self.target = stored
        _track("click", "switch_target", scope="capsule", props={"target": Path(stored).name})
        return {
            "ok": True,
            "target": stored,
            "target_label": Path(stored).name,
            "target_display": display_target(stored),
        }

    def resize(self, w: int, h: int) -> dict:
        """状态切换时使用，不更新用户记忆尺寸。"""
        try:
            for win in webview.windows:
                win.resize(int(w), int(h))
                break
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}
        self._cur_w = int(w)
        self._cur_h = int(h)
        return {"ok": True}

    def close(self) -> dict:
        """关窗：先 destroy，然后 0.3s 后强制退出进程 — 防止流式 LLM 线程拖住主进程。"""
        for w in webview.windows:
            try:
                w.destroy()
            except Exception:
                pass

        def _force_exit() -> None:
            try:
                os._exit(0)
            except Exception:
                pass

        threading.Timer(0.3, _force_exit).start()
        return {"ok": True}


def show_capsule(
    text: str, *, target: str, mode: str, demo: bool = False, image_path: str = "",
) -> int:
    api = CapsuleApi(
        text=text, target=target or "", mode=mode, demo=demo, image_path=image_path,
    )
    html = QUICK_UI / "capsule.html"
    if not html.exists():
        raise FileNotFoundError(f"缺少 {html}")

    init_w, init_h = CAPSULE_INITIAL
    x, y = _mouse_anchor((init_w, init_h))

    webview.create_window(
        "Quick Capsule",
        url=html.resolve().as_uri(),
        js_api=api,
        width=init_w,
        height=init_h,
        x=x,
        y=y,
        frameless=True,
        on_top=True,
        easy_drag=True,
        resizable=True,
        transparent=True,
        background_color="#000000",
    )

    try:
        webview.start(gui="cocoa")
    except Exception:
        traceback.print_exc()
        return 1
    return 0 if api.done else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="鼠标边轻量胶囊浮层")
    parser.add_argument("--target", help="指定目标 md 相对路径，默认 default_target")
    parser.add_argument("--mode", default="polish",
                        choices=list(MODE_LABELS.keys()))
    parser.add_argument("--raw", action="store_true")
    parser.add_argument(
        "--demo", action="store_true",
        help="上手引导演示：预制精简结果，不走 API",
    )
    parser.add_argument(
        "--image-path",
        default="",
        help="v0.4.15 图片即附件归档：传入剪贴板图片落盘后的临时路径，胶囊进图片预览模式（不调 AI）",
    )
    args = parser.parse_args(argv)
    if args.raw:
        args.mode = "raw"

    # 启动时确保三层档案存在（首次从模板拷贝；出错只警告，不阻塞主流程）
    try:
        ensure_profile()
    except Exception as _e:
        print(f"[warn] ensure_profile failed: {_e}", flush=True)

    _load_env()

    target = _resolve_target(args.target)
    if not target:
        _notify("Skillless", "尚未设置默认文档")
        return 2

    # 图片模式：跳过剪贴板文本读取（剪贴板里就是图，没文本），直接进胶囊
    if args.image_path:
        return show_capsule(
            "", target=target, mode=args.mode, demo=args.demo,
            image_path=args.image_path,
        )

    text = _read_clip()
    if not text.strip():
        _notify("Skillless", "剪贴板为空，先 Cmd+C")
        return 2
    try:
        record_text(text, source="capsule")
    except Exception:
        pass

    return show_capsule(text, target=target, mode=args.mode, demo=args.demo)


if __name__ == "__main__":
    raise SystemExit(main())
