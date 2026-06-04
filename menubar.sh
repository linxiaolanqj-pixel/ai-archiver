#!/usr/bin/env bash
# 菜单栏 App 控制脚本
#
# 用法：
#   menubar.sh start       前台/后台启动菜单栏 App（自动判断是否已在跑）
#   menubar.sh stop        停止菜单栏 App
#   menubar.sh restart     重启
#   menubar.sh status      查看运行状态
#   menubar.sh enable      安装为登录项（开机自启）
#   menubar.sh disable     取消开机自启
#   menubar.sh logs        查看运行日志

set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
APP_PY="$DIR/archiver_menubar.py"
PID_FILE="$DIR/.menubar.pid"
LOG_FILE="$DIR/.menubar.log"

PLIST_LABEL="com.archiver.menubar"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"

if [ -x "$DIR/.venv/bin/python" ]; then
  PY="$DIR/.venv/bin/python"
else
  PY="$(command -v python3)"
fi

_is_running() {
  if [ -f "$PID_FILE" ]; then
    local pid
    pid=$(cat "$PID_FILE")
    if kill -0 "$pid" 2>/dev/null; then
      echo "$pid"
      return 0
    fi
  fi
  # 兜底：按命令名查
  local pid
  pid=$(pgrep -f "archiver_menubar.py" | head -1 || true)
  if [ -n "$pid" ]; then
    echo "$pid"
    return 0
  fi
  return 1
}

cmd_start() {
  if pid=$(_is_running); then
    echo "[menubar] 已经在跑 (pid=$pid)"
    return 0
  fi
  echo "[menubar] 启动中…"
  nohup "$PY" "$APP_PY" >> "$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
  sleep 1
  if pid=$(_is_running); then
    echo "[menubar] ✓ 已启动 (pid=$pid)，看屏幕右上角的 🗂"
  else
    echo "[menubar] ✗ 启动失败，看 $LOG_FILE"
    tail -20 "$LOG_FILE" 2>/dev/null || true
    return 1
  fi
}

cmd_stop() {
  if pid=$(_is_running); then
    echo "[menubar] 停止 pid=$pid"
    kill "$pid" 2>/dev/null || true
    sleep 0.5
    pgrep -f "archiver_menubar.py" | xargs -r kill 2>/dev/null || true
    rm -f "$PID_FILE"
    echo "[menubar] ✓ 已停止"
  else
    echo "[menubar] 没在跑"
  fi
}

cmd_restart() {
  cmd_stop
  cmd_start
}

cmd_status() {
  if pid=$(_is_running); then
    echo "[menubar] running (pid=$pid)"
  else
    echo "[menubar] not running"
  fi
  if [ -f "$PLIST_PATH" ]; then
    echo "[autostart] enabled: $PLIST_PATH"
  else
    echo "[autostart] disabled"
  fi
}

cmd_enable() {
  mkdir -p "$HOME/Library/LaunchAgents"
  cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${PLIST_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PY}</string>
    <string>${APP_PY}</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${LOG_FILE}</string>
  <key>StandardErrorPath</key>
  <string>${LOG_FILE}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
  </dict>
</dict>
</plist>
PLIST
  launchctl unload "$PLIST_PATH" 2>/dev/null || true
  launchctl load "$PLIST_PATH"
  echo "[menubar] ✓ 已设置开机自启，下次登录自动启动；现在也已立即拉起"
}

cmd_disable() {
  if [ -f "$PLIST_PATH" ]; then
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    rm -f "$PLIST_PATH"
    echo "[menubar] ✓ 已取消开机自启"
  else
    echo "[menubar] 本来就没开自启"
  fi
}

cmd_logs() {
  if [ -f "$LOG_FILE" ]; then
    tail -50 "$LOG_FILE"
  else
    echo "[menubar] 没有日志文件: $LOG_FILE"
  fi
}

case "${1:-}" in
  start)     cmd_start ;;
  stop)      cmd_stop ;;
  restart)   cmd_restart ;;
  status)    cmd_status ;;
  enable)    cmd_enable ;;
  disable)   cmd_disable ;;
  logs)      cmd_logs ;;
  *)
    cat <<USAGE
用法：$(basename "$0") <command>

  start     启动菜单栏 App
  stop      停止
  restart   重启
  status    查看状态
  enable    设为开机自启（推荐）
  disable   取消开机自启
  logs      看运行日志
USAGE
    exit 1
    ;;
esac
