#!/usr/bin/env bash
# 给 macOS Shortcuts 用的入口：
# 1) 从 stdin 接收选中的文本（Shortcut 配置成 Pass input: to stdin）
# 2) 弹一个 AppleScript 菜单让用户选归档类型
# 3) 调 run.sh 把文本喂给 archiver.py
#
# 也可以单独从命令行跑测试：
#   echo "测试一段话" | ~/tools/ai-archiver/archive_menu.sh

set -e

DIR="$(cd "$(dirname "$0")" && pwd)"

# 1) 把 stdin 存到临时文件
TMP_FILE=$(mktemp -t archiver.XXXXXX)
trap 'rm -f "$TMP_FILE"' EXIT
cat > "$TMP_FILE"

if [ ! -s "$TMP_FILE" ]; then
  osascript -e 'display notification "没有选中文字，先选一段再触发快捷键" with title "Skillless"' || true
  exit 0
fi

# 2) 弹菜单（item 1 即用户选的那条，括号里是 action key）
CHOICE=$(osascript <<'APPLESCRIPT'
set actionList to {¬
  "今日杂记 (daily)", ¬
  "顺手买知识库 (shunshoumai)", ¬
  "提取待办 (todo)", ¬
  "提取会议结论 (meeting)", ¬
  "提取产品分歧 (divergence)", ¬
  "周报素材 (weekly)"}
set theChoice to choose from list actionList ¬
  with prompt "归档到哪里？" ¬
  default items {"今日杂记 (daily)"} ¬
  OK button name "归档" ¬
  cancel button name "取消"
if theChoice is false then
  return "__CANCELLED__"
else
  return item 1 of theChoice
end if
APPLESCRIPT
)

if [ "$CHOICE" = "__CANCELLED__" ] || [ -z "$CHOICE" ]; then
  exit 0
fi

# 3) 从 "今日杂记 (daily)" 里提出 daily
ACTION=$(printf '%s' "$CHOICE" | sed -E 's/.*\(([a-z_]+)\).*/\1/')

if [ -z "$ACTION" ]; then
  osascript -e 'display notification "解析操作失败" with title "Skillless"' || true
  exit 1
fi

# 4) 调归档器（把临时文件作为 stdin 喂进去）
"$DIR/run.sh" "$ACTION" < "$TMP_FILE"
