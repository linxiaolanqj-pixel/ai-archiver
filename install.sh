#!/usr/bin/env bash
# 一次性安装：建 venv、装依赖、复制 .env、给脚本执行权限
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"

echo "[1/4] 创建 venv: $DIR/.venv"
python3 -m venv "$DIR/.venv"

echo "[2/4] 安装依赖"
"$DIR/.venv/bin/pip" install --quiet --upgrade pip
"$DIR/.venv/bin/pip" install --quiet -r "$DIR/requirements.txt"

echo "[3/4] 初始化 .env"
if [ ! -f "$DIR/.env" ]; then
  cp "$DIR/.env.example" "$DIR/.env"
  echo "    → 已生成 .env，去填写你的 API key"
else
  echo "    → .env 已存在，跳过"
fi

echo "[4/5] 赋可执行权限"
chmod +x "$DIR/run.sh" "$DIR/archiver.py" "$DIR/menubar.sh" "$DIR/archive_menu.sh" 2>/dev/null || true

echo "[5/5] 初始化知识库 git 仓库（如果还没初始化）"
KB_ROOT=$(grep -E "^\s*root:" "$DIR/config.yaml" | head -1 | sed -E "s/.*root:\s*//; s/^[\"']//; s/[\"']$//")
KB_ROOT=$(eval echo "$KB_ROOT")
if [ -d "$KB_ROOT" ]; then
  if [ ! -f "$KB_ROOT/.git/HEAD" ]; then
    # git init 是幂等的，即使 .git/hooks 已被预先创建也没事
    ( cd "$KB_ROOT" && git init -q -b main && git add -A && git commit -q -m "init knowledge base" 2>/dev/null || true )
    echo "    → 已 git init: $KB_ROOT"
  else
    echo "    → 已是 git 仓库: $KB_ROOT"
  fi
else
  echo "    → 知识库目录还不存在: $KB_ROOT（首次写入时会自动创建）"
fi

echo ""
echo "✅ 安装完成。下一步："
echo "   1) 编辑 $DIR/.env 填写 API key（如还没填）"
echo "   2) 启动菜单栏 App:        $DIR/menubar.sh start"
echo "   3) 设置开机自启（推荐）:    $DIR/menubar.sh enable"
echo ""
echo "之后用法："
echo "   选中文字 → Cmd+C → 点屏幕右上角 🗂 → 选归档目标"
