# AI Archiver · 低摩擦的个人知识归档器

把零散信息从微信群 / 网页 / 会议纪要里**一键归档**到本地 Markdown 知识库的 macOS 小工具。

不解决"AI 帮你写 PRD"，专门解决：**让知识库不再靠手动维护**。

## 用法（最常见场景）

启动后菜单栏会出现 `📥 归档`。

1. 在任何 App 选中一段文字 → `Cmd+C`
2. 复制 ≥100 字时，自动弹"归档到哪个文件？"对话框
3. 选目标 → 自动调 LLM 结构化 → 追加到对应 `.md` 文件
4. 右上角弹通知：「你的龙虾今天更聪明一些啦 🎉 今天共归档 N 条」

主动触发：直接点菜单栏 `📥 归档` → 选文件，归档当前剪贴板内容。

## 安装

```bash
git clone <this-repo> ~/tools/ai-archiver
cd ~/tools/ai-archiver
bash install.sh
```

填 API key（默认走 DeepSeek，最便宜，¥10 能用很久）：

```bash
# 编辑 .env，填入：
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

把 `config.yaml` 里 `provider` 改成 `deepseek`（也可以是 `anthropic` / `openai`）。

启动菜单栏 + 开机自启：

```bash
./menubar.sh start
./menubar.sh enable
```

## 关键设计

| 能力 | 实现 |
|---|---|
| 一步式选择 | 弹窗直接列出知识库里所有 `.md` + `+ 新建文件` |
| 全局模式开关 | 菜单里切「AI 梳理 / 原文追加」，原文模式不调 LLM 不花钱 |
| 免打扰 | 连续 2 次「跳过」自动暂停剪贴板监听 |
| 字数过滤 | 默认 ≥100 字才弹（`config.yaml` 可改任意自然数） |
| 写入前 git checkpoint | 知识库是 git 仓库时每次写入前自动 commit，可 `git reset --hard HEAD^` 回滚 |
| 今日计数 | 状态存 `.state.json`，0 点自动重置 |
| 归档流水 | 每条写入都在知识库根 `_archive_log.md` 留一行 |

## 文件结构

```
ai-archiver/
├── archiver.py            核心：读输入 → LLM → 结构化 JSON → 追加 .md
├── archiver_menubar.py    菜单栏 App
├── run.sh                 命令行/Shortcuts 入口
├── menubar.sh             菜单栏 App 控制（start/stop/enable）
├── archive_menu.sh        macOS Shortcuts 弹菜单包装
├── install.sh             一键安装
├── config.yaml            配置：知识库路径、模型、操作映射
├── prompts/               每种归档类型的固定 prompt
└── requirements.txt
```

## 命令行用法

```bash
# AI 梳理后归档
echo "随便一段文字" | ./run.sh shunshoumai

# 原文模式（不调 LLM）
echo "随便一段文字" | ARCHIVER_MODE=raw ./run.sh daily

# 看可用操作
./archiver.py --list

# 试跑不写入
./archiver.py daily --text "测试" --dry-run
```

## 菜单栏控制

```bash
./menubar.sh start     启动
./menubar.sh stop      停止
./menubar.sh restart   重启
./menubar.sh status    看状态
./menubar.sh enable    开机自启
./menubar.sh disable   取消自启
./menubar.sh logs      看运行日志
```

## License

MIT
