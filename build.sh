#!/usr/bin/env bash
# 一键把 Skillless 打成 macOS .app
#   - 用 venv 里的 pyinstaller
#   - 产物：dist/Skillless.app
#   - 双击 .app 即可启动菜单栏 App
#
# 用法： ~/tools/ai-archiver/build.sh
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  echo "[build] ✗ 没找到 .venv，先跑：python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

echo "[build] 1/4 确保 pyinstaller 已装"
"$PY" -m pip install --quiet --upgrade "pyinstaller>=6.0"

echo "[build] 2/4 清理旧产物"
rm -rf build dist

echo "[build] 3/4 PyInstaller 打包中…（首次约 30-60 秒）"
"$PY" -m PyInstaller --noconfirm --clean Skillless.spec

if [ ! -d "dist/Skillless.app" ]; then
  echo "[build] ✗ 没生成 dist/Skillless.app，看上面报错"
  exit 1
fi

echo "[build] 4/4 移除隔离 attr（避免 Gatekeeper 阻拦自打包的 App）"
xattr -dr com.apple.quarantine "dist/Skillless.app" 2>/dev/null || true

echo
echo "✓ 完成：dist/Skillless.app"
echo
echo "试用："
echo "    open dist/Skillless.app"
echo
echo "拖到 /Applications："
echo "    cp -R dist/Skillless.app /Applications/"
echo
echo "卸载："
echo "    rm -rf /Applications/Skillless.app"
echo "    rm -rf ~/tools/ai-archiver/dist ~/tools/ai-archiver/build"
