#!/usr/bin/env bash
# 一键"重新走新手引导"
#   - reset .state.json 到第一次使用的状态
#   - 清空 .history/（备份到 .reset_backup/）
#   - 直接独立进程跑 onboarding_window.py（不依赖菜单栏 App，避免 launchd 冲突）
#
# 用法： ~/tools/ai-archiver/onboard.sh
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
PY="$DIR/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

cd "$DIR"

# 1) 备份现有 state + history
TS="$(date +%Y%m%d_%H%M%S)"
BAK="$DIR/.reset_backup/$TS"
mkdir -p "$BAK"
[ -f .state.json ] && cp .state.json "$BAK/state.json" 2>/dev/null || true
[ -d .history    ] && cp -R .history "$BAK/history"   2>/dev/null || true
echo "[onboard] ✓ 备份到 $BAK"

# 2) 重置到「第一次使用」
cat > .state.json <<JSON
{
  "date": "$(date +%F)",
  "count": 0
}
JSON
mkdir -p .history/img .history/txt
: > .history/clips.jsonl
: > .history/events.jsonl
echo '{}' > .history/stats.json
find .history/img .history/txt -mindepth 1 -delete 2>/dev/null || true
echo "[onboard] ✓ 已重置 .state.json + .history/"

# 3) 杀掉旧的 menubar 进程（避免冲突）
pkill -f archiver_menubar.py 2>/dev/null || true
sleep 0.5

# 4) 独立进程直接拉起引导窗口（强制弹，无视 state）
echo "[onboard] 启动 Skillless 上手窗口…"
echo "         ⚠️  本脚本只开「新手引导窗」，不会出现菜单栏 📥 图标"
echo "         引导走完后请用：$DIR/open_app.sh  或  $DIR/menubar.sh start"
echo "         （关掉窗口前，这个终端会一直停在这里）"
exec "$PY" "$DIR/onboarding_window.py" --force
