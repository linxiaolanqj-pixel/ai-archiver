#!/usr/bin/env bash
# 一次性配置「用户反馈/错误上报」的飞书机器人 webhook。
# 流程：
#   1. 在飞书群里 「设置」→「群机器人」→「添加机器人」→「自定义机器人」
#   2. 拷它给你的 webhook URL（形如 https://open.feishu.cn/open-apis/bot/v2/hook/xxxx）
#   3. 跑这个脚本，粘贴进去
#   4. 下次 ./build.sh 就会把它加密打包到 .app 里
#
# webhook URL 不会进 git（已加进 .gitignore）。
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
mkdir -p secrets

FB_FILE="$DIR/secrets/feedback_webhook.txt"

if [ -f "$FB_FILE" ]; then
  CUR=$(head -1 "$FB_FILE")
  echo "[setup-feedback] 当前已配置 webhook："
  echo "                 $(echo "$CUR" | sed 's|\(.\{40\}\).*|\1...|')"
  echo
  read -r -p "覆盖？[y/N] " yn
  case "$yn" in
    [yY]*) ;;
    *) echo "[setup-feedback] 跳过"; exit 0 ;;
  esac
fi

echo "[setup-feedback] 粘贴你的飞书机器人 webhook URL："
echo "                 形如 https://open.feishu.cn/open-apis/bot/v2/hook/xxxx"
read -r WEBHOOK
WEBHOOK=$(echo "$WEBHOOK" | tr -d '\r' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')

if [ -z "$WEBHOOK" ]; then
  echo "[setup-feedback] ✗ 没输入任何内容，取消"
  exit 1
fi

case "$WEBHOOK" in
  https://*) ;;
  *) echo "[setup-feedback] ⚠ webhook 不是以 https:// 开头，确认下是否粘错了" ;;
esac

echo "$WEBHOOK" > "$FB_FILE"
chmod 600 "$FB_FILE"
echo "[setup-feedback] ✓ 已写入 secrets/feedback_webhook.txt（已加进 .gitignore）"

# 顺便发一条测试消息验证 webhook 通不通
if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  PY="python3"
fi

echo "[setup-feedback] 发条测试消息验证一下…"
"$PY" - <<'PYEOF'
from feedback_collector import build_payload, send_feedback, get_feedback_webhook
print(f"[setup-feedback] 当前 webhook 解析结果：{'已配置' if get_feedback_webhook() else '空'}")
payload = build_payload(kind="user_report", description="（这是 setup_feedback.sh 的测试消息）")
r = send_feedback(payload)
print(f"[setup-feedback] 发送结果：{r}")
if r.get("ok"):
    print("[setup-feedback] ✓ 飞书群应该收到一条测试卡片了")
else:
    print(f"[setup-feedback] ✗ 失败：{r.get('reason') or r.get('error')}")
    print("[setup-feedback]    检查：webhook URL 是否填错 / 群机器人是否还活着")
PYEOF

echo
echo "[setup-feedback] 下一步：./build.sh （会把这个 webhook 加密打包到 .app 里）"
