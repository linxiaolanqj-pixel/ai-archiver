#!/usr/bin/env bash
# 熟人版打包：一键 bump 版本号 + 固化 changelog + 内置加密 Key + 打 .zip 分发
#
# 用法：
#   ./release.sh                                    # 不 bump，仅重打包当前版本
#   ./release.sh patch "胶囊 toast 优化"             # bump patch，追加 1 条到 changelog
#   ./release.sh minor "新增视角补充"                # bump minor
#   ./release.sh major "重写 KB 引擎"               # bump major
#   ./release.sh patch "改动1" "改动2" "改动3"      # 多条改动并入 changelog
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# ──────────────────────────── 颜色 ────────────────────────────
if [ -t 1 ]; then
  GREEN=$'\033[32m'
  RED=$'\033[31m'
  YEL=$'\033[33m'
  DIM=$'\033[2m'
  NC=$'\033[0m'
else
  GREEN= ; RED= ; YEL= ; DIM= ; NC=
fi
say_ok()  { printf "%s✓ %s%s\n" "$GREEN" "$*" "$NC"; }
say_err() { printf "%s✗ %s%s\n" "$RED"   "$*" "$NC" >&2; }
say_warn(){ printf "%s⚠ %s%s\n" "$YEL"   "$*" "$NC"; }

# ──────────────────────────── 参数解析 ────────────────────────────
BUMP="${1:-}"          # patch / minor / major / 空
shift || true
BULLETS=("$@")

if [ -n "$BUMP" ] && [ "$BUMP" != "patch" ] && [ "$BUMP" != "minor" ] && [ "$BUMP" != "major" ]; then
  say_err "未知 bump 类型：$BUMP（只接受 patch / minor / major，或留空只打包不 bump）"
  exit 2
fi

# ──────────────────────────── bump + changelog（Python 操作更稳） ────────────────────────────
if [ -n "$BUMP" ]; then
  printf '%s[release] 准备 bump=%s，bullets=%d 条%s\n' "$DIM" "$BUMP" "${#BULLETS[@]}" "$NC"

  # 把 bullets 作为 argv 传给 python（heredoc 已占 stdin，所以不能 pipe）
  NEW_VERSION="$(
    BUMP="$BUMP" python3 - "$DIR" "${BULLETS[@]}" <<'PY'
import os, re, sys, datetime, pathlib

root      = pathlib.Path(sys.argv[1])
bump_kind = os.environ["BUMP"]
bullets   = sys.argv[2:]

version_py = root / "version.py"
changelog  = root / "CHANGELOG.md"

# ── 1. 读旧 VERSION
src = version_py.read_text(encoding="utf-8")
m = re.search(r'VERSION\s*=\s*"([^"]+)"', src)
if not m:
    print("ERR_NO_VERSION", file=sys.stderr); sys.exit(3)
old = m.group(1)
parts = [int(x) for x in old.split(".")]
while len(parts) < 3:
    parts.append(0)
major, minor, patch = parts[:3]
if bump_kind == "major":
    major, minor, patch = major + 1, 0, 0
elif bump_kind == "minor":
    minor, patch = minor + 1, 0
else:
    patch += 1
new = f"{major}.{minor}.{patch}"
today = datetime.date.today().isoformat()

# ── 2. 解析 [Unreleased] 并合并新 bullets
text = changelog.read_text(encoding="utf-8")

m_unrel = re.search(
    r"(##\s*\[Unreleased\][^\n]*\n)(.*?)(\n##\s*\[)",
    text,
    flags=re.DOTALL,
)
if not m_unrel:
    print("ERR_NO_UNRELEASED", file=sys.stderr); sys.exit(4)
unrel_body = m_unrel.group(2)

# 解析 Unreleased 下面 3 个分组：✨ 新增 / 🔧 优化 / 🐛 修复
def split_section(body: str) -> dict[str, list[str]]:
    groups = {"added": [], "changed": [], "fixed": []}
    cur = None
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("### "):
            head = s[4:]
            if "新增" in head:      cur = "added"
            elif "优化" in head:    cur = "changed"
            elif "修复" in head:    cur = "fixed"
            else:                   cur = None
            continue
        if cur is None:
            continue
        if not s or s.startswith("---"):
            continue
        if s.startswith("- "):
            content = s[2:].strip()
            # 占位行 / 空 bullet 不算
            if content and not content.startswith("（"):
                groups[cur].append(content)
    return groups

groups = split_section(unrel_body)
# 命令行传入的 bullets 默认全部丢进「🔧 优化」
for b in bullets:
    b = b.strip()
    if b:
        groups["changed"].append(b)

has_any = any(groups.values())
if not has_any:
    print("ERR_EMPTY_RELEASE", file=sys.stderr); sys.exit(5)

# ── 3. 拼新版本块
def render_section(title: str, items: list[str]) -> str:
    if not items:
        return ""
    out = [f"### {title}"]
    out += [f"- {it}" for it in items]
    return "\n".join(out) + "\n"

suffix = ""  # 新版本不带 codename，旧的保持原样
new_block = f"## [{new}] - {today}{suffix}\n\n"
new_block += render_section("✨ 新增", groups["added"])
if groups["added"] and (groups["changed"] or groups["fixed"]):
    new_block += "\n"
new_block += render_section("🔧 优化", groups["changed"])
if groups["changed"] and groups["fixed"]:
    new_block += "\n"
new_block += render_section("🐛 修复", groups["fixed"])
new_block = new_block.rstrip() + "\n"

# ── 4. 替换：清空 [Unreleased] + 在它后面插入新版本块
empty_unrel = (
    "## [Unreleased]\n"
    "\n"
    "### ✨ 新增\n"
    "- （把还没发布的写这里）\n"
    "\n"
    "### 🔧 优化\n"
    "\n"
    "### 🐛 修复\n"
    "\n"
    "---\n"
    "\n"
)

# 用 m_unrel.group(3) 之前的"原 [Unreleased] 整段（含末尾 ---）"做替换
# 但原文里 [Unreleased] 后是 `\n## [` 即下一个版本，没有显式 ---
# 这里我们直接重写：把整段 [Unreleased] 替换成「空 [Unreleased] + 新版本块」
start, end = m_unrel.start(1), m_unrel.start(3)  # 到 "\n## [" 的开头
text_new = text[:start] + empty_unrel + new_block + "\n" + text[end + 1:]  # +1 跳过 group(3) 开头的 \n

changelog.write_text(text_new, encoding="utf-8")

# ── 5. 写回 version.py
src_new = re.sub(r'VERSION\s*=\s*"[^"]+"', f'VERSION = "{new}"', src)
src_new = re.sub(r'BUILD_DATE\s*=\s*"[^"]+"', f'BUILD_DATE = "{today}"', src_new)
version_py.write_text(src_new, encoding="utf-8")

# ── 6. 同步 dashboard/index.html 里的 <span class="app-version" ...>v...</span>
dash = root / "dashboard" / "index.html"
if dash.exists():
    html = dash.read_text(encoding="utf-8")
    html_new = re.sub(
        r'(<span class="app-version"[^>]*>)v[^<]+(</span>)',
        lambda m: f"{m.group(1)}v{new}{m.group(2)}",
        html,
    )
    if html_new != html:
        dash.write_text(html_new, encoding="utf-8")

# ── 7. 同步 onboarding/index.html 的 footer 版本号（如果存在）
ob = root / "onboarding" / "index.html"
if ob.exists():
    html = ob.read_text(encoding="utf-8")
    html_new = re.sub(
        r'(<span class="app-version"[^>]*>)v[^<]+(</span>)',
        lambda m: f"{m.group(1)}v{new}{m.group(2)}",
        html,
    )
    if html_new != html:
        ob.write_text(html_new, encoding="utf-8")

# ── 8. 同步 Skillless.spec 里 Info.plist 的 CFBundleShortVersionString / CFBundleVersion
spec = root / "Skillless.spec"
if spec.exists():
    s = spec.read_text(encoding="utf-8")
    s = re.sub(
        r'"CFBundleShortVersionString"\s*:\s*"[^"]+"',
        f'"CFBundleShortVersionString": "{new}"',
        s,
    )
    s = re.sub(
        r'"CFBundleVersion"\s*:\s*"[^"]+"',
        f'"CFBundleVersion": "{new}"',
        s,
    )
    spec.write_text(s, encoding="utf-8")

print(new)
PY
  )"

  rc=$?
  if [ $rc -ne 0 ]; then
    if [ $rc -eq 5 ]; then
      say_err "没有改动可发布：[Unreleased] 是空的，也没有命令行 bullets"
    else
      say_err "bump 失败（exit=$rc）"
    fi
    exit $rc
  fi

  if [ -z "$NEW_VERSION" ]; then
    say_err "bump 失败：没拿到新版本号"
    exit 6
  fi

  say_ok "版本已 bump：→ v$NEW_VERSION"
  printf '  · CHANGELOG.md / version.py / Skillless.spec / dashboard·onboarding html 已同步\n'
else
  # 不 bump：只读出当前版本号
  NEW_VERSION="$(python3 -c 'from version import VERSION; print(VERSION)')"
  printf '%s[release] 不 bump，当前版本：v%s%s\n' "$DIM" "$NEW_VERSION" "$NC"
fi

# ──────────────────────────── 打包 ────────────────────────────
"$DIR/build.sh"

APP="dist/Skillless.app"
ZIP="dist/Skillless-v${NEW_VERSION}.zip"
LEGACY_ZIP="dist/Skillless-mac.zip"

if [ ! -d "$APP" ]; then
  say_err "没有 $APP"
  exit 1
fi

rm -f "$ZIP" "$LEGACY_ZIP"

# 把 .app + README + CHANGELOG.md 一起塞进 zip（先建临时 staging）
STAGE="$(mktemp -d -t skillless-release.XXXXXX)"
trap 'rm -rf "$STAGE"' EXIT
cp -R "$APP" "$STAGE/"
[ -f README.md ]    && cp README.md    "$STAGE/README.md"
[ -f CHANGELOG.md ] && cp CHANGELOG.md "$STAGE/CHANGELOG.md"

# 注意不能用 --keepParent：会把 mktemp 临时目录名打进 zip 顶层，
# 解压后 Skillless.app 藏在 skillless-release.XXXXXX.*/ 里（v0.4.12 踩过）
( cd "$STAGE" && ditto -c -k --sequesterRsrc . "$DIR/$ZIP" )

# 兼容旧路径：留一个软链让脚本/读者一目了然
( cd dist && ln -sf "Skillless-v${NEW_VERSION}.zip" "Skillless-mac.zip" ) 2>/dev/null || true

echo
say_ok "已发布 v${NEW_VERSION}"
printf '  · changelog: CHANGELOG.md\n'
printf '  · 分发包: %s\n' "$ZIP"
printf '  · 给别人：复制 %s → 解压 → 拖进 Applications\n' "$ZIP"
if command -v shasum >/dev/null 2>&1; then
  printf '  · SHA256: %s\n' "$(shasum -a 256 "$ZIP" | awk '{print $1}')"
fi
echo
echo "别人怎么快速体验："
echo "  1. 解压 Skillless-v${NEW_VERSION}.zip，把 Skillless.app 拖到「应用程序」"
echo "  2. 首次打开若被拦：右键 Skillless → 打开（或终端 xattr -dr com.apple.quarantine /Applications/Skillless.app）"
echo "  3. 跑引导：复制一段 ≥100 字文字 → Cmd+C，跟着 7 步走完"
echo "  4. AI 精简已内置，一般不用自己填 Key"
echo
say_warn "发小红书 / 陌生人请改用：./release-public.sh"
