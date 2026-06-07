#!/usr/bin/env bash
# 把 assets/icon.png（推荐 1024×1024 方图）转成 macOS .app 用的 Skillless.icns
# 也会生成 assets/icon-128.png / icon-256.png 供 onboarding / dashboard 引用。
#
# 用法：
#   1) 把图标存到 ~/tools/ai-archiver/assets/icon.png（方图，至少 512×512，1024×1024 最佳）
#   2) 跑：~/tools/ai-archiver/make_icon.sh
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
ASSETS="$DIR/assets"
SRC="$ASSETS/icon.png"

if [ ! -f "$SRC" ]; then
  echo "[icon] ✗ 找不到 $SRC"
  echo "       请先把方形 PNG 图标存到 ~/tools/ai-archiver/assets/icon.png"
  exit 1
fi

# 检查是否方图（推荐 1024）
W=$(sips -g pixelWidth  "$SRC" | awk 'NR==2{print $2}')
H=$(sips -g pixelHeight "$SRC" | awk 'NR==2{print $2}')
echo "[icon] 源图尺寸：${W} × ${H}"
if [ "$W" != "$H" ]; then
  echo "[icon] ⚠️  非方图，会强制拉伸成 1024×1024。建议先裁成方图。"
fi

# 1) 生成 .iconset 各种尺寸
ICONSET="$ASSETS/Skillless.iconset"
rm -rf "$ICONSET"
mkdir -p "$ICONSET"

declare -a SIZES=(16 32 64 128 256 512 1024)
for SZ in "${SIZES[@]}"; do
  sips -z "$SZ" "$SZ" "$SRC" --out "$ASSETS/_tmp_${SZ}.png" >/dev/null
done

# Apple iconset 命名规则
cp "$ASSETS/_tmp_16.png"    "$ICONSET/icon_16x16.png"
cp "$ASSETS/_tmp_32.png"    "$ICONSET/icon_16x16@2x.png"
cp "$ASSETS/_tmp_32.png"    "$ICONSET/icon_32x32.png"
cp "$ASSETS/_tmp_64.png"    "$ICONSET/icon_32x32@2x.png"
cp "$ASSETS/_tmp_128.png"   "$ICONSET/icon_128x128.png"
cp "$ASSETS/_tmp_256.png"   "$ICONSET/icon_128x128@2x.png"
cp "$ASSETS/_tmp_256.png"   "$ICONSET/icon_256x256.png"
cp "$ASSETS/_tmp_512.png"   "$ICONSET/icon_256x256@2x.png"
cp "$ASSETS/_tmp_512.png"   "$ICONSET/icon_512x512.png"
cp "$ASSETS/_tmp_1024.png"  "$ICONSET/icon_512x512@2x.png"

# 2) 用 iconutil 转 .icns
iconutil -c icns "$ICONSET" -o "$ASSETS/Skillless.icns"

# 3) 留几个给 HTML 引用（onboarding / dashboard logo）
cp "$ASSETS/_tmp_128.png" "$ASSETS/icon-128.png"
cp "$ASSETS/_tmp_256.png" "$ASSETS/icon-256.png"

# 4) 清理临时文件
rm -f "$ASSETS/_tmp_"*.png

echo "[icon] ✓ 已生成：assets/Skillless.icns + assets/icon-128.png + assets/icon-256.png"
echo "       下次 ./build.sh 打 .app 时会自动用上"
