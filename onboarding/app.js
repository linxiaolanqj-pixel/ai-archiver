/**
 * Skillless · 上手引导（7 步）
 *   1. Welcome —— 三大核心能力总览
 *   2. Refine  —— ① 选中就精简：动画演示
 *   3. How     —— ② 精简后归档：动画演示
 *   4. Hotkey  —— ⌘C 触发 + 亲自试一次
 *   5. API     —— AI 已内置（或可选自备 Key）
 *   6. Pick    —— 选默认 .md = 知识库
 *   7. KB      —— 知识库越用越懂：三列对比演示
 */
(function () {
  const STEPS = ["welcome", "refine", "how", "hotkey", "api", "pick", "kb"];

  let stepIndex = 0;
  let picked = null;
  let hotkey = "";
  let hasKey = false;
  const EASY_HOTKEY = "⌘C";
  const ALT_HOTKEY = "⌥⌘R";
  let permPollTimer = null;

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
        <div class="hero-mark">
          <img src="../assets/icon-128.png" alt=""
               onerror="this.parentNode.classList.add('no-img'); this.remove();" />
        </div>
        <h2 class="title">选中文字，立刻变清晰</h2>
        <p class="lead">
          Skillless 做三件事：<strong>① 选中就精简</strong> · 去口水、结构化；<br />
          <strong>② 一键归档</strong> · 追加到你指定的 .md；<br />
          <strong>③ 越用越懂你</strong> · AI 读你的笔记，下次精简会顺手补遗漏、提示重复。
        </p>
      </div>`;
    clearActions();
    actionsEl.appendChild(btn("开始 →", "primary", goNext));
  }

  /* ============================================================
   * Step 2 · ① 选中就精简（动画演示）
   * ============================================================ */
  function renderRefine() {
    stage.innerHTML = `
      <h2 class="title">① 选中就精简</h2>
      <p class="lead">选中一段口语化文字 → 按 <kbd>⌘</kbd><kbd>C</kbd> 复制 → 胶囊弹出 → AI 去口水化 + 结构化。先看一遍真实效果。</p>

      <div class="demo-stage refine-stage run" id="refine-stage">
        <div class="demo-phase">
          <span class="ph ph-1">① 复制</span>
          <span class="ph ph-2">② 精简</span>
        </div>
        <div class="demo-source">
          <span class="src-line sel-1">你知道吗，我们最近上线了一个新的工具，哈哈哈哈，但是遇到了一个问题。</span><br />
          <span class="src-line sel-2">里面一个数据吧，有点问题；反正现在就很难搞。我想去找那帮人，但是没有啥利益点去推动他们。</span><br />
          <span class="src-line sel-3">而且那如果要给部门做数据反哺的话，是直接给这个表就行，还是得再处理一下？</span>
        </div>
        <div class="demo-capsule">
          <div class="cap-thinking">
            <span class="cap-spin"></span>
            <span>AI 正在去口水化 + 结构化…</span>
          </div>
          <div class="cap-result">
            <div class="cap-head">
              <span class="cap-i">i</span>
              <span class="cap-title">AI · 精简</span>
            </div>
            <div class="cap-body">
              <div class="cap-typed-md">
                <div class="cap-row cap-l1"><strong>1. 新工具上线遇阻</strong></div>
                <div class="cap-row cap-l2"><span class="cap-sub">数据有问题，缺乏利益点驱动相关方配合</span></div>
                <div class="cap-row cap-l3"><strong>2. 数据反哺的困惑</strong></div>
                <div class="cap-row cap-l4"><span class="cap-sub">直接给表就行？还是需要再处理一下？</span></div>
              </div>
            </div>
            <div class="cap-actions">
              <span class="cap-btn">↻ 精简</span>
              <span class="cap-btn">⌘ 复制</span>
              <span class="cap-btn primary">📥 归档</span>
            </div>
          </div>
        </div>
      </div>
      <div class="demo-replay-wrap">
        <button type="button" class="demo-replay" id="refine-replay">↻ 重播动画</button>
      </div>`;

    document.getElementById("refine-replay").onclick = () => {
      const s = document.getElementById("refine-stage");
      s.classList.remove("run");
      void s.offsetWidth;
      s.classList.add("run");
    };

    clearActions();
    actionsEl.appendChild(btn("← 上一步", "ghost", goBack));
    actionsEl.appendChild(btn("继续 → 看看归档", "primary", goNext));
  }

  /* ============================================================
   * Step 3 · ② 精简后能归档（演示动画 + 能力网格）
   * ============================================================ */
  function renderHow() {
    stage.innerHTML = `
      <h2 class="title">② 精简好了，一键归档</h2>
      <p class="lead">选中 → AI 去口水化 + 结构化 → 点「归档」飞进你的 .md。下面动画就是真实流程。</p>

      <div class="demo-stage run" id="demo-stage">
        <div class="demo-phase">
          <span class="ph ph-1">① 选中</span>
          <span class="ph ph-2">② 精简</span>
          <span class="ph ph-3">③ 归档</span>
        </div>

        <!-- ① 原文卡：保留真实口语化 -->
        <div class="demo-source">
          <span class="src-line sel-1">你知道吗，我们最近上线了一个新的工具，哈哈哈哈，但是遇到了一个问题。</span><br />
          <span class="src-line sel-2">里面一个数据吧，有点问题；反正现在就很难搞。我想去找那帮人，但是没有啥利益点去推动他们。</span><br />
          <span class="src-line sel-3">而且那如果要给部门做数据反哺的话，是直接给这个表就行，还是得再处理一下？</span>
        </div>

        <!-- ② 胶囊：thinking → result（去口水化 + 结构化） -->
        <div class="demo-capsule" id="demo-capsule">
          <div class="cap-thinking">
            <span class="cap-spin"></span>
            <span>AI 正在去口水化 + 结构化…</span>
          </div>
          <div class="cap-result">
            <div class="cap-head">
              <span class="cap-i">i</span>
              <span class="cap-title">AI · 精简</span>
              <span class="cap-target">→ 工作待办.md</span>
            </div>
            <div class="cap-body">
              <div class="cap-typed-md">
                <div class="cap-row cap-l1"><strong>1. 新工具上线遇阻</strong></div>
                <div class="cap-row cap-l2"><span class="cap-sub">数据有问题，缺乏利益点驱动相关方配合</span></div>
                <div class="cap-row cap-l3"><strong>2. 数据反哺的困惑</strong></div>
                <div class="cap-row cap-l4"><span class="cap-sub">直接给表就行？还是需要再处理一下？</span></div>
              </div>
            </div>
            <div class="cap-actions">
              <span class="cap-btn">↻ 精简</span>
              <span class="cap-btn">⌘ 复制</span>
              <span class="cap-btn primary">📥 归档</span>
            </div>
          </div>
        </div>

        <!-- ③ 飞行包裹 -->
        <div class="demo-parcel">
          <span class="parcel-ico">📝</span>
          <span class="parcel-text">工作待办.md</span>
        </div>

        <!-- ③ 文件夹：被命中时弹一下 + 角标 +1 -->
        <div class="demo-folder">
          <div class="folder-shape">
            <span class="folder-emoji">📁</span>
            <span class="folder-name">知识库</span>
            <span class="folder-badge">+1</span>
          </div>
        </div>
      </div>

      <div class="demo-replay-wrap">
        <button type="button" class="demo-replay" id="demo-replay">↻ 重播动画</button>
      </div>

      <h3 class="title-2">Skillless 三大核心能力</h3>
      <div class="capa-grid capa-grid-3">
        <div class="capa-card capa-card-primary">
          <span class="capa-ico">✨</span>
          <div class="capa-title">① 选中就精简</div>
          <div class="capa-desc">选中文字按 ⌘C 复制，胶囊立刻去口水、结构化</div>
        </div>
        <div class="capa-card">
          <span class="capa-ico">📥</span>
          <div class="capa-title">② 一键归档</div>
          <div class="capa-desc">满意就点归档，追加到你指定的 .md</div>
        </div>
        <div class="capa-card">
          <span class="capa-ico">📚</span>
          <div class="capa-title">③ 越用越懂你</div>
          <div class="capa-desc">AI 读过你的笔记，下次会顺手提示重复、补遗漏</div>
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
    actionsEl.appendChild(btn("继续 → 设置快捷键", "primary", goNext));
  }

  /* ============================================================
   * Step 5 · ⌘C 快捷键 + 亲自试一次
   * ============================================================ */
  function markDemoSuccess() {
    window._onboardingDemoOk = true;
    const rowLocal = document.getElementById("hk-diag-local");
    const rowGlobal = document.getElementById("hk-diag-global");
    const rowMatch = document.getElementById("hk-diag-match");
    const hint = document.getElementById("hk-diag-hint");
    const setRow = (row, state, text) => {
      if (!row) return;
      row.dataset.state = state;
      row.querySelector(".hk-diag-text").textContent = text;
    };
    setRow(rowLocal, "ok", "① 本窗口内监听：演示通过 ✓");
    setRow(rowGlobal, "ok", "② 全局监听：演示模式跳过 ✓（正式用时再开权限）");
    setRow(rowMatch, "ok", "③ 命中你的组合：演示胶囊已弹起 ✓");
    if (hint) {
      hint.innerHTML =
        `演示通过 ✓ 已用<strong>预制精简结果</strong>弹胶囊（无需 API Key）。` +
        `点「继续」去配 Key，或先跳过也行。`;
      hint.className = "hk-diag-hint ok";
    }
    const box = document.getElementById("hk-diag");
    if (box) box.style.display = "block";
  }

  async function ensureDefaultHotkey() {
    const statusEl = document.getElementById("hk-status");
    try {
      const cur = await api().get_input_hotkey();
      if (cur && cur.ok && cur.shortcut) {
        if (cur.shortcut === "⇧⌘E" || cur.shortcut === "⌘E") {
          await applyHotkeyPreset(EASY_HOTKEY);
          return;
        }
        hotkey = cur.shortcut;
        showHotkey(cur.shortcut);
        if (statusEl) {
          statusEl.textContent = `快捷键 ${cur.shortcut} 已就绪，可直接点下面体验`;
          statusEl.className = "hk-status ok";
        }
        const acts = document.getElementById("hk-actions");
        if (acts) acts.style.display = "flex";
        return;
      }
    } catch {}
    try {
      const res = await api().set_input_hotkey(EASY_HOTKEY);
      if (res.ok) {
        hotkey = res.shortcut;
        showHotkey(hotkey);
        const acts = document.getElementById("hk-actions");
        if (acts) acts.style.display = "flex";
        if (statusEl) {
          statusEl.textContent = `已设置 ${hotkey}，完成上方授权后去备忘录试试`;
          statusEl.className = "hk-status ok";
        }
      }
    } catch {}
  }

  async function applyHotkeyPreset(shortcut) {
    const statusEl = document.getElementById("hk-status");
    try { await api().enable_hotkey_mode(); } catch {}
    const res = await api().set_input_hotkey(shortcut);
    if (!res || !res.ok) {
      if (statusEl) {
        statusEl.textContent = `✗ ${(res && res.error) || "保存失败"}`;
        statusEl.className = "hk-status err";
      }
      return false;
    }
    hotkey = res.shortcut;
    showHotkey(hotkey);
    document.querySelectorAll(".hk-preset").forEach((b) => {
      b.classList.toggle("active", b.dataset.hk === hotkey);
    });
    if (statusEl) {
      if (res.listener_ok) {
        statusEl.textContent = `✓ 快捷键 ${hotkey} 已就绪，去别的 App 选中文字后按一下试试`;
        statusEl.className = "hk-status ok";
      } else {
        statusEl.textContent = `✓ 已保存 ${hotkey}，请先完成上方「输入监控」授权`;
        statusEl.className = "hk-status ok";
      }
    }
    const acts = document.getElementById("hk-actions");
    if (acts) acts.style.display = "flex";
    return true;
  }

  function setupPermissionWizard() {
    const statusEl = document.getElementById("perm-status");
    const btnOpen = document.getElementById("perm-open");
    const btnCheck = document.getElementById("perm-check");

    async function refresh() {
      let st;
      try { st = await api().check_input_monitor_permission(); } catch { return; }
      if (!st || !statusEl) return;
      if (st.granted) {
        statusEl.className = "perm-status ok";
        statusEl.textContent = "✓ 已授权！现在可以在备忘录等任意 App 里用快捷键了";
        if (permPollTimer) { clearInterval(permPollTimer); permPollTimer = null; }
      } else {
        statusEl.className = "perm-status wait";
        statusEl.textContent = "⏳ 还没检测到授权 —— 点下面按钮打开设置，勾选 Skillless 后回来";
      }
    }

    if (btnOpen) {
      btnOpen.onclick = async () => {
        try { await api().request_input_monitor_access(); } catch {}
        if (statusEl) {
          statusEl.className = "perm-status wait";
          statusEl.textContent = "请在系统设置里打开 Skillless 开关，然后点「检测授权」或等几秒…";
        }
        if (!permPollTimer) permPollTimer = setInterval(refresh, 2000);
      };
    }
    if (btnCheck) btnCheck.onclick = refresh;

    refresh();
    if (!permPollTimer) permPollTimer = setInterval(refresh, 2500);
  }

  function setupHotkeyPresets() {
    document.querySelectorAll(".hk-preset").forEach((btn) => {
      btn.onclick = () => applyHotkeyPreset(btn.dataset.hk);
    });
  }

  async function setupHotkeyPrimary() {
    try {
      await api().enable_copy_mode();
      window._copyModeOnly = false;
    } catch {}
  }

  async function renderHotkey() {
    window._onboardingDemoOk = false;
    window._copyModeOnly = false;
    if (permPollTimer) { clearInterval(permPollTimer); permPollTimer = null; }

    stage.innerHTML = `
      <h2 class="title">用 ⌘C 弹胶囊</h2>
      <p class="lead">选中文字后按 <strong>⌘C</strong> 复制，Skillless 监听到剪贴板更新，自动弹出精简胶囊。</p>

      <div class="copy-primary-card">
        <h3>用法</h3>
        <ol class="copy-steps">
          <li>在任意 App 里<strong>选中一段文字</strong>（≥100 字）</li>
          <li>按 <kbd>⌘</kbd><kbd>C</kbd> 复制</li>
          <li>鼠标旁弹出精简胶囊</li>
        </ol>
      </div>

      <div class="perm-wizard" id="perm-wizard">
        <h3>先开「输入监控」权限</h3>
        <ol class="perm-steps">
          <li>点「一键开启权限」→ 自动跳转系统设置</li>
          <li>在列表里<strong>打开 Skillless 开关</strong></li>
          <li>看到绿灯后，去别的 App 按 ⌘C 试试</li>
        </ol>
        <div class="perm-actions">
          <button type="button" class="btn primary" id="perm-open">一键开启权限</button>
          <button type="button" class="btn ghost" id="perm-check">检测授权</button>
        </div>
        <div class="perm-status wait" id="perm-status">检测中…</div>
      </div>

      <div class="hk-card">
        <div class="hk-presets">
          <button type="button" class="hk-preset active" data-hk="${EASY_HOTKEY}">
            默认 · ⌘C
          </button>
        </div>
        <div class="hk-status ok" id="hk-status">快捷键 ⌘C 已设置</div>
      </div>

      <div class="try-card">
        <div class="tc-head">
          <span class="tc-step">试</span>
          <span>点按钮体验胶囊效果</span>
        </div>
        <pre class="tc-sample" id="tc-sample"></pre>
        <div class="tc-actions">
          <button type="button" class="btn primary big" id="tc-trigger">立即试精简 · 弹胶囊 →</button>
        </div>
        <div class="tc-note">
          <strong>演示模式</strong>：预制精简结果，不走真实 API。正式用时再去下一步配 Key。
        </div>
      </div>`;

    // 渲染示例文字
    try {
      const dt = await api().get_demo_text();
      document.getElementById("tc-sample").textContent = dt.text || "";
    } catch {}

    await setupHotkeyPrimary();
    setupPermissionWizard();
    await ensureDefaultHotkey();
    setupHotkeyPresets();
    setupTryDemo();

    clearActions();
    actionsEl.appendChild(btn("← 上一步", "ghost", goBack));
    actionsEl.appendChild(btn("继续 → AI 能力", "primary", goNext));
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
    let captureStartedAt = 0;
    let waitTimer = null;

    async function onCapturedKey(e) {
      if (!capturing) return;
      // 仅修饰键不算 —— 但要"消化"事件防止 WKWebView 触发其它行为
      const isMod = ["Control", "Alt", "Shift", "Meta", "Option", "Command", "OS"].includes(e.key);
      if (isMod) { e.preventDefault(); return; }

      // ESC 取消
      if (e.key === "Escape") {
        e.preventDefault();
        stop();
        return;
      }

      e.preventDefault();
      e.stopPropagation();

      const mods = [];
      if (e.ctrlKey)  mods.push("⌃");
      if (e.altKey)   mods.push("⌥");
      if (e.shiftKey) mods.push("⇧");
      if (e.metaKey)  mods.push("⌘");
      if (mods.length === 0) {
        // 纯单键不允许，必须带修饰键
        statusEl.textContent = "至少一个修饰键（⌃ / ⌥ / ⇧ / ⌘）+ 一个字母";
        statusEl.className = "hk-status err";
        return;
      }

      let key = (e.key || "").toUpperCase();
      if (key === " ") key = "SPACE";
      if (key.length > 1 && !["F1","F2","F3","F4","F5","F6","F7","F8","F9","F10","F11","F12","SPACE"].includes(key)) {
        // 不接受 "ARROWUP" / "TAB" / "ALTGRAPH" 等
        return;
      }
      const shortcut = mods.join("") + key;

      if (shortcut === "⇧⌘E") {
        statusEl.innerHTML =
          "⚠️ <strong>⇧⌘E</strong> 在「备忘录」里会被系统拿去<strong>标紫高亮</strong>，Skillless 收不到。建议换 <strong>⌃⌥E</strong>。";
        statusEl.className = "hk-status err";
        stop();
        return;
      }

      // 显式拦下被 macOS / 主流 App 强占的组合，避免用户白设
      const SYSTEM_RESERVED = new Set([
        "⌘C","⌘V","⌘X","⌘A","⌘Z","⌘S","⌘W","⌘Q","⌘N","⌘O","⌘P","⌘T","⌘R","⌘F",
        "⌘E","⌘D","⌘G","⌘H","⌘M","⌘L","⌘I","⌘B","⌘U",
        "⇧⌘E","⇧⌘H","⇧⌘K",
        "⌘ ", "⌘SPACE", "⌘TAB", "⌃SPACE",
      ]);
      if (SYSTEM_RESERVED.has(shortcut)) {
        statusEl.textContent = `「${shortcut}」被系统/常见 App 占用，换一组试试 —— 推荐点上面的「好按 · ⌃⌥E」`;
        statusEl.className = "hk-status err";
        return;
      }

      stopWaitTimer();
      const res = await api().set_input_hotkey(shortcut);
      if (res.ok) {
        hotkey = res.shortcut;
        showHotkey(hotkey);

        // 显示后续按钮
        const acts = document.getElementById("hk-actions");
        if (acts) acts.style.display = "flex";

        const warn = document.getElementById("hk-warn");
        if (res.listener_ok) {
          statusEl.textContent = `✓ 已保存并已开始监听：在任何 App 按一下 ${hotkey}，会用当前剪贴板内容弹胶囊`;
          statusEl.className = "hk-status ok";
          if (warn) warn.textContent = "";
        } else {
          statusEl.textContent = `✓ 已保存：${hotkey}（菜单栏 App 启动后会全局生效）`;
          statusEl.className = "hk-status ok";
          if (warn) {
            warn.innerHTML = `
              <span class="hk-warn-i">!</span>
              当前进程没拿到「输入监听」权限，所以现在按 ${hotkey} 还不会触发；
              点右边「打开输入监听设置」，把 <strong>Skillless / Python</strong> 勾上即可。`;
          }
        }
      } else {
        statusEl.textContent = `✗ ${res.error || "保存失败"}`;
        statusEl.className = "hk-status err";
      }
      stop();
    }

    function start() {
      if (capturing) return;
      capturing = true;
      captureStartedAt = Date.now();
      box.classList.add("capturing");
      txt.textContent = "按下你想要的组合键…（ESC 取消）";
      statusEl.textContent = "";
      statusEl.className = "hk-status";
      // 关键：用 capture phase 全局监听，WebKit 里 <button> 拿不到 focus
      document.addEventListener("keydown", onCapturedKey, true);
      // 3 秒还没按 → 提示"被系统占用？换一组"
      stopWaitTimer();
      waitTimer = setTimeout(() => {
        if (capturing) {
          statusEl.textContent = "没收到按键？可能这组合被系统/其他 App 占用，换一组试试";
          statusEl.className = "hk-status err";
        }
      }, 3500);
    }
    function stop() {
      if (!capturing) return;
      capturing = false;
      box.classList.remove("capturing");
      if (!hotkey) txt.textContent = "点这里录入…";
      document.removeEventListener("keydown", onCapturedKey, true);
      stopWaitTimer();
    }
    function stopWaitTimer() {
      if (waitTimer) { clearTimeout(waitTimer); waitTimer = null; }
    }

    box.onclick = (e) => {
      e.preventDefault();
      if (capturing) stop();
      else start();
    };
    // 点击空白处取消录入
    document.addEventListener("mousedown", (e) => {
      if (capturing && e.target !== box && !box.contains(e.target)) {
        stop();
      }
    }, true);

    // 还原推荐
    const dft = document.getElementById("hk-default");
    if (dft) dft.onclick = () => applyHotkeyPreset(EASY_HOTKEY);

  }

  function setupTryDemo() {
    const triggerBtn = document.getElementById("tc-trigger");
    let inFlight = false;

    triggerBtn.onclick = async () => {
      if (inFlight) return;
      inFlight = true;
      const originalText = triggerBtn.textContent;
      triggerBtn.disabled = true;
      triggerBtn.textContent = "正在弹起胶囊…";
      // trigger_capsule 内部会先 pbcopy 再 spawn 胶囊进程
      const res = await api().trigger_capsule();
      if (res && res.ok) {
        markDemoSuccess();
        triggerBtn.textContent = "✓ 演示胶囊已弹起，看鼠标旁";
        setTimeout(() => {
          triggerBtn.textContent = "再来一次 ↻";
          triggerBtn.disabled = false;
          inFlight = false;
        }, 2200);
      } else {
        triggerBtn.textContent = "✗ 失败：" + (res && res.error ? res.error : "未知");
        triggerBtn.classList.add("err");
        setTimeout(() => {
          triggerBtn.textContent = originalText;
          triggerBtn.classList.remove("err");
          triggerBtn.disabled = false;
          inFlight = false;
        }, 3500);
      }
    };
  }

  /* 本窗口内按快捷键 → 直接触发演示胶囊（不依赖全局输入监听权限） */
  function setupHotkeyDemoTrigger() {
    let busy = false;
    document.addEventListener("keydown", async (e) => {
      if (STEPS[stepIndex] !== "hotkey" || !hotkey || busy) return;
      const box = document.getElementById("hk-input");
      if (box && box.classList.contains("capturing")) return;
      const mods = [];
      if (e.ctrlKey) mods.push("⌃");
      if (e.altKey) mods.push("⌥");
      if (e.shiftKey) mods.push("⇧");
      if (e.metaKey) mods.push("⌘");
      let k = (e.key || "").toUpperCase();
      if (k === " ") k = "SPACE";
      const allowedFn = ["F1","F2","F3","F4","F5","F6","F7","F8","F9","F10","F11","F12","SPACE"];
      if (!(k.length === 1 || allowedFn.includes(k))) return;
      const combo = mods.join("") + k;
      if (combo !== hotkey) return;
      busy = true;
      try {
        const res = await api().trigger_capsule();
        if (res && res.ok) markDemoSuccess();
      } finally {
        busy = false;
      }
    }, true);
  }

  /* 实时诊断：每 0.7s 拉一次后端心跳，可视化告诉用户问题在哪一环 */
  function setupHotkeyDiag() {
    const box = document.getElementById("hk-diag");
    if (!box) return;
    const rowLocal = document.getElementById("hk-diag-local");
    const rowGlobal = document.getElementById("hk-diag-global");
    const rowMatch = document.getElementById("hk-diag-match");
    const hint = document.getElementById("hk-diag-hint");
    if (!rowLocal || !rowGlobal || !rowMatch) return;

    const setRow = (row, state, text) => {
      row.dataset.state = state;        // ok | wait | err | fresh
      row.querySelector(".hk-diag-text").textContent = text;
    };

    // JS 自己捕获本窗口 keydown —— 最直接，完全不依赖任何系统权限
    let lastLocalAt = 0;
    let lastLocalCombo = "";
    document.addEventListener("keydown", (e) => {
      lastLocalAt = Date.now();
      const mods = [];
      if (e.ctrlKey)  mods.push("⌃");
      if (e.altKey)   mods.push("⌥");
      if (e.shiftKey) mods.push("⇧");
      if (e.metaKey)  mods.push("⌘");
      let k = (e.key || "").toUpperCase();
      if (k === " ") k = "SPACE";
      const allowedFn = ["F1","F2","F3","F4","F5","F6","F7","F8","F9","F10","F11","F12","SPACE"];
      if (k.length === 1 || allowedFn.includes(k)) {
        lastLocalCombo = mods.join("") + k;
      }
    }, true);

    async function tick() {
      if (window._onboardingDemoOk) return;

      let d;
      try { d = await api().get_hotkey_diag(); } catch { return; }
      if (!d) return;

      if (!d.configured) {
        box.style.display = "none";
        return;
      }
      box.style.display = "block";

      const demoAt = d.demo_capsule_at || 0;
      if (demoAt > 0 && Date.now() / 1000 - demoAt < 30) {
        markDemoSuccess();
        return;
      }

      // ① 本窗口内监听：以 JS keydown 为准
      const localAgeMs = lastLocalAt > 0 ? Date.now() - lastLocalAt : -1;
      if (localAgeMs >= 0) {
        const ago = (localAgeMs / 1000).toFixed(1);
        const fresh = localAgeMs < 1500;
        const seen = lastLocalCombo ? `（最后一次：${lastLocalCombo}）` : "";
        setRow(rowLocal, fresh ? "fresh" : "ok",
          `① 本窗口内监听：${ago}s 前 ✓ ${seen}`);
      } else {
        setRow(rowLocal, "wait",
          `① 本窗口内监听：等待中…（在这个窗口里按一下 ${d.configured} —— 不需要任何权限）`);
      }

      // ② 全局监听（其他 App）：后端 source=global 才算
      const globalSeen = d.any_event && d.any_source === "global";
      if (globalSeen) {
        const ago = (d.any_age_ms / 1000).toFixed(1);
        const fresh = d.any_age_ms < 1500;
        setRow(rowGlobal, fresh ? "fresh" : "ok",
          `② 全局监听（其他 App）：${ago}s 前 ✓`);
      } else if (!d.listener_global) {
        setRow(rowGlobal, "wait",
          "② 全局监听（其他 App）：演示可跳过 —— 本窗口按键或点按钮即可");
      } else {
        setRow(rowGlobal, "wait",
          `② 全局监听（其他 App）：等待中…（切到 Safari/便签等任意 App，按 ${d.configured}）`);
      }

      // ③ 命中你设的组合（global 或 local 都算）
      if (d.match) {
        const ago = (d.match_age_ms / 1000).toFixed(1);
        const fresh = d.match_age_ms < 1500;
        setRow(rowMatch, fresh ? "fresh" : "ok",
          `③ 命中你的组合：${ago}s 前 ✓ 胶囊已经弹了`);
      } else {
        setRow(rowMatch, "wait", "③ 命中你的组合：等待中…");
      }

      // 综合建议
      const localOk = localAgeMs >= 0;
      if (localOk && lastLocalCombo && lastLocalCombo !== d.configured && !d.match) {
        hint.innerHTML = `你按了 <strong>${lastLocalCombo}</strong>，但跟你保存的
          <strong>${d.configured}</strong> 对不上 —— 上方重设为
          <strong>${lastLocalCombo}</strong>，或换一组重按。`;
        hint.className = "hk-diag-hint warn";
      } else if (!globalSeen && d.listener_global && localOk) {
        hint.innerHTML = `本窗口能收到按键 ✓。其他 App 里要用快捷键，再去开「输入监听」权限；<strong>演示不用管</strong>。`;
        hint.className = "hk-diag-hint";
      } else if (d.match) {
        hint.innerHTML = `全链路通 ✓ 胶囊已经弹了，你可以一直按 <strong>${d.configured}</strong> 复弹。`;
        hint.className = "hk-diag-hint ok";
      } else {
        hint.innerHTML = `先在<strong>这个窗口里</strong>按一下 <strong>${d.configured}</strong> ——
          ① 行会立刻变绿；这一步通了就说明 hotkey 字符串没错，然后再去别的 App 试。`;
        hint.className = "hk-diag-hint";
      }
    }

    tick();
    const id = setInterval(tick, 1500);
    window._hkDiagTimer && clearInterval(window._hkDiagTimer);
    window._hkDiagTimer = id;
  }

  /* ============================================================
   * Step 4 · API Key（可跳过：清楚说明有/无 Key 的差异）
   * ============================================================ */
  async function renderApi() {
    let status = { has_key: false, masked: "", platform_provided: false, free_tier: false };
    try {
      const r = await api().get_api_status();
      if (r && r.ok) status = r;
    } catch {}
    hasKey = status.has_key;

    if (status.platform_provided || status.free_tier) {
      stage.innerHTML = `
        <h2 class="title">AI 精简已内置 · 免配置</h2>
        <p class="lead">Skillless 已自带 AI 能力，<strong>不用申请、不用粘贴 API Key</strong>，复制就能精简归档。当前阶段免费给大家用。</p>
        <div class="api-builtin-card">
          <div class="api-builtin-badge">✓ 已就绪</div>
          <ul class="api-list">
            <li class="ok yes"><strong>① 选中就精简</strong> · ⌘C 复制即去口水、结构化</li>
            <li class="ok yes"><strong>② 一键归档</strong> · 满意一键写进 .md</li>
            <li class="ok yes"><strong>③ 越用越懂你</strong> · AI 读你的笔记后做关联补充</li>
          </ul>
          <p class="api-builtin-note">以后可能改成投币模式；现阶段直接点继续即可。</p>
        </div>
        <details class="api-advanced">
          <summary>高级 · 想用自己的 API Key？</summary>
          <div class="api-input-row" style="margin-top:10px">
            <input type="password" id="api-key-input" placeholder="粘贴 sk- 开头的 Key（可选）" autocomplete="off" />
            <button type="button" class="btn ghost" id="api-save">保存</button>
          </div>
          <div class="api-input-hint" id="api-status"></div>
        </details>`;
      const saveBtn = document.getElementById("api-save");
      if (saveBtn) {
        saveBtn.onclick = async () => {
          const v = (document.getElementById("api-key-input").value || "").trim();
          const statusEl = document.getElementById("api-status");
          if (!v) { statusEl.textContent = "留空即可，已用内置 AI"; return; }
          const res = await api().save_api(v);
          statusEl.textContent = res.ok ? `✓ 已切换为你自己的 Key` : `✗ ${res.error}`;
        };
      }
      clearActions();
      actionsEl.appendChild(btn("← 上一步", "ghost", goBack));
      actionsEl.appendChild(btn("继续 → 选文档", "primary", goNext));
      return;
    }

    stage.innerHTML = `
      <h2 class="title">配 DeepSeek API · 开启 AI 精简</h2>
      <p class="lead">精简、归档、提问都靠 AI。不配 Key 只能当高级剪贴板；配上 Key，三大能力才真正能用。</p>

      <div class="api-compare">
        <div class="api-col api-col-off">
          <div class="api-col-head">
            <span class="api-dot off">○</span>
            <span class="api-col-title">不配 Key</span>
            <span class="api-col-sub">高级剪贴板，只能存和看</span>
          </div>
          <p class="api-col-summary">复制自动存、能看历史、能手动写进 .md。但 AI 精简 / 提问全是摆设，点不了。</p>
          <ul class="api-list">
            <li class="ok">复制即自动入库 · 永不丢</li>
            <li class="ok">历史里翻回过去复制的任何东西</li>
            <li class="ok">手动把原文写进 .md</li>
            <li class="no"><strong>① 选中就精简</strong> · 去口水 / 结构化</li>
            <li class="no"><strong>② 精简后归档</strong> · AI 整理再写入</li>
            <li class="no"><strong>③ 基于 .md 提问</strong> · 按笔记上下文回答</li>
          </ul>
        </div>
        <div class="api-col api-col-on">
          <div class="api-col-head">
            <span class="api-dot on">✓</span>
            <span class="api-col-title">配 Key（推荐）</span>
            <span class="api-col-sub">精简 + 归档 + 提问 全开</span>
          </div>
          <p class="api-col-summary"><strong>上面都能用，三大核心能力解锁</strong>：</p>
          <ul class="api-list">
            <li class="ok yes"><strong>① 选中就精简</strong> · 复制即去口水、结构化</li>
            <li class="ok yes"><strong>② 精简后归档</strong> · 满意一键写进 .md</li>
            <li class="ok yes"><strong>③ 基于 .md 提问</strong> · 选中文字 + 笔记上下文问答</li>
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
      <h2 class="title">最后一步：精简后归档到哪？</h2>
      <p class="lead">选一个默认 .md —— 精简满意后点「归档」，内容会追加到这里。
        <strong>它所在的文件夹</strong>就是你的知识库，Agent 加进来就能基于 .md 提问。<br />
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
    const nextBtn = btn("继续 → 看知识库", "primary", goNext, { disabled: !picked, id: "btn-finish" });
    actionsEl.appendChild(nextBtn);
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
    refine: renderRefine,
    how: renderHow,
    hotkey: renderHotkey,
    api: renderApi,
    pick: renderPick,
    kb: renderKb,
  };

  async function renderKb() {
    let summary = {};
    try { summary = (await api().get_summary()) || {}; } catch {}
    const mdLabel = escapeHtml(summary.default_display || summary.default_md || "（未设置）");
    const kbLabel = escapeHtml(summary.kb_display || summary.kb_path || "（未设置）");
    const filled = !!summary.default_md;

    stage.innerHTML = `
      <h2 class="title">越用越懂你：AI 会读你的笔记</h2>
      <p class="lead">
        每次精简，AI 都会顺手扫一下你这个 .md，<strong>主动提示重复、补出遗漏的相关知识</strong>——
        像一个懂你工作习惯的同事帮你整理。先看个三列对比 👇
      </p>

      <div class="kb-demo">
        <div class="kb-demo-col kb-col-src">
          <div class="kb-col-head">
            <span class="kb-col-tag">① 你复制的</span>
            <span class="kb-col-sub">口语化原文</span>
          </div>
          <div class="kb-col-body">
            <p>今天测了下动态徽章 AB，推全数据是 +5,116 单/天。分事业部看了，外卖闪购效果不一样。负责人张三李四王五，4 月开始 6 月结束。后面还有动态门店头图的实验。</p>
          </div>
        </div>

        <div class="kb-demo-col kb-col-kb">
          <div class="kb-col-head">
            <span class="kb-col-tag">② 知识库里已有</span>
            <span class="kb-col-sub">顺手买信息.md · 片段</span>
          </div>
          <div class="kb-col-body kb-col-mono">
            <div class="kb-md-line">## 实验</div>
            <div class="kb-md-line">- 动态徽章项目（4 月立项）</div>
            <div class="kb-md-line">- 业务方：李四 / 王五</div>
            <div class="kb-md-line">## 埋点</div>
            <div class="kb-md-line">- ab_id, exp_group, biz_unit</div>
            <div class="kb-md-line">## 版本</div>
            <div class="kb-md-line">- v3.2 推全计划</div>
          </div>
        </div>

        <div class="kb-demo-col kb-col-out">
          <div class="kb-col-head">
            <span class="kb-col-tag primary">③ AI 输出</span>
            <span class="kb-col-sub">精简 + 旁白补充</span>
          </div>
          <div class="kb-col-body">
            <div class="kb-out-section">
              <h4>动态徽章 AB · 推全</h4>
              <ul>
                <li><strong>结论</strong>：推全 +5,116 单/天</li>
                <li><strong>分事业部</strong>：外卖、闪购效果不一致</li>
                <li><strong>人员</strong>：张三、李四、王五</li>
                <li><strong>时间</strong>：4 月 → 6 月</li>
                <li><strong>后续</strong>：动态门店头图实验（待启）</li>
              </ul>
            </div>
            <div class="kb-out-aside">
              <div class="kb-aside-head">📚 与你的笔记</div>
              <div class="kb-aside-line">
                <span class="kb-aside-tag warn">⚠️ 似乎重复</span>
                <span>动态徽章项目你 4 月已立项，这次是有数据了</span>
              </div>
              <div class="kb-aside-line">
                <span class="kb-aside-tag tip">💡 旁白补充</span>
                <span>埋点 <code>biz_unit</code> 刚好对应这次的分事业部维度</span>
              </div>
              <div class="kb-aside-line">
                <span class="kb-aside-tag tip">💡 旁白补充</span>
                <span>张三是这次新出现的人员，老笔记里没记过</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="kb-current">
        <div class="kb-row"><span class="kb-k">默认 .md</span><span class="kb-v">${mdLabel}</span></div>
        <div class="kb-row"><span class="kb-k">知识库目录</span><span class="kb-v">${kbLabel}</span></div>
        <div class="kb-hint">
          ${filled
            ? `<strong>胶囊右下角会出现「已参考你的笔记」</strong>的小提示，看到它就说明 AI 读了上下文。`
            : `还没设默认 .md？点「上一步」回到第 6 步选一个。`}
          <br/>胶囊里点 <strong>⚙ 或 ›</strong>，菜单栏点 <strong>📥 → 打开后台</strong>，可随时切换、看历史。
        </div>
      </div>

      <div class="kb-tips">
        <h4>用得越多越懂你的小习惯</h4>
        <ul>
          <li><strong>同一类内容写在同一个 .md</strong>：会议纪要 / 灵感 / 学习笔记分开放，AI 旁白更准。</li>
          <li><strong>顶部写一段「这是什么文档」</strong>：AI 读到后自动按场景调整输出。</li>
          <li><strong>不用强求完整</strong>：旁白只在确实有重复或可补时才出现，干净不啰嗦。</li>
        </ul>
      </div>`;

    clearActions();
    actionsEl.appendChild(btn("← 上一步", "ghost", goBack));
    actionsEl.appendChild(btn("完成 · 开始使用", "primary", doFinish));
  }

  function render() {
    renderDots();
    const name = STEPS[stepIndex];
    const fn = renderers[name];
    if (fn) fn();
  }

  document.getElementById("btn-cancel").onclick = onCancel;
  document.addEventListener("visibilitychange", () => {
    document.body.classList.toggle("onboarding-paused", document.hidden);
  });
  waitForApi().then(() => render());
})();
