/**
 * Skillless · 上手引导（5 步）
 *   1. Welcome   —— 价值主张
 *   2. Compare   —— 同问题左右对比 + 真实流程演示动画
 *   3. Try       —— 录入快捷键 + 真的弹一次胶囊（用户手动操作）
 *   4. API       —— 配置 DeepSeek Key（前后能力差异 + 输入框 + 可跳过）
 *   5. Pick      —— 选 .md → 显示位置回执 → 「开始体验」（拉起 Dashboard）
 */
(function () {
  const STEPS = ["welcome", "compare", "try", "api", "pick"];

  let stepIndex = 0;
  let picked = null;
  let hotkey = "";
  let hasKey = false;

  const stage = document.getElementById("stage");
  const dotsEl = document.getElementById("dots");
  const actionsEl = document.getElementById("actions");

  function api() { return window.pywebview && window.pywebview.api; }
  function waitForApi() {
    return new Promise((r) => {
      const tick = () => (api() ? r(api()) : setTimeout(tick, 40));
      tick();
    });
  }

  function setLoading(on) {
    document.querySelector(".app").classList.toggle("loading", on);
  }

  function renderDots() {
    dotsEl.innerHTML = STEPS.map((_, i) => {
      let cls = "dot";
      if (i === stepIndex) cls += " active";
      else if (i < stepIndex) cls += " done";
      return `<span class="${cls}"></span>`;
    }).join("");
  }

  function btn(label, kind, onclick, opts = {}) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = `btn ${kind}`;
    b.textContent = label;
    if (opts.disabled) b.disabled = true;
    if (opts.id) b.id = opts.id;
    b.onclick = onclick;
    return b;
  }

  function clearActions() { actionsEl.innerHTML = ""; }
  function goNext() {
    if (stepIndex < STEPS.length - 1) { stepIndex += 1; render(); }
  }
  function goBack() {
    if (stepIndex > 0) { stepIndex -= 1; render(); }
  }

  async function onCancel() {
    const a = api();
    if (a) await a.cancel();
  }

  /* ============================================================
   * Step 1 · Welcome
   * ============================================================ */
  function renderWelcome() {
    stage.innerHTML = `
      <div class="welcome">
        <div class="hero-mark">S</div>
        <h2 class="title">让 Agent 真正"懂你的项目"</h2>
        <p class="lead">
          复制一段对话或正文，Skillless 自动精简成知识库笔记。<br />
          下次 Cursor / Claude 一开口，回答里全是你项目的真细节。
        </p>
      </div>`;
    clearActions();
    actionsEl.appendChild(btn("开始 · 30 秒看完 →", "primary", goNext));
  }

  /* ============================================================
   * Step 2 · 同问题 Agent 对比 + 真实流程动画
   *   动画严格对齐真实胶囊三态：Thinking → Result → Feedback
   * ============================================================ */
  function renderCompare() {
    const QUESTION = "顺手买 v2 上线要注意什么？";
    const noKB = `一般来说上线灰度要关注节奏、监控指标、回滚方案。
建议先 1% → 10% → 50% → 100%，观察核心指标变化。

（没读过你的项目，只能给通用模板。）`;
    const withKB =
      `根据《顺手买 v2》归档记录：
· **下周三 11:00** 灰度 30%（@李四 已确认）
· 核心 KPI：加购率 3% → **5%**，转化率持平不降
· 周五 18:00 前补埋点：\`button_v2_click\`
· 新人券分歧下周复盘 —— **王五负责**`;

    stage.innerHTML = `
      <h2 class="title">同一个问题，差距到底在哪？</h2>
      <p class="lead">区别只有一个：右侧 Agent 读过你 Skillless 里的 .md。</p>

      <div class="compare2">
        <div class="col before">
          <div class="col-head"><span class="tag tag-bad">普通 Agent · 无项目记忆</span></div>
          <div class="q-bubble">${escapeHtml(QUESTION)}</div>
          <div class="a-text">${escapeHtml(noKB)}</div>
        </div>
        <div class="col after">
          <div class="col-head"><span class="tag tag-good">Skillless 加持 · 有项目记忆</span></div>
          <div class="q-bubble">${escapeHtml(QUESTION)}</div>
          <div class="a-text">${mdInline(withKB)}</div>
        </div>
      </div>

      <div class="demo-section">
        <div class="demo-head">
          <h3>这条记忆怎么来的：3 个动作，循环演示</h3>
          <button type="button" class="demo-replay" id="demo-replay">↻ 重播</button>
        </div>
        <div class="demo-stage run" id="demo-stage">
          <div class="demo-phase">
            <span class="ph ph-1">① 选中</span>
            <span class="ph ph-2">② 精简</span>
            <span class="ph ph-3">③ 归档</span>
          </div>

          <!-- 原文卡：模拟微信/网页里被选中的对话 -->
          <div class="demo-source">
            <span class="src-line sel-1">小美：v2 下周三 11 点开始灰度 30%，李四已经确认了。</span><br />
            <span class="src-line sel-2">我们重点看加购率从 3% 拉到 5%，转化率不能掉。</span><br />
            <span class="src-line sel-3">周五前补埋点 button_v2_click，新人券分歧下周复盘，王五负责。</span>
          </div>

          <!-- 胶囊：三态合一，由 CSS 时间轴依次切换 thinking / result / feedback -->
          <div class="demo-capsule" id="demo-capsule">
            <!-- Phase 2a · Thinking -->
            <div class="cap-thinking">
              <span class="cap-spin"></span>
              <span>AI 正在精简…</span>
            </div>
            <!-- Phase 2b · Result（精简结果 + 三个真实按钮） -->
            <div class="cap-result">
              <div class="cap-head">
                <span class="cap-i">i</span>
                <span class="cap-title">AI · 精简</span>
                <span class="cap-target">→ 顺手买v2.md</span>
              </div>
              <div class="cap-body">
                <span class="cap-typed">下周三 11:00 灰度 30%，KPI 加购 3%→5%；周五补埋点；王五负责复盘。</span><span class="cap-cursor"></span>
              </div>
              <div class="cap-actions">
                <span class="cap-btn">↻ 精简</span>
                <span class="cap-btn">⌘ 复制</span>
                <span class="cap-btn primary">📥 归档</span>
              </div>
            </div>
            <!-- Phase 3 · Feedback（与真实工具一致：胶囊本身变 ✓ 状态） -->
            <div class="cap-feedback">
              <span class="cap-ok">✓</span>
              <span>已写入 顺手买v2.md</span>
            </div>
          </div>
        </div>
      </div>`;

    document.getElementById("demo-replay").onclick = () => {
      const s = document.getElementById("demo-stage");
      s.classList.remove("run");
      void s.offsetWidth;
      s.classList.add("run");
    };

    clearActions();
    actionsEl.appendChild(btn("← 上一步", "ghost", goBack));
    actionsEl.appendChild(btn("看着不错，继续 →", "primary", goNext));
  }

  /* ============================================================
   * Step 3 · 设快捷键 + 真的手动试一次
   * ============================================================ */
  async function renderTry() {
    stage.innerHTML = `
      <h2 class="title">设一个快捷键，亲自试一次</h2>
      <p class="lead">在任何 App 里按这个组合键 → Skillless 自动把剪贴板里的内容精简后弹胶囊。</p>

      <div class="hk-card">
        <div class="hk-row">
          <div class="hk-meta">
            <div class="hk-label">归档快捷键</div>
            <div class="hk-hint">点输入框，按下你想要的组合（推荐 <kbd>⌃</kbd> + <kbd>⌥</kbd> + <kbd>A</kbd>）</div>
          </div>
          <button type="button" class="hk-input" id="hk-input" tabindex="0" data-empty="true">
            <span id="hk-input-text">点这里录入…</span>
          </button>
        </div>
        <div class="hk-status" id="hk-status"></div>
      </div>

      <div class="try-card">
        <div class="tc-head">
          <span class="tc-step">②</span>
          <span>把这段示例文字"复制"进去，再按你刚才设的快捷键</span>
        </div>
        <pre class="tc-sample" id="tc-sample"></pre>
        <div class="tc-actions">
          <button type="button" class="btn outline" id="tc-copy">① 复制示例到剪贴板</button>
          <button type="button" class="btn primary" id="tc-trigger" disabled>② 直接弹一次胶囊试试 →</button>
        </div>
        <div class="tc-note">
          小贴士：第一次按快捷键 macOS 可能要求开启「<strong>输入监听</strong>」权限。<br />
          不想给权限也没关系，点上面 <strong>② 直接弹一次</strong> 一样能体验完整流程。
        </div>
      </div>`;

    // 渲染示例文字
    try {
      const dt = await api().get_demo_text();
      document.getElementById("tc-sample").textContent = dt.text || "";
    } catch {}

    // 读取当前 hotkey
    try {
      const cur = await api().get_input_hotkey();
      if (cur && cur.ok && cur.shortcut) {
        hotkey = cur.shortcut;
        showHotkey(cur.shortcut);
      }
    } catch {}

    setupHotkeyCapture();
    setupTryDemo();

    clearActions();
    actionsEl.appendChild(btn("← 上一步", "ghost", goBack));
    actionsEl.appendChild(btn("继续 →", "primary", goNext));
  }

  function showHotkey(shortcut) {
    const el = document.getElementById("hk-input");
    const txt = document.getElementById("hk-input-text");
    if (!el || !txt) return;
    if (shortcut) {
      txt.innerHTML = renderShortcutChips(shortcut);
      el.dataset.empty = "false";
    } else {
      txt.textContent = "点这里录入…";
      el.dataset.empty = "true";
    }
  }

  function renderShortcutChips(s) {
    return [...s].map((c) => `<kbd>${escapeHtml(c)}</kbd>`).join("<span class='hk-plus'>+</span>");
  }

  function setupHotkeyCapture() {
    const box = document.getElementById("hk-input");
    const txt = document.getElementById("hk-input-text");
    const statusEl = document.getElementById("hk-status");
    let capturing = false;

    function start() {
      capturing = true;
      box.classList.add("capturing");
      txt.textContent = "按下你想要的组合键…";
      statusEl.textContent = "";
      statusEl.className = "hk-status";
    }
    function stop() {
      capturing = false;
      box.classList.remove("capturing");
      if (!hotkey) txt.textContent = "点这里录入…";
    }

    box.onclick = () => { box.focus(); start(); };
    box.onblur = () => stop();

    box.addEventListener("keydown", async (e) => {
      if (!capturing) return;
      e.preventDefault();
      // 仅修饰键不算
      const isMod = ["Control", "Alt", "Shift", "Meta", "Option", "Command"].includes(e.key);
      if (isMod) return;

      const mods = [];
      if (e.ctrlKey)  mods.push("⌃");
      if (e.altKey)   mods.push("⌥");
      if (e.shiftKey) mods.push("⇧");
      if (e.metaKey)  mods.push("⌘");

      let key = (e.key || "").toUpperCase();
      if (key === " " ) key = "SPACE";
      if (key === "ESCAPE" || key === "ESC") {
        stop();
        return;
      }
      if (key.length > 1 && !["F1","F2","F3","F4","F5","F6","F7","F8","F9","F10","F11","F12","SPACE"].includes(key)) {
        // 不接受 "ARROWUP" 这种功能键
        return;
      }
      const shortcut = mods.join("") + key;
      const res = await api().set_input_hotkey(shortcut);
      if (res.ok) {
        hotkey = res.shortcut;
        showHotkey(hotkey);
        statusEl.textContent = `✓ 已保存：${hotkey}`;
        statusEl.className = "hk-status ok";
      } else {
        statusEl.textContent = `✗ ${res.error || "保存失败"}`;
        statusEl.className = "hk-status err";
      }
      box.blur();
    });
  }

  function setupTryDemo() {
    const copyBtn = document.getElementById("tc-copy");
    const triggerBtn = document.getElementById("tc-trigger");
    let copied = false;

    copyBtn.onclick = async () => {
      const res = await api().copy_demo_to_clipboard();
      if (res.ok) {
        copied = true;
        copyBtn.textContent = "✓ 已复制到剪贴板";
        copyBtn.classList.add("done");
        triggerBtn.disabled = false;
      } else {
        copyBtn.textContent = "✗ 复制失败，重试";
      }
    };

    triggerBtn.onclick = async () => {
      if (!copied) await api().copy_demo_to_clipboard();
      triggerBtn.disabled = true;
      triggerBtn.textContent = "胶囊已弹起，看屏幕…";
      const res = await api().trigger_capsule();
      setTimeout(() => {
        triggerBtn.disabled = false;
        triggerBtn.textContent = "再来一次 ↻";
      }, 2500);
      if (!res.ok) {
        triggerBtn.textContent = "✗ 启动失败：" + (res.error || "未知");
      }
    };
  }

  /* ============================================================
   * Step 4 · API Key（可跳过：清楚说明有/无 Key 的差异）
   * ============================================================ */
  async function renderApi() {
    let status = { has_key: false, masked: "" };
    try {
      const r = await api().get_api_status();
      if (r && r.ok) status = r;
    } catch {}
    hasKey = status.has_key;

    stage.innerHTML = `
      <h2 class="title">配 DeepSeek API · 开启 AI 能力</h2>
      <p class="lead">不填也能用 — Skillless 会退化成"剪贴板速记 + 手动归档"。填了 Key 就解锁所有 AI 自动化。</p>

      <div class="api-compare">
        <div class="api-col api-col-off">
          <div class="api-col-head">
            <span class="api-dot off">○</span>
            <span class="api-col-title">不配 Key</span>
            <span class="api-col-sub">基础剪贴板工具</span>
          </div>
          <ul class="api-list">
            <li class="ok">复制即记录到剪贴板历史</li>
            <li class="ok">手动把原文归档到默认 .md</li>
            <li class="ok">Dashboard 浏览/管理历史</li>
            <li class="no">AI 精简（弹胶囊会提示缺 Key）</li>
            <li class="no">AI 翻译 / 润色 / 结构化</li>
            <li class="no">今日 Memory 智能摘要</li>
            <li class="no">基于 .md 的 AI 问答</li>
          </ul>
        </div>
        <div class="api-col api-col-on">
          <div class="api-col-head">
            <span class="api-dot on">✓</span>
            <span class="api-col-title">配上 Key（推荐）</span>
            <span class="api-col-sub">完整 AI 工作流</span>
          </div>
          <ul class="api-list">
            <li class="ok">上面 3 条都有 +</li>
            <li class="ok yes"><strong>胶囊一键 AI 精简</strong> · 抽掉废话只留结论</li>
            <li class="ok yes"><strong>翻译/润色/结构化</strong> · 不同模式按需选</li>
            <li class="ok yes"><strong>今日 Memory</strong> · LLM 每天自动总结你学到了啥</li>
            <li class="ok yes"><strong>AI Ask</strong> · 把整个知识库当 context 提问</li>
            <li class="ok yes">原文 → 结论前置的精简笔记</li>
          </ul>
        </div>
      </div>

      <div class="api-input-card">
        <div class="api-input-head">
          <span class="api-input-label">DeepSeek API Key</span>
          ${status.has_key
            ? `<span class="api-input-state ok">✓ 已配置：${escapeHtml(status.masked)}</span>`
            : `<span class="api-input-state">未配置</span>`}
        </div>
        <div class="api-input-row">
          <input type="password" id="api-key-input" placeholder="${status.has_key ? "如需更换，粘贴新 Key…" : "粘贴 sk- 开头的 Key…"}" autocomplete="off" />
          <button type="button" class="btn primary" id="api-save">保存</button>
        </div>
        <div class="api-input-hint" id="api-status"></div>
        <div class="api-help">
          没有 Key？去 <a href="https://platform.deepseek.com" id="api-link">platform.deepseek.com</a>
          注册一个，新用户送 500 万 tokens，够用很久（也支持 OpenAI / Anthropic 的 sk-Key）。
        </div>
      </div>`;

    document.getElementById("api-save").onclick = async () => {
      const input = document.getElementById("api-key-input");
      const statusEl = document.getElementById("api-status");
      const v = (input.value || "").trim();
      if (!v) {
        statusEl.textContent = "请粘贴 Key";
        statusEl.className = "api-input-hint err";
        return;
      }
      statusEl.textContent = "保存中…";
      statusEl.className = "api-input-hint";
      const res = await api().save_api(v);
      if (res.ok) {
        statusEl.textContent = `✓ 已保存：${res.masked}`;
        statusEl.className = "api-input-hint ok";
        hasKey = true;
        input.value = "";
      } else {
        statusEl.textContent = `✗ ${res.error || "保存失败"}`;
        statusEl.className = "api-input-hint err";
      }
    };

    // 兼容 pywebview：在浏览器里点 a 会跳，pywebview 里劫持去 open
    const link = document.getElementById("api-link");
    if (link) {
      link.onclick = (e) => {
        e.preventDefault();
        try { api().open_link && api().open_link(link.href); } catch {}
        return false;
      };
    }

    clearActions();
    actionsEl.appendChild(btn("← 上一步", "ghost", goBack));
    actionsEl.appendChild(btn(hasKey ? "继续 →" : "暂不配置，先用基础功能 →", "primary", goNext));
  }

  /* ============================================================
   * Step 5 · 选 .md（最后一步 → 拉起 Dashboard）
   * ============================================================ */
  function renderPick() {
    stage.innerHTML = `
      <h2 class="title">最后一步：告诉 Skillless 写到哪</h2>
      <p class="lead">挑一个 .md 当默认归档文档。<strong>它所在的文件夹</strong>会自动成为你的"知识库根"，
        Cursor 等 Agent 把这个目录加进来就能读到。<br />
        <span class="pick-tail-tip">点「开始体验」后会自动打开 Skillless 后台。</span></p>

      <div class="pick-zone">
        <button type="button" class="pick-primary" id="pick-existing">
          <span class="pp-ico">📄</span>
          <span class="pp-text">
            <span class="pp-title">从 Finder 选一个 .md 文件</span>
            <span class="pp-desc">任意位置都行 · 已有的笔记、Obsidian vault、桌面随手放的都 OK</span>
          </span>
          <span class="pp-arrow">›</span>
        </button>

        <div class="pick-secondary">
          <span>没有现成的？</span>
          <button type="button" class="linkish" id="toggle-new">新建一个空的 .md ▾</button>
        </div>

        <div class="new-md-form" id="new-md-form">
          <label class="nm-label">在 Finder 中选位置 + 起个名字</label>
          <div class="nm-row">
            <input type="text" id="new-md-name" placeholder="例如：我的项目记忆" value="Skillless 笔记" />
            <button type="button" class="btn outline" id="pick-new">选位置并创建</button>
          </div>
        </div>

        <div class="picked-card" id="picked-card"></div>
      </div>`;

    document.getElementById("toggle-new").onclick = () => {
      document.getElementById("new-md-form").classList.toggle("show");
    };
    document.getElementById("pick-existing").onclick = () => doPick(() => api().pick_existing_md());
    document.getElementById("pick-new").onclick = () => doPick(() => api().pick_new_md());

    clearActions();
    actionsEl.appendChild(btn("← 上一步", "ghost", goBack));
    const finishBtn = btn("开始体验", "primary", doFinish, { disabled: !picked, id: "btn-finish" });
    actionsEl.appendChild(finishBtn);
    if (picked) renderPicked(picked);
  }

  async function doPick(fn) {
    setLoading(true);
    const res = await fn();
    setLoading(false);
    if (!res || res.cancelled) return;
    const card = document.getElementById("picked-card");
    if (!res.ok) {
      card.className = "picked-card err show";
      card.innerHTML = `
        <div class="pk-head">
          <span class="pk-tick">!</span>
          <span class="pk-title">没保存成功</span>
        </div>
        <div class="pk-line"><span class="pk-k">原因</span><span class="pk-v">${escapeHtml(res.error || "未知错误")}</span></div>`;
      return;
    }
    picked = res;
    renderPicked(res);
    const b = document.getElementById("btn-finish");
    if (b) b.disabled = false;
  }

  function renderPicked(res) {
    const card = document.getElementById("picked-card");
    if (!card) return;
    card.className = "picked-card show";
    card.innerHTML = `
      <div class="pk-head">
        <span class="pk-tick">✓</span>
        <span class="pk-title">已设定默认归档位置</span>
      </div>
      <div class="pk-line">
        <span class="pk-k">默认 .md</span>
        <span class="pk-v" title="${escapeHtml(res.file_path)}">${escapeHtml(res.file_display)}</span>
      </div>
      <div class="pk-line">
        <span class="pk-k">知识库根</span>
        <span class="pk-v" title="${escapeHtml(res.kb_path)}">${escapeHtml(res.kb_display)}</span>
      </div>
      <div class="pk-actions">
        <button type="button" class="btn outline" id="pk-open">在 Finder 中查看</button>
        <button type="button" class="btn ghost" id="pk-redo">换一个 .md</button>
      </div>`;
    const openBtn = document.getElementById("pk-open");
    if (openBtn) openBtn.onclick = () => api().open_default_md();
    const redoBtn = document.getElementById("pk-redo");
    if (redoBtn) redoBtn.onclick = () => {
      picked = null;
      card.classList.remove("show");
      const b = document.getElementById("btn-finish");
      if (b) b.disabled = true;
    };
  }

  async function doFinish() {
    if (!picked) return;
    setLoading(true);
    const res = await api().finish();
    setLoading(false);
    if (!res.ok) alert(res.error || "保存失败");
  }

  /* ============================================================
   * 工具
   * ============================================================ */
  function mdInline(s) {
    const escaped = escapeHtml(s);
    return escaped
      .replace(/`([^`]+)`/g, '<code style="background:#e0f2fe;color:#075985;padding:1px 6px;border-radius:4px;font-family:ui-monospace,Menlo,monospace;font-size:12px">$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/\n/g, '<br>');
  }
  function escapeHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  const renderers = {
    welcome: renderWelcome,
    compare: renderCompare,
    try: renderTry,
    api: renderApi,
    pick: renderPick,
  };

  function render() {
    renderDots();
    const name = STEPS[stepIndex];
    const fn = renderers[name];
    if (fn) fn();
  }

  document.getElementById("btn-cancel").onclick = onCancel;
  waitForApi().then(() => render());
})();
