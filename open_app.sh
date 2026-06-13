#!/usr/bin/env bash
# 启动 Skillless 菜单栏主进程（复制监听只在这里，后台窗口不能替代）
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$DIR/dist/Skillless.app"
BIN="$APP/Contents/MacOS/Skillless"
DATA=~/Library/Application\ Support/Skillless
LOG="$DATA/last_launch.log"
MENUBAR_LOG="$DATA/menubar_stdout.log"

if [ ! -x "$BIN" ]; then
  echo "[open] ✗ 找不到可执行文件，先跑：$DIR/build.sh"
  exit 1
fi

xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true
mkdir -p "$DATA"

# 必须清掉所有子模式（dashboard / onboarding / capsule），否则 macOS 会认为 App 已在跑而不起 menubar
echo "[open] 清理旧进程…"
pkill -f "Skillless.app/Contents/MacOS" 2>/dev/null || true
sleep 1
pkill -9 -f "Skillless.app/Contents/MacOS" 2>/dev/null || true
sleep 0.5

# 刚 rebuild 时 macOS LaunchServices 缓存 stale → kLSNoExecutableErr / _RegisterApplication SIGABRT
# 重注册一次再启动（毫秒级）
LSREG=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
"$LSREG" -u "$APP" >/dev/null 2>&1 || true
"$LSREG" -f "$APP" >/dev/null 2>&1 || true

menubar_pid() {
  # 菜单栏主进程：无 --mode= 参数
  pgrep -lf "Skillless.app/Contents/MacOS/Skillless$" 2>/dev/null | head -1
}

other_pid() {
  pgrep -lf "Skillless.app/Contents/MacOS/Skillless --mode=" 2>/dev/null | head -5
}

# 打包版是 GUI（console=False），不能用 nohup >>log 重定向 stdout，否则会 Trace/BPT trap: 5
echo "[open] 启动菜单栏主进程…"
if ! open -gj "$APP" 2>/dev/null; then
  echo "[open] open 失败，尝试 Finder 拉起…"
  osascript -e "tell application \"Finder\" to open POSIX file \"$APP\"" 2>/dev/null || true
fi

MB=""
for _ in 1 2 3 4 5 6 7 8 9 10; do
  sleep 1
  MB=$(menubar_pid || true)
  [ -n "$MB" ] && break
done

if [ -n "$MB" ]; then
  echo "[open] ✓ 菜单栏在跑："
  echo "       $MB"
  echo ""
  if [ -f "$LOG" ] && grep -q "status=ready" "$LOG" 2>/dev/null; then
    echo "[open] ✓ 已就绪（status=ready）→ 右上角找 📥，复制 ≥100 字试 Cmd+C"
  else
    echo "[open] ⚠ 进程在跑但日志未 ready（可能仍在初始化）："
    [ -f "$LOG" ] && cat "$LOG" || echo "       (无 last_launch.log)"
    echo ""
    echo "       等几秒再复制试；仍不行前台调试：open \"$APP\""
  fi
  echo ""
  CLIP_LOG="$DATA/clip_watcher.log"
  echo "       复制诊断："
  echo "         cat \"$CLIP_LOG\""
  if [ -f "$CLIP_LOG" ]; then
    echo ""
    echo "       最近几条："
    tail -5 "$CLIP_LOG" | sed 's/^/         /'
  else
    echo "       （还没有复制记录，先选 ≥100 字再 Cmd+C）"
  fi
  exit 0
fi

echo "[open] ✗ 菜单栏主进程没起来（复制监听不会工作）"
echo ""

# 兜底：LaunchServices 卡死时 → 重启 Dock 强刷 LS 缓存，再开一次
echo "[open] 兜底：刷新 LaunchServices 缓存（killall Dock）…"
killall Dock 2>/dev/null || true
sleep 2
"$LSREG" -f "$APP" >/dev/null 2>&1 || true
open -gj "$APP" 2>/dev/null || true
for _ in 1 2 3 4 5; do
  sleep 1
  MB=$(menubar_pid || true)
  [ -n "$MB" ] && break
done
if [ -n "$MB" ]; then
  echo "[open] ✓ 兜底后菜单栏起来了："
  echo "       $MB"
  exit 0
fi

OTH=$(other_pid || true)
if [ -n "$OTH" ]; then
  echo "[open] 当前只有这些子进程在跑（不是菜单栏）："
  echo "$OTH" | sed 's/^/       /'
  echo ""
  echo "       常见原因：之前开的「后台」窗口还在，挡住了菜单栏启动。"
  echo "       已尝试清理；若仍失败请手动：pkill -9 -f Skillless"
fi
echo ""
if [ -f "$LOG" ]; then
  echo "last_launch.log:"
  cat "$LOG"
  if grep -q "status=ready" "$LOG" 2>/dev/null; then
    echo ""
    echo "       ↑ 这是上次启动留下的日志，进程已退出（不要用 nohup >>log 直接跑 GUI 包）。"
  fi
fi
echo ""
[ -f "$DATA/startup.log" ] && echo "startup.log:" && cat "$DATA/startup.log" || true
echo ""
[ -f "$MENUBAR_LOG" ] && [ -s "$MENUBAR_LOG" ] && echo "menubar_stdout.log (tail):" && tail -20 "$MENUBAR_LOG" || true
echo ""
echo "前台调试：open \"$APP\""
echo "或终端直跑（勿重定向输出）：\"$BIN\""
exit 1
