#!/usr/bin/env bash
# Shortcuts / 命令行调用入口。
# 用法：
#   run.sh <action>            从 stdin 读文本（Shortcuts 推荐用这种）
#   run.sh <action> "text..."  把文本作为第二个参数

set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
ACTION="${1:-daily}"
shift || true

# 支持环境变量 ARCHIVER_MODE=raw 切到原文模式（菜单栏 App 走这条）
MODE_ARGS=()
if [ "${ARCHIVER_MODE:-}" = "raw" ]; then
  MODE_ARGS=(--mode raw)
fi
if [ -n "${ARCHIVER_TARGET:-}" ]; then
  MODE_ARGS+=(--target "$ARCHIVER_TARGET")
fi

# 加载 .env（如果存在）
if [ -f "$DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$DIR/.env"
  set +a
fi

# 优先用 venv 里的 python
if [ -x "$DIR/.venv/bin/python" ]; then
  PY="$DIR/.venv/bin/python"
else
  PY="$(command -v python3)"
fi

if [ -n "$*" ]; then
  exec "$PY" "$DIR/archiver.py" "$ACTION" "${MODE_ARGS[@]}" --text "$*"
else
  exec "$PY" "$DIR/archiver.py" "$ACTION" "${MODE_ARGS[@]}" --from-stdin
fi
