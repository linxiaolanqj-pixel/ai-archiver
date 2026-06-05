#!/usr/bin/env bash
# Shortcuts / 命令行调用入口。
# 用法：
#   run.sh <action>            从 stdin 读文本（Shortcuts 推荐用这种）
#   run.sh <action> "text..."  把文本作为第二个参数

set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
ACTION="${1:-daily}"
shift || true

if [ -x "$DIR/.venv/bin/python" ]; then
  PY="$DIR/.venv/bin/python"
else
  PY="$(command -v python3)"
fi
if [ -f "$DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$DIR/.env"
  set +a
fi

# 快捷入口
case "$ACTION" in
  popup)
    exec "$PY" "$DIR/popup.py" "$@"
    ;;
  quick)
    # 极简 ✅❌ 浮层（绑给「输入快捷键」）
    exec "$PY" "$DIR/quick_archive.py" "$@"
    ;;
  translate)
    # AI 转译浮层：mode 可选 polish / i18n / structure，缺省 polish
    MODE="${1:-polish}"
    if [ "$MODE" = "polish" ] || [ "$MODE" = "i18n" ] || [ "$MODE" = "structure" ]; then
      shift
    else
      MODE="polish"
    fi
    exec "$PY" "$DIR/quick_archive.py" --mode "$MODE" "$@"
    ;;
  ask)
    exec "$PY" "$DIR/ask.py" "$@"
    ;;
  dashboard)
    exec "$PY" "$DIR/dashboard.py" "$@"
    ;;
esac

# 缺省：把 ACTION 当作 archiver.py 的 action 名直接调用（菜单栏 / Shortcuts 都走这条）
MODE_ARGS=()
if [ "${ARCHIVER_MODE:-}" = "raw" ]; then
  MODE_ARGS=(--mode raw)
fi
if [ -n "${ARCHIVER_TARGET:-}" ]; then
  MODE_ARGS+=(--target "$ARCHIVER_TARGET")
fi

if [ -n "$*" ]; then
  exec "$PY" "$DIR/archiver.py" "$ACTION" "${MODE_ARGS[@]}" --text "$*"
else
  exec "$PY" "$DIR/archiver.py" "$ACTION" "${MODE_ARGS[@]}" --from-stdin
fi
