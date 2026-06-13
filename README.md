# AI Archiver · 低摩擦的个人知识归档器

把零散信息从微信群 / 网页 / 会议纪要里**一键归档**到本地 Markdown 知识库的 macOS 小工具。

不解决"AI 帮你写 PRD"，专门解决：**让知识库不再靠手动维护**。

## 用法（最常见场景）

启动后菜单栏会出现 `📥 归档`。

1. 在任何 App 选中一段文字 → `Cmd+C`
2. 内容只进入后台历史，不会自动弹归档框
3. 按你在后台设置的「归档快捷键」→ 出 ✅ / ❌ 小浮层
4. 点 ✅ → 自动写入默认 `.md`，提示「已经补充到 ...，放在了文件末尾。」

主动触发：直接点菜单栏 `📥 归档` → 选文件，归档当前剪贴板内容。

## 安装

```bash
git clone <this-repo> ~/tools/ai-archiver
cd ~/tools/ai-archiver
bash install.sh
```

填 API key（默认走 DeepSeek，最便宜，¥10 能用很久）：

在 https://platform.deepseek.com/api_keys 创建 Key，写入 `.env`：

```bash
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

把 `config.yaml` 里 `provider` 改成 `deepseek`（也可以是 `anthropic` / `openai`）。

启动菜单栏 + 开机自启：

```bash
./menubar.sh start
./menubar.sh enable
```

首次启动会自动弹出 **内嵌式新客引导**（居中窗口，无需开 Safari）。若你之前装过旧版，请先补依赖：

```bash
cd ~/tools/ai-archiver
.venv/bin/pip install -r requirements.txt
./menubar.sh restart
```

菜单里也可随时点 **🎓 重新走新客引导**。单独调试引导窗：

```bash
.venv/bin/python onboarding_window.py --force
```

**引导窗口没弹出？** 常见原因：引导已标记完成（需加 `--force`），或曾在菜单栏线程里直接调 webview（已改为子进程）。请用：

```bash
cd ~/tools/ai-archiver
.venv/bin/python onboarding_window.py --force
```

终端会显示「正在打开引导窗口…」，关窗后才会回到命令行。

## 关键设计

| 能力 | 实现 |
|---|---|
| 一步式选择 | 常用文档直接列出；选「📂 在 Finder 选其他 .md」直接进系统选择器，零中间页 |
| 防误触 | `Cmd+C` 默认只记录历史，不拉起归档；旧的自动弹窗模式可在菜单里手动打开 |
| 全局快捷键 | 后台「⌨️ 快捷键」里直接按组合键录入，菜单栏进程全局监听 |
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
├── dashboard.py           后台管理 App（pywebview）
├── dashboard/             后台前端
├── quick_archive.py       极简 ✅❌ 浮层
├── quick/                 浮层前端
├── ask.py                 随便问（单轮 Q&A）
├── ask/                   随便问前端
├── history.py             剪贴板历史（文字 + 图片）
├── onboarding_window.py   新客引导（pywebview）
├── onboarding/            引导页（HTML/CSS 动画）
├── onboarding.py          引导逻辑与演示归档
├── run.sh                 命令行/Shortcuts 入口
├── menubar.sh             菜单栏 App 控制（start/stop/enable）
├── archive_menu.sh        macOS Shortcuts 弹菜单包装
├── install.sh             一键安装
├── config.yaml            配置：知识库路径、模型、操作映射
├── prompts/               每种归档类型的固定 prompt
└── requirements.txt
```

## 后台 App 与三类快捷键

菜单栏点 **📊 打开后台…**，会出来一个四 Tab 窗口：

| Tab | 内容 |
|---|---|
| 📊 首页 | 累计字数 / 节省时间 / 最后一次复制 / 常用文档 |
| 📜 历史记录 | 最近 200 条剪贴板（文字 + 图片），可一键复制 / 再次归档 |
| 📕 词典 | 跳过名单管理（内置 / config / 手动 / 自动 四组分开） |
| ⌨️ 快捷键 | 三类全局快捷键，点击输入框后直接按键录入；Shortcuts 只作为备用 |

三类快捷键（在后台 Tab 里直接按组合键即可保存）：

| 名称 | 命令 | 行为 |
|---|---|---|
| 归档 | `~/tools/ai-archiver/run.sh quick` | 弹 ✅❌ 浮层，确认即写入默认 md |
| 随便问 | `~/tools/ai-archiver/run.sh ask` | 把默认 md 喂给 LLM 单轮 Q&A |

## 全局快捷键

推荐用后台直接设置：

1. 菜单栏 `📥 归档` → `📊 打开后台…`
2. 进入 `⌨️ 快捷键`
3. 点击「归档 / 随便问」任一输入框
4. 直接按组合键，例如 `⌃⌥⌘A`
5. 如果系统没响应，去「系统设置 → 隐私与安全性 → 辅助功能」允许 Terminal / Python / Cursor

备用：macOS Shortcuts 方式

1. 打开 **Shortcuts** → 新建快捷指令 → 命名「归档」
2. 添加 Action：**Run Shell Script**
3. Script 填：

   ```bash
   ~/tools/ai-archiver/run.sh quick
   ```

4. 在快捷指令信息（i）里勾 **「Use as Quick Action」→ Services Menu** → **Pin in Menu Bar / Add Keyboard Shortcut**
5. 系统设置 → 键盘 → 键盘快捷键 → 服务，给「归档」绑你喜欢的快捷键（建议 `⌃⌥⌘A`）

**Raycast 方式**：新建 Script Command 指向同一行，给个 Hotkey。

之后任何时候：选中文字 → `Cmd+C` → 按你绑的快捷键 → ✅ / ❌ → 完成提示。

## 命令行用法

```bash
# AI 梳理后归档
echo "随便一段文字" | ./run.sh shunshoumai

# 原文模式（不调 LLM）
echo "随便一段文字" | ARCHIVER_MODE=raw ./run.sh daily

# 极简 ✅ / ❌ 浮层（读剪贴板，写默认 md）
./run.sh quick
./run.sh quick --raw      # 强制原文，不调 LLM

# 随便问（基于默认 md）
./run.sh ask

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
