#!/usr/bin/env bash
# 公开分发打包：不带内置 API Key，适合小红书 / 陌生人下载
#
# 复用 release.sh 的 bump + changelog 流程，靠 SKILLLESS_PUBLIC=1 让 build.sh 跳过 Key 内嵌。
# 用法和 release.sh 完全一致：
#   ./release-public.sh
#   ./release-public.sh patch "改动1" "改动2"
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

export SKILLLESS_PUBLIC=1
# 直接转发所有参数给 release.sh，避免 bump/changelog 两份实现走偏
"$DIR/release.sh" "$@"

NEW_VERSION="$(python3 -c 'from version import VERSION; print(VERSION)')"

APP="dist/Skillless.app"
PUB_ZIP="dist/Skillless-public-v${NEW_VERSION}.zip"
LEGACY_PUB="dist/Skillless-mac-public.zip"

if [ ! -d "$APP" ]; then
  echo "[release-public] ✗ 没有 $APP"
  exit 1
fi

# release.sh 会留下 Skillless-v<ver>.zip；公开版另起一个名字，更醒目
rm -f "$PUB_ZIP" "$LEGACY_PUB"

STAGE="$(mktemp -d -t skillless-public.XXXXXX)"
trap 'rm -rf "$STAGE"' EXIT
cp -R "$APP" "$STAGE/"
[ -f README.md ]    && cp README.md    "$STAGE/README.md"
[ -f CHANGELOG.md ] && cp CHANGELOG.md "$STAGE/CHANGELOG.md"

# 同 release.sh：不用 --keepParent，zip 顶层直接是 Skillless.app
( cd "$STAGE" && ditto -c -k --sequesterRsrc . "$DIR/$PUB_ZIP" )
( cd dist && ln -sf "Skillless-public-v${NEW_VERSION}.zip" "Skillless-mac-public.zip" ) 2>/dev/null || true

echo
echo "✓ 公开分享包：$PUB_ZIP"
if command -v shasum >/dev/null 2>&1; then
  echo "  SHA256: $(shasum -a 256 "$PUB_ZIP" | awk '{print $1}')"
fi
echo
echo "适合发小红书 / 公开链接："
echo "  · 包内没有你的 API Key，陌生人无法刷你的额度"
echo "  · 用户走引导第 6 步，去 DeepSeek 申请自己的 Key（约 1 分钟）"
echo
echo "别人怎么体验："
echo "  1. 解压 → Skillless.app 拖到「应用程序」"
echo "  2. 右键打开（若被 Gatekeeper 拦）"
echo "  3. 跟着引导走完，第 6 步粘贴自己的 sk- Key"
echo "  4. 复制 ≥100 字 → Cmd+C 试胶囊"
echo
echo "熟人想免配置？用 ./release.sh（勿公开发那个 zip）"
