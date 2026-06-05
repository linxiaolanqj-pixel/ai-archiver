/**
 * AI Archiver 内嵌引导 — 步进与 pywebview API
 */
(function () {
  const STEPS = [
    "welcome",
    "kb",
    "md",
    "api",
    "demo",
    "agent",
    "menubar",
    "done",
  ];

  let stepIndex = 0;
  let meta = { api_keys_url: "", demo_len: 0, has_key: false };
  let kbCreated = false;
  let mdPicked = false;
  let demoDone = false;

  const stage = document.getElementById("stage");
  const dotsEl = document.getElementById("dots");
  const actionsEl = document.getElementById("actions");

  function api() {
    return window.pywebview && window.pywebview.api;
  }

  function waitForApi() {
    return new Promise((resolve) => {
      const tick = () => {
        if (api()) resolve(api());
        else setTimeout(tick, 50);
      };
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

  function btn(label, cls, onclick, disabled) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = `btn ${cls}`;
    b.textContent = label;
    if (disabled) b.disabled = true;
    b.onclick = onclick;
    return b;
  }

  function clearActions() {
    actionsEl.innerHTML = "";
  }

  function goNext() {
    if (stepIndex < STEPS.length - 1) {
      stepIndex += 1;
      render();
    }
  }

  function goBack() {
    if (stepIndex > 0) {
      stepIndex -= 1;
      render();
    }
  }

  async function onCancel() {
    const a = api();
    if (a) await a.cancel();
  }

  /* —— 各屏内容 —— */

  function renderWelcome() {
    stage.innerHTML = `
      <h2 class="title">复制 → 归档，少掉 7 步</h2>
      <p class="lead">左边是你现在的折腾；右边是装好归档器之后。全程约 1 分钟。</p>
      <div class="compare-grid">
        <div class="card old">
          <span class="badge">老流程 · 7 步</span>
          <h3>😵 每次都要折腾</h3>
          <div class="step"><span class="num">1</span><span class="txt">复制群聊 / 会议内容</span></div>
          <div class="step"><span class="num">2</span><span class="txt">打开龙虾 / Cursor</span></div>
          <div class="step"><span class="num">3</span><span class="txt">粘贴 + 写 prompt</span></div>
          <div class="step"><span class="num">4</span><span class="txt">等 AI 输出</span></div>
          <div class="step"><span class="num">5</span><span class="txt">再复制结果</span></div>
          <div class="step"><span class="num">6</span><span class="txt">找到 md 文件</span></div>
          <div class="step"><span class="num">7</span><span class="txt">粘贴进去… 知识库还是空的</span></div>
        </div>
        <div class="card new">
          <span class="badge">新流程 · 2 步</span>
          <h3>✨ 复制就完事</h3>
          <div class="step"><span class="num">1</span><span class="txt"><strong>Cmd+C</strong> 复制一段文字</span></div>
          <div class="step"><span class="num">2</span><span class="txt">点 <strong>📥 归档</strong> → 写入默认 md</span></div>
          <div class="step"><span class="num">🎉</span><span class="txt">Agent 能读到你的项目记忆</span></div>
        </div>
      </div>`;
    clearActions();
    actionsEl.appendChild(btn("开始设置 →", "btn-primary", goNext));
  }

  function renderKb() {
    stage.innerHTML = `
      <h2 class="title">给知识库起个名字</h2>
      <p class="lead">会自动在 ~/knowledge/ 下创建文件夹，不用自己建。</p>
      <div class="field">
        <label>知识库名称</label>
        <input type="text" id="kb-name" value="我的知识库" placeholder="例如：顺手买、个人笔记" />
      </div>
      <p class="hint" id="kb-hint"></p>`;
    clearActions();
    actionsEl.appendChild(btn("← 上一步", "btn-secondary", goBack));
    actionsEl.appendChild(
      btn("创建并继续 →", "btn-primary", async () => {
        const name = document.getElementById("kb-name").value.trim();
        const hint = document.getElementById("kb-hint");
        setLoading(true);
        const res = await api().create_kb(name);
        setLoading(false);
        if (!res.ok) {
          hint.textContent = res.error || "创建失败";
          hint.style.color = "#ff9eb0";
          return;
        }
        kbCreated = true;
        hint.textContent = `已创建：${res.path}`;
        hint.style.color = "#7dffb2";
        setTimeout(goNext, 400);
      })
    );
  }

  function renderMd() {
    stage.innerHTML = `
      <h2 class="title">选一个默认归档文档</h2>
      <p class="lead">日常复制的内容会默认写入这个 .md。下一步会打开 Finder，点选即可。</p>
      <div class="pick-row">
        <button type="button" class="btn btn-secondary" id="pick-existing">📄 选择已有 .md</button>
        <button type="button" class="btn btn-secondary" id="pick-new">✨ 新建 .md</button>
      </div>
      <div class="picked" id="picked-md"></div>
      <p class="hint">可在子文件夹里选；演示和日常归档都用这一份。</p>`;
    const pickedEl = document.getElementById("picked-md");
    document.getElementById("pick-existing").onclick = async () => {
      setLoading(true);
      const res = await api().pick_existing_md();
      setLoading(false);
      if (res.cancelled) return;
      if (!res.ok) {
        pickedEl.classList.add("show");
        pickedEl.textContent = res.error || "未选择";
        pickedEl.style.borderColor = "#5c3d48";
        pickedEl.style.color = "#ffc8d4";
        return;
      }
      mdPicked = true;
      pickedEl.classList.add("show");
      pickedEl.textContent = `已选：${res.label}`;
      pickedEl.style.borderColor = "";
      pickedEl.style.color = "";
      enableMdNext();
    };
    document.getElementById("pick-new").onclick = async () => {
      setLoading(true);
      const res = await api().pick_new_md();
      setLoading(false);
      if (res.cancelled) return;
      if (!res.ok) {
        pickedEl.classList.add("show");
        pickedEl.textContent = res.error || "未创建";
        return;
      }
      mdPicked = true;
      pickedEl.classList.add("show");
      pickedEl.textContent = `已选：${res.label}`;
      enableMdNext();
    };
    clearActions();
    const nextBtn = btn("继续 →", "btn-primary", goNext, true);
    nextBtn.id = "md-next";
    actionsEl.appendChild(btn("← 上一步", "btn-secondary", goBack));
    actionsEl.appendChild(nextBtn);

    function enableMdNext() {
      const n = document.getElementById("md-next");
      if (n) n.disabled = false;
    }
  }

  function renderApi() {
    stage.innerHTML = `
      <h2 class="title">DeepSeek API Key（可选）</h2>
      <p class="lead">有 Key 可走 AI 梳理；没有也能用「原文追加」，稍后在菜单里再填。</p>
      <div class="field">
        <label>API Key（sk- 开头）</label>
        <input type="password" id="api-key" placeholder="粘贴 sk-..." autocomplete="off" />
      </div>
      <p class="hint"><a href="#" id="open-keys">在浏览器打开申请页</a></p>`;
    document.getElementById("open-keys").onclick = (e) => {
      e.preventDefault();
      api().open_api_keys_page();
    };
    clearActions();
    actionsEl.appendChild(btn("← 上一步", "btn-secondary", goBack));
    actionsEl.appendChild(
      btn("跳过", "btn-secondary", async () => {
        await api().skip_api_key();
        goNext();
      })
    );
    actionsEl.appendChild(
      btn("保存并继续 →", "btn-primary", async () => {
        const key = document.getElementById("api-key").value;
        setLoading(true);
        const res = key ? await api().save_api_key(key) : await api().skip_api_key();
        setLoading(false);
        if (!res.ok) {
          alert(res.error || "保存失败");
          return;
        }
        goNext();
      })
    );
  }

  function renderDemo() {
    stage.innerHTML = `
      <h2 class="title">现场演示（推荐）</h2>
      <p class="lead">用一段模拟群聊走一遍真实写入，约 ${meta.demo_len} 字。</p>
      <div class="demo-box" id="demo-snippet">加载中…</div>
      <button type="button" class="btn btn-secondary" id="demo-textedit" style="margin-bottom:8px">在 TextEdit 查看全文</button>
      <div class="demo-status" id="demo-status"></div>`;
    api()
      .get_demo_preview()
      .then((p) => {
        const el = document.getElementById("demo-snippet");
        if (el) el.textContent = `${p.summary}\n\n${p.snippet}`;
      });
    document.getElementById("demo-textedit").onclick = () => api().open_demo_in_textedit();
    clearActions();
    actionsEl.appendChild(btn("← 上一步", "btn-secondary", goBack));
    actionsEl.appendChild(btn("跳过演示", "btn-secondary", goNext));
    actionsEl.appendChild(
      btn("开始写入演示 →", "btn-primary", async () => {
        const st = document.getElementById("demo-status");
        st.className = "demo-status";
        st.textContent = "正在写入，请稍候…";
        setLoading(true);
        await api().prepare_demo_clipboard();
        const res = await api().run_demo();
        setLoading(false);
        if (!res.ok) {
          st.className = "demo-status err";
          st.textContent = res.message || res.error || "演示失败，可跳过";
          return;
        }
        demoDone = true;
        st.textContent = `✅ ${res.message}（${res.mode}）`;
        clearActions();
        actionsEl.appendChild(
          btn("打开文档", "btn-secondary", () => api().open_demo_result())
        );
        actionsEl.appendChild(btn("继续 →", "btn-primary", goNext));
      })
    );
  }

  function renderAgent() {
    const beforeText =
      "一般需要关注灰度节奏、监控指标、回滚方案……\n（泛泛而谈，记不住你会议里的数字和人名。）";
    const afterText =
      "根据你刚归档的记录：\n· v2 下周三灰度 30%\n· KPI 加购 3%→5%\n· @李四 周五前补埋点\n· 新人券分歧下周复盘\n（像带了项目秘书 🦞）";
    stage.innerHTML = `
      <h2 class="title">同一个问题，Agent 差在哪？</h2>
      <p class="lead">把知识库文件夹加进 Cursor 工作区，龙虾就能读到你的 md。</p>
      <div class="agent-grid">
        <div class="panel before">
          <div class="label">❌ 知识库是空的</div>
          <div class="q">顺手买 v2 上线要注意什么？</div>
          <div class="a" id="agent-before"></div>
        </div>
        <div class="panel after">
          <div class="label">✅ 有 Markdown 知识库</div>
          <div class="q">顺手买 v2 上线要注意什么？</div>
          <div class="a" id="agent-after"></div>
        </div>
      </div>`;
    typewriter(document.getElementById("agent-before"), beforeText, 18);
    setTimeout(() => typewriter(document.getElementById("agent-after"), afterText, 14), 600);
    clearActions();
    actionsEl.appendChild(btn("← 上一步", "btn-secondary", goBack));
    actionsEl.appendChild(btn("懂了，继续 →", "btn-primary", goNext));
  }

  function typewriter(el, text, ms) {
    if (!el) return;
    let i = 0;
    const cur = document.createElement("span");
    cur.className = "cursor";
    el.textContent = "";
    el.appendChild(cur);
    const t = setInterval(() => {
      if (i < text.length) {
        el.insertBefore(document.createTextNode(text[i]), cur);
        i += 1;
      } else {
        cur.remove();
        clearInterval(t);
      }
    }, ms);
  }

  function renderMenubar() {
    stage.innerHTML = `
      <h2 class="title">日常从这里开始</h2>
      <p class="lead">菜单栏在屏幕<strong>右上角</strong>。若看不见 📥，按住 <strong>Cmd</strong> 拖动其它图标让出位置。</p>
      <div class="menubar-demo">
        <div class="fake-menubar">
          <div class="menu-icons">
            <span>Wi‑Fi</span>
            <span>🔋</span>
            <span class="archiver">📥 归档</span>
          </div>
        </div>
        <div class="arrow-callout">
          <span class="arrow-down">↑</span>
          复制文字后，点 <strong>📥 归档</strong> 即可写入默认文档
        </div>
      </div>`;
    clearActions();
    actionsEl.appendChild(btn("← 上一步", "btn-secondary", goBack));
    actionsEl.appendChild(btn("记住了 →", "btn-primary", goNext));
  }

  async function renderDone() {
    const s = await api().get_summary();
    stage.innerHTML = `
      <div class="done-hero">
        <div class="emoji">🎊</div>
        <h2 class="title">全部完成</h2>
        <p class="lead">现在起复制 ≥100 字会询问是否归档（可在菜单里改）。</p>
        <ul class="summary-list">
          <li>知识库：${s.kb_name || "—"}</li>
          <li>默认文档：${s.default_md || "—"}</li>
          <li>API Key：${s.has_key ? "已配置" : "未配置（原文模式）"}</li>
          <li>演示：${s.demo_ran ? "已跑通 ✅" : "已跳过"}</li>
        </ul>
      </div>`;
    clearActions();
    actionsEl.appendChild(
      btn("开始使用 🦞", "btn-primary", async () => {
        setLoading(true);
        const res = await api().finish();
        setLoading(false);
        if (!res.ok) alert(res.error || "保存失败");
      })
    );
  }

  const renderers = {
    welcome: renderWelcome,
    kb: renderKb,
    md: renderMd,
    api: renderApi,
    demo: renderDemo,
    agent: renderAgent,
    menubar: renderMenubar,
    done: renderDone,
  };

  function render() {
    renderDots();
    const name = STEPS[stepIndex];
    const fn = renderers[name];
    if (fn) fn();
  }

  document.getElementById("btn-cancel").onclick = onCancel;

  waitForApi().then(async (a) => {
    meta = await a.get_meta();
    render();
  });
})();
