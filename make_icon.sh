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
  echo "[icon] ⚠️  非方图 ${W}×${H}，自动居中裁成方图"
  SIDE=$(( W < H ? W : H ))
  sips -c "$SIDE" "$SIDE" "$SRC" --out "$SRC" >/dev/null
  sips -z 1024 1024 "$SRC" --out "$SRC" >/dev/null
fi

# 0) macOS squircle 圆角（避免方角尖图标）
if [ -x "$DIR/.venv/bin/python" ]; then
  PY_ICON="$DIR/.venv/bin/python"
else
  PY_ICON="$(command -v python3)"
fi
echo "[icon] 套用 macOS squircle 圆角…"
"$PY_ICON" "$DIR/icon_squircle.py" "$SRC" "$SRC"

# 1) 生成 .iconset 各种尺寸
ICONSET="$ASSETS/Skillless.iconset"
rm -rf "$ICONSET"
mkdir -p "$ICONSET"

# 用 PIL 按目标尺寸重新套 squircle（sips 缩放会让圆角变「方」）
"$PY_ICON" "$DIR/icon_squircle.py" --all "$SRC" "$ASSETS"

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

# 2) 转 .icns（优先 iconutil；沙箱/无 GUI 环境可能失败，fallback Python）
if iconutil -c icns "$ICONSET" -o "$ASSETS/Skillless.icns" 2>/dev/null; then
  echo "[icon] iconutil ✓"
else
  echo "[icon] iconutil 不可用，改用 Python icns_writer.py"
  "$DIR/.venv/bin/python" "$DIR/icns_writer.py" "$SRC" "$ASSETS/Skillless.icns"
fi

# 3) 留几个给 HTML 引用（onboarding / dashboard logo）
cp "$ASSETS/_tmp_128.png" "$ASSETS/icon-128.png"
cp "$ASSETS/_tmp_256.png" "$ASSETS/icon-256.png"

# 4) 清理临时文件
rm -f "$ASSETS/_tmp_"*.png

echo "[icon] ✓ 已生成：assets/Skillless.icns + assets/icon-128.png + assets/icon-256.png"
echo "       下次 ./build.sh 打 .app 时会自动用上"
