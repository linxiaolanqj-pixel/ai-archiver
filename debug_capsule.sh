#!/usr/bin/env bash
# 触发胶囊后立刻跑这个，把所有诊断信息一次抓出来
set +e
DATA="$HOME/Library/Application Support/Skillless"

echo "=== 当前时间 ==="
date '+%F %T'

echo ""
echo "=== clip_watcher 最近 5 ==="
tail -5 "$DATA/clip_watcher.log"

echo ""
echo "=== Skillless 全部进程（含子进程）==="
ps -ax -o pid,etime,command | grep -i Skillless | grep -v grep

echo ""
echo "=== capsule 子进程 ==="
CAP=$(pgrep -f "Skillless --mode=capsule" 2>/dev/null | head -1)
if [ -n "$CAP" ]; then
  echo "PID=$CAP"
  echo "存活时间："; ps -o etime= -p $CAP
  echo "打开的窗口（NSWorkspace 视角）："
  osascript -e 'tell application "System Events" to get {position, size, name} of every window of (every process whose name contains "Skillless")' 2>&1 | head -10
else
  echo "(无 capsule 进程 — 它已经退出 / 没起来)"
fi

echo ""
echo "=== 屏幕分辨率 ==="
system_profiler SPDisplaysDataType 2>/dev/null | grep -A 1 "Resolution:" | head -4

echo ""
echo "=== capsule_errors 最新 ==="
tail -3 "$DATA/capsule_errors.log" 2>/dev/null || echo "(无 error 日志)"

echo ""
echo "=== capsule_spawn 最近 5 ==="
tail -5 "$DATA/capsule_spawn.log" 2>/dev/null

echo ""
echo "=== 今天新崩溃 ==="
for f in $(ls -t "$HOME/Library/Logs/DiagnosticReports/"Skillless-*.ips 2>/dev/null | head -3); do
  MIN=$(( ($(date +%s) - $(stat -f %m "$f")) / 60 ))
  if [ $MIN -lt 30 ]; then
    echo "$f ($MIN min ago)"
  fi
done
