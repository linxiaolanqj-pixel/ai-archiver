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

# 单一版本源：version.py。任何手动改这里的版本号都会被 release.sh 下一次 bump 覆盖。
VERSION_INFO="$("$PY" -c 'from version import VERSION, BUILD_DATE; print(VERSION); print(BUILD_DATE)' 2>/dev/null || true)"
if [ -z "$VERSION_INFO" ]; then
  echo "[build] ✗ 读不到 version.py，请确认文件存在且语法正确"
  exit 1
fi
VERSION="$(echo "$VERSION_INFO" | sed -n '1p')"
BUILD_DATE="$(echo "$VERSION_INFO" | sed -n '2p')"
echo "[build] 当前版本号: v$VERSION ($BUILD_DATE)"

echo "[build] 1/4 确保 pyinstaller 已装"
"$PY" -m pip install --quiet --upgrade "pyinstaller>=6.0"

echo "[build] 2/5 准备内置 API Key（可选，供用户免配置）"
# 公开分发（小红书等）请设 SKILLLESS_PUBLIC=1 或跑 release-public.sh，绝不内置你的 Key
if [ "${SKILLLESS_PUBLIC:-0}" = "1" ]; then
  rm -f "$DIR/platform.env" "$DIR/platform.key.enc"
  echo "[build] ✓ 公开版：不内置 API Key（用户引导里自备 DeepSeek Key）"
else
  mkdir -p secrets
  PLATFORM_SECRET="$DIR/secrets/platform.env"
  if [ ! -f "$PLATFORM_SECRET" ]; then
    AS_ENV="$HOME/Library/Application Support/Skillless/.env"
    if [ -f "$AS_ENV" ]; then
      KEY_LINE=$(grep -E '^DEEPSEEK_API_KEY=sk-' "$AS_ENV" | head -1 || true)
      if [ -n "$KEY_LINE" ]; then
        echo "$KEY_LINE" > "$PLATFORM_SECRET"
        echo "[build] 已从本机 Skillless/.env 生成 secrets/platform.env（勿提交 git）"
      fi
    fi
  fi
  if [ -f "$PLATFORM_SECRET" ]; then
    "$PY" "$DIR/pack_platform_key.py" "$PLATFORM_SECRET" "$DIR/platform.key.enc"
    rm -f "$DIR/platform.env"
    echo "[build] ✓ 熟人版：平台 Key 已加密为 platform.key.enc（仅私发，勿上小红书）"
  else
    rm -f "$DIR/platform.env" "$DIR/platform.key.enc"
    echo "[build] ⚠ 未找到 secrets/platform.env，用户需自备 API Key"
  fi
fi

echo "[build] 3/5 准备反馈通道（可选）"
# secrets/feedback_webhook.txt 一行写飞书机器人 webhook URL，build 时会加密成 feedback_webhook.enc
# 用户的反馈 / 自动错误上报会发到这个群。不配置也能跑（fallback 到剪贴板）。
FB_SECRET="$DIR/secrets/feedback_webhook.txt"
FB_ENC="$DIR/feedback_webhook.enc"
if [ -f "$FB_SECRET" ]; then
  # 通过环境变量 + stdin 都不走，最安全：让 Python 自己读文件，避免 URL 里有 shell 特殊字符
  if FB_SECRET_PATH="$FB_SECRET" FB_ENC_PATH="$FB_ENC" "$PY" - <<'PYEOF'
import os
from pathlib import Path
from feedback_collector import encrypt_webhook

src = Path(os.environ["FB_SECRET_PATH"]).read_text(encoding="utf-8").strip().splitlines()
url = src[0].strip() if src else ""
if not url:
    raise SystemExit(2)
Path(os.environ["FB_ENC_PATH"]).write_text(encrypt_webhook(url) + "\n", encoding="utf-8")
PYEOF
  then
    echo "[build] ✓ 反馈通道已加密为 feedback_webhook.enc（用户反馈/错误上报会发到你这里）"
  else
    rm -f "$FB_ENC"
    echo "[build] ⚠ secrets/feedback_webhook.txt 是空的或写入失败，本次不内置反馈通道"
  fi
else
  rm -f "$FB_ENC"
  echo "[build] ℹ 未找到 secrets/feedback_webhook.txt，本次不内置反馈通道"
  echo "        想收到用户反馈/错误日志：./setup_feedback.sh"
fi

echo "[build] 4/6 清理旧产物"
rm -rf build dist

echo "[build] 5/6 PyInstaller 打包中…（首次约 30-60 秒）"
"$PY" -m PyInstaller --noconfirm --clean Skillless.spec

if [ ! -d "dist/Skillless.app" ]; then
  echo "[build] ✗ 没生成 dist/Skillless.app，看上面报错"
  exit 1
fi

echo "[build] 6/6 写入版本号到 Info.plist + 清隔离 + 重新注册到 LaunchServices"
PLIST="dist/Skillless.app/Contents/Info.plist"
if [ -f "$PLIST" ]; then
  /usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$PLIST" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString string $VERSION" "$PLIST"
  /usr/libexec/PlistBuddy -c "Set :CFBundleVersion $VERSION" "$PLIST" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Add :CFBundleVersion string $VERSION" "$PLIST"
  echo "[build] ✓ Info.plist 版本号已设为 v$VERSION"
else
  echo "[build] ⚠ 没找到 $PLIST，跳过版本号写入"
fi

xattr -cr "dist/Skillless.app" 2>/dev/null || true
LSREG=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
"$LSREG" -u "dist/Skillless.app" >/dev/null 2>&1 || true
"$LSREG" -f  "dist/Skillless.app" >/dev/null 2>&1 || true

echo
echo "✓ 完成：dist/Skillless.app"
echo
echo "本机试用："
echo "    ./open_app.sh"
echo
echo "发给别人体验："
echo "    ./release.sh          # 熟人版（内置 Key，勿公开传播）"
echo "    ./release-public.sh   # 公开版（小红书等，用户自备 Key）"
echo
echo "拖到 /Applications："
echo "    cp -R dist/Skillless.app /Applications/"
echo
echo "卸载："
echo "    rm -rf /Applications/Skillless.app"
echo "    rm -rf ~/tools/ai-archiver/dist ~/tools/ai-archiver/build"
