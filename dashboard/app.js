(function () {
  const root = document.getElementById("content");
  const toast = document.getElementById("toast");

  function api() {
    return window.pywebview && window.pywebview.api;
  }
  function waitForApi() {
    return new Promise((r) => {
      const tick = () => (api() ? r(api()) : setTimeout(tick, 50));
      tick();
    });
  }

  let toastTimer = 0;
  function showToast(msg) {
    toast.textContent = msg;
    toast.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove("show"), 1800);
  }

  function applyTheme(theme) {
    document.body.classList.toggle("theme-dark", theme === "dark");
  }

  // 极简 md → html：只处理 **bold**、- list、段落
  function mdToHtml(md) {
    if (!md) return "";
    let html = escapeHtml(md);
    html = html.replace(/\*\*([^*\n]+?)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/`([^`\n]+?)`/g, "<code>$1</code>");
    const lines = html.split("\n");
    const out = [];
    let inList = false;
    for (const ln of lines) {
      const m = ln.match(/^[-•]\s+(.+)$/);
      if (m) {
        if (!inList) { out.push("<ul>"); inList = true; }
        out.push("<li>" + m[1] + "</li>");
      } else {
        if (inList) { out.push("</ul>"); inList = false; }
        if (ln.trim()) out.push("<p>" + ln + "</p>");
      }
    }
    if (inList) out.push("</ul>");
    return out.join("");
  }

  function fmtRelTime(ts) {
    if (!ts) return "";
    const diff = Date.now() / 1000 - ts;
    if (diff < 60) return "刚刚";
    if (diff < 3600) return Math.floor(diff / 60) + " 分钟前";
    if (diff < 86400) return Math.floor(diff / 3600) + " 小时前";
    return fmtTime(ts);
  }

  function escapeHtml(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function comboFromEvent(e) {
    const mods = [];
    if (e.ctrlKey) mods.push("⌃");
    if (e.altKey) mods.push("⌥");
    if (e.shiftKey) mods.push("⇧");
    if (e.metaKey) mods.push("⌘");
    let key = e.key || "";
    if (["Control", "Alt", "Shift", "Meta"].includes(key)) return "";
    if (key === "Escape") key = "ESC";
    else if (key === "Enter") key = "↩";
    else if (key.length === 1) key = key.toUpperCase();
    else return "";
    if (!mods.length) return "";
    return mods.join("") + key;
  }

  function fmtTime(ts) {
    if (!ts) return "";
    const d = new Date(ts * 1000);
    const now = new Date();
    const sameDay =
      d.getFullYear() === now.getFullYear() &&
      d.getMonth() === now.getMonth() &&
      d.getDate() === now.getDate();
    const hh = String(d.getHours()).padStart(2, "0");
    const mm = String(d.getMinutes()).padStart(2, "0");
    if (sameDay) return `今天 ${hh}:${mm}`;
    return `${d.getMonth() + 1}/${d.getDate()} ${hh}:${mm}`;
  }

  /* ====== Panel 容器 ====== */
  root.innerHTML = `
    <section data-panel="home" class="panel"></section>
    <section data-panel="history" class="panel" hidden></section>
    <section data-panel="dict" class="panel" hidden></section>
    <section data-panel="hotkey" class="panel" hidden></section>
  `;
  const panels = {
    home: root.querySelector('[data-panel="home"]'),
    history: root.querySelector('[data-panel="history"]'),
    dict: root.querySelector('[data-panel="dict"]'),
    hotkey: root.querySelector('[data-panel="hotkey"]'),
  };

  // 每个 panel 是否已加载过（避免重复 RPC）
  const loaded = { home: false, history: false, dict: false, hotkey: false };

  /* ====== 首页 ====== */
  async function renderHome(force = false) {
    if (!force && loaded.home) return;
    if (!loaded.home) panels.home.innerHTML = `<div class="loading">加载中…</div>`;
    const data = await api().get_overview();
    applyTheme(data.app_theme || "light");
    const s = data.stats;
    const last = data.last_record || {};
    const def = data.default_target;
    const defDisplay = data.default_target_display || def || "";
    panels.home.innerHTML = `
      <div class="stats-grid">
        <div class="stat-card"><div class="label">累计字数</div><div class="value">${s.chars.toLocaleString()}</div><div class="sub">字</div></div>
        <div class="stat-card"><div class="label">已归档</div><div class="value">${s.archived}</div><div class="sub">条</div></div>
        <div class="stat-card"><div class="label">节省时间</div><div class="value">${s.saved_hhmm}</div><div class="sub">按 1 条/分钟</div></div>
        <div class="stat-card"><div class="label">历史条目</div><div class="value">${s.count}</div><div class="sub">总复制</div></div>
      </div>

      <div class="card default-doc-card">
        <h3>默认归档文档 <span class="hint">所有复制即归档 / 胶囊浮层 / 一键归档都写入这里</span></h3>
        ${
          def
            ? `<div class="default-doc-row">
                 <div class="default-doc-path" data-act="open-def" title="${escapeHtml(data.default_target_path || def)}（点击在 Finder 中打开）">${escapeHtml(defDisplay)}</div>
                 <button class="btn" data-act="change-def">更换…</button>
                 <button class="btn" data-act="new-def">新建…</button>
               </div>`
            : `<div class="default-doc-row">
                 <div class="default-doc-empty">尚未设置默认归档文档</div>
                 <button class="btn btn-primary" data-act="change-def">选择…</button>
                 <button class="btn" data-act="new-def">新建…</button>
               </div>`
        }
      </div>

      <div class="card memory-card" id="memory-card">
        <h3>
          <span>今日 memory</span>
          <button class="btn-mini" id="btn-memory-regen" hidden>重新生成</button>
        </h3>
        <div class="memory-body" id="memory-body">
          <div class="memory-loading">读取中…</div>
        </div>
      </div>

      <div class="home-bottom">
        <div class="card">
          <h3>最后一次复制</h3>
          ${
            last.ts
              ? `<div class="last-meta">${fmtTime(last.ts)} · ${escapeHtml(last.type || "text")}${last.len ? " · " + last.len + " 字" : ""}</div>
                 ${
                   last.type === "image"
                     ? `<img src="${escapeHtml(last.img_url || "")}" class="last-img"/>`
                     : `<div class="last-preview">${escapeHtml(last.preview || "")}</div>`
                 }`
              : `<div class="empty">还没有任何复制记录</div>`
          }
        </div>

        <div class="card">
          <h3>常用文档 <span class="hint">按归档次数排序</span></h3>
          ${
            data.favorites.length
              ? `<div class="fav-list">${data.favorites
                  .map((f) => `<div title="${escapeHtml(f.raw || f.display || "")}">· ${escapeHtml(f.display || f.raw || "")}</div>`)
                  .join("")}</div>`
              : `<div class="empty">暂无常用，去归档几次就有了</div>`
          }
        </div>

        <div class="card">
          <h3>主题 <span class="hint">同时作用于胶囊浮层与后台</span></h3>
          <div class="segment" data-act="theme-seg">
            <button data-theme="light" class="${(data.app_theme || "light") === "light" ? "active" : ""}">浅色</button>
            <button data-theme="dark" class="${data.app_theme === "dark" ? "active" : ""}">深色</button>
          </div>
        </div>
      </div>
    `;
    loaded.home = true;
    // 异步加载 memory（不阻塞首页其它内容）
    loadMemoryCard();
  }

  async function loadMemoryCard(forceRegen = false) {
    const body = document.getElementById("memory-body");
    const btn = document.getElementById("btn-memory-regen");
    if (!body) return;

    if (forceRegen) {
      body.innerHTML = `<div class="memory-loading"><span class="dot-spin"></span>AI 总结中… 通常 5–15 秒</div>`;
      btn.hidden = true;
      const r = await api().regen_today_memory();
      if (r.ok) {
        renderMemory(r);
      } else {
        body.innerHTML = `<div class="memory-empty">${escapeHtml(r.error || "生成失败")}</div>`;
        btn.hidden = false;
        btn.textContent = "重试";
      }
      return;
    }

    const stat = await api().memory_stats();
    if (stat.cached) {
      renderMemory(stat);
    } else if (stat.today_records === 0) {
      body.innerHTML = `<div class="memory-empty">今天还没复制任何文字，复制几条之后再来。</div>`;
      btn.hidden = true;
    } else {
      body.innerHTML = `
        <div class="memory-empty">
          今天已记录 <strong>${stat.today_records}</strong> 条复制内容
          <button class="btn btn-primary memory-gen" data-act="memory-gen">生成今日 memory</button>
        </div>`;
      btn.hidden = true;
    }
  }

  function renderMemory(r) {
    const body = document.getElementById("memory-body");
    const btn = document.getElementById("btn-memory-regen");
    body.innerHTML = `
      <div class="memory-content">${mdToHtml(r.content || "")}</div>
      <div class="memory-meta">基于 ${r.source_count} 条 · ${fmtRelTime(r.generated_ts)}生成</div>
    `;
    btn.hidden = false;
    btn.textContent = "重新生成";
  }

  // 事件委托：home 点击
  panels.home.addEventListener("click", async (e) => {
    // memory 生成 / 重新生成
    if (e.target.closest("#btn-memory-regen") || e.target.closest("[data-act=memory-gen]")) {
      loadMemoryCard(true);
      return;
    }
    // 主题 segment
    const seg = e.target.closest("[data-act=theme-seg] [data-theme]");
    if (seg) {
      const r = await api().update_app_theme(seg.dataset.theme);
      if (r && r.ok) {
        seg.parentElement.querySelectorAll("[data-theme]").forEach((b) => {
          b.classList.toggle("active", b.dataset.theme === r.theme);
        });
        applyTheme(r.theme);
        showToast("主题：" + (r.theme === "dark" ? "深色" : "浅色"));
      }
      return;
    }

    const t = e.target.closest("[data-act]");
    if (!t) return;
    const act = t.dataset.act;
    if (act === "open-def") api().open_default_target();
    else if (act === "open-kb") {
      api().open_kb();
    } else if (act === "change-def") {
      const r = await api().pick_default_target();
      if (r.ok) {
        showToast("已设为：" + (r.default_target_display || r.default_target));
        renderHome(true);
      } else if (!r.cancelled) {
        showToast("更换失败：" + (r.error || "未知"));
      }
    } else if (act === "new-def") {
      const r = await api().create_default_target();
      if (r.ok) {
        showToast("已创建并设为默认：" + r.default_target);
        renderHome(true);
      } else if (!r.cancelled) {
        showToast("创建失败");
      }
    }
  });

  /* ====== 历史 ====== */
  const HISTORY_PAGE = 50;
  let historyFilter = null;
  let historyOffset = 0;
  let historyTotal = 0;
  let historyDom = null; // 缓存外壳

  async function renderHistory(force = false) {
    if (!force && loaded.history) return;
    if (!historyDom) {
      panels.history.innerHTML = `
        <h2 class="page-title">📜 历史记录</h2>
        <p class="page-lead">最近的剪贴板（按时间倒序），文字和图片都在。</p>
        <div class="filter-bar" id="hist-filter"></div>
        <div class="history-list" id="hist-list"><div class="loading">加载中…</div></div>
        <div class="load-more-wrap"><button class="btn" id="hist-more" hidden>加载更多</button></div>
      `;
      historyDom = {
        filter: panels.history.querySelector("#hist-filter"),
        list: panels.history.querySelector("#hist-list"),
        more: panels.history.querySelector("#hist-more"),
      };

      // 事件委托：所有 list 内点击走这里
      historyDom.list.addEventListener("click", onHistoryListClick);

      historyDom.filter.addEventListener("click", (e) => {
        const b = e.target.closest("[data-filter]");
        if (!b) return;
        const f = b.dataset.filter || null;
        if (f === historyFilter) return;
        historyFilter = f;
        historyOffset = 0;
        renderFilter();
        loadFirstPage();
      });

      historyDom.more.addEventListener("click", loadMore);

      const clearBtn = document.createElement("button");
      clearBtn.textContent = "清空历史";
      clearBtn.className = "danger-link";
      clearBtn.onclick = async () => {
        if (!confirm("确认清空所有历史？图片文件也会一并删除。")) return;
        await api().clear_history();
        showToast("已清空");
        historyOffset = 0;
        loadFirstPage();
      };
      historyDom.filter._clearBtn = clearBtn;
    }

    renderFilter();
    await loadFirstPage();
    loaded.history = true;
  }

  function renderFilter() {
    const btn = (key, label) =>
      `<button type="button" data-filter="${key ?? ""}" class="${historyFilter === key ? "active" : ""}">${label}</button>`;
    historyDom.filter.innerHTML = `
      ${btn(null, "全部")}${btn("text", "文字")}${btn("image", "图片")}
      <div class="spacer"></div>
    `;
    historyDom.filter.appendChild(historyDom.filter._clearBtn);
  }

  async function loadFirstPage() {
    historyDom.list.innerHTML = `<div class="loading">加载中…</div>`;
    historyDom.more.hidden = true;
    historyOffset = 0;
    const r = await api().list_history(historyFilter, HISTORY_PAGE, 0);
    historyTotal = r.total || 0;
    if (!r.items || r.items.length === 0) {
      historyDom.list.innerHTML = `<div class="empty">还没有历史记录</div>`;
      return;
    }
    historyDom.list.innerHTML = r.items.map(renderHistoryItem).join("");
    historyOffset = r.items.length;
    historyDom.more.hidden = historyOffset >= historyTotal;
    historyDom.more.textContent = `加载更多（已显示 ${historyOffset} / ${historyTotal}）`;
  }

  async function loadMore() {
    historyDom.more.disabled = true;
    historyDom.more.textContent = "加载中…";
    const r = await api().list_history(historyFilter, HISTORY_PAGE, historyOffset);
    if (r.items && r.items.length) {
      historyDom.list.insertAdjacentHTML("beforeend", r.items.map(renderHistoryItem).join(""));
      historyOffset += r.items.length;
    }
    historyTotal = r.total || historyTotal;
    historyDom.more.disabled = false;
    historyDom.more.hidden = historyOffset >= historyTotal;
    historyDom.more.textContent = `加载更多（已显示 ${historyOffset} / ${historyTotal}）`;
  }

  async function onHistoryListClick(e) {
    const b = e.target.closest("[data-action]");
    if (!b) return;
    const action = b.dataset.action;
    if (action === "copy") {
      const r = await api().get_record_text(Number(b.dataset.ts));
      if (!r.ok) return showToast("内容已不在");
      await api().copy_command(r.text);
      showToast("已复制到剪贴板");
    } else if (action === "archive") {
      const r = await api().get_record_text(Number(b.dataset.ts));
      if (!r.ok) return showToast("内容已不在");
      const res = await api().archive_text(r.text, null, "auto");
      showToast(res.ok ? `已归档到 ${res.target}` : `失败：${res.error || ""}`);
    } else if (action === "open") {
      api().open_path(b.dataset.path);
    }
  }

  function renderHistoryItem(r) {
    const meta = `<div class="meta">${fmtTime(r.ts)}<br/><small>${
      r.type === "image" ? (r.size ? Math.round(r.size / 1024) + " KB" : "图片") : (r.len || 0) + " 字"
    }</small></div>`;
    if (r.type === "image") {
      const url = r.img_url || "";
      return `
        <div class="history-item image">
          ${meta}
          <div class="body">
            <img class="thumb" src="${escapeHtml(url)}" loading="lazy" data-action="open" data-path="${escapeHtml(r.img_path || "")}"/>
            <span class="muted">点击在 Finder 打开</span>
          </div>
          <div class="actions">
            <button class="btn-mini" data-action="open" data-path="${escapeHtml(r.img_path || "")}">打开</button>
          </div>
        </div>`;
    }
    return `
      <div class="history-item">
        ${meta}
        <div class="body">${escapeHtml(r.preview || "")}</div>
        <div class="actions">
          <button class="btn-mini" data-action="copy" data-ts="${r.ts}">复制</button>
          <button class="btn-mini" data-action="archive" data-ts="${r.ts}">归档</button>
        </div>
      </div>`;
  }

  /* ====== 词典 ====== */
  async function renderDict(force = false) {
    if (!force && loaded.dict) return;
    if (!loaded.dict) panels.dict.innerHTML = `<div class="loading">加载中…</div>`;
    const d = await api().get_dictionary();
    panels.dict.innerHTML = `
      <h2 class="page-title">黑名单</h2>
      <p class="page-lead">命中黑名单的复制内容不会触发胶囊浮层（仍会进历史）。规则是<strong>正则表达式</strong>，按从上到下的顺序匹配，命中一条即跳过。常见用法：<code>^https?://</code> 跳过链接、<code>function|class\\s</code> 跳过代码片段、关键词如 <code>密码</code> / <code>token</code> 跳过敏感内容。</p>
      <div class="card">
        <h3>手动添加跳过规则</h3>
        <div class="dict-add">
          <input type="text" id="new-skip" placeholder="正则，如 ^https://  或  某关键词" />
          <button class="btn btn-primary" id="add-skip">添加</button>
        </div>
        ${renderDictGroup("✋ 手动添加", d.manual, "manual", "manual")}
        ${renderDictGroup("🤖 自动加入（连续跳过时）", d.auto, "auto", "auto")}
        ${renderDictGroup("⚙️ config.yaml 配置", d.config, "config", null)}
        ${renderDictGroup("📦 内置（不可删）", d.builtin, "builtin", null)}
      </div>
    `;
    panels.dict.querySelector("#add-skip").onclick = async () => {
      const input = panels.dict.querySelector("#new-skip");
      const v = input.value.trim();
      if (!v) return;
      const r = await api().add_skip(v);
      input.value = "";
      showToast(r.ok ? "已添加" : "已存在");
      renderDict(true);
    };
    panels.dict.querySelector("#new-skip").onkeydown = (e) => {
      if (e.key === "Enter") panels.dict.querySelector("#add-skip").click();
    };
    loaded.dict = true;
  }

  // 事件委托：dict 删除
  panels.dict.addEventListener("click", async (e) => {
    const x = e.target.closest("[data-rm]");
    if (!x) return;
    await api().remove_skip(x.dataset.rm, x.dataset.scope);
    showToast("已删除");
    renderDict(true);
  });

  function renderDictGroup(title, items, klass, removable) {
    if (!items || !items.length) {
      return `<div class="dict-group"><h4>${title}</h4><div class="muted small">（空）</div></div>`;
    }
    return `
      <div class="dict-group">
        <h4>${title}（${items.length}）</h4>
        <div class="dict-tags">
          ${items
            .map(
              (p) => `<span class="tag ${klass}"><code>${escapeHtml(p)}</code>${
                removable ? `<span class="x" data-rm="${escapeHtml(p)}" data-scope="${removable}" title="删除">×</span>` : ""
              }</span>`
            )
            .join("")}
        </div>
      </div>`;
  }

  /* ====== 快捷键 ====== */
  async function renderHotkey(force = false) {
    if (!force && loaded.hotkey) return;
    if (!loaded.hotkey) panels.hotkey.innerHTML = `<div class="loading">加载中…</div>`;
    const hk = await api().get_hotkeys();
    const row = (key, info) => `
      <div class="hotkey-row">
        <div class="hotkey-name">${escapeHtml(info.name)}<small>${escapeHtml(info.cmd)}</small></div>
        <input type="text" data-key="${key}" value="${escapeHtml(info.shortcut)}" placeholder="点这里，然后按快捷键" readonly />
        <button class="btn-mini" data-copy="${escapeHtml(info.cmd)}">复制命令</button>
        <button class="btn-mini" data-open-shortcuts>打开 Shortcuts</button>
      </div>`;
    panels.hotkey.innerHTML = `
      <h2 class="page-title">⌨️ 快捷键</h2>
      <p class="page-lead">点击输入框后直接按组合键即可保存。菜单栏会全局监听这些快捷键，Shortcuts 仍保留为备用方案。</p>
      <div class="card">
        ${row("input", hk.input)}
        ${row("translate", hk.translate)}
        ${row("ask", hk.ask)}
        <div class="hotkey-help">
          <strong>怎么用：</strong><br/>
          1. 点输入框，直接按你想要的组合键，例如 <code>⌃⌥⌘A</code><br/>
          2. 保存后通常立即生效；若没反应，再点菜单「🔄 重新加载配置」或重启菜单栏<br/>
          3. 若系统没响应，去「系统设置 → 隐私与安全性 → 辅助功能」允许相关进程
        </div>
      </div>
    `;
    loaded.hotkey = true;
  }

  // 事件委托：hotkey
  panels.hotkey.addEventListener("keydown", async (e) => {
    const inp = e.target.closest("input[data-key]");
    if (!inp) return;
    e.preventDefault();
    const combo = comboFromEvent(e);
    if (!combo) {
      showToast("请按组合键，例如 ⌃⌥⌘A");
      return;
    }
    inp.value = combo;
    const r = await api().update_hotkey(inp.dataset.key, combo);
    showToast(r.ok ? "已保存，通常立即生效" : (r.error || "保存失败"));
  });
  panels.hotkey.addEventListener("click", async (e) => {
    const c = e.target.closest("[data-copy]");
    if (c) {
      const r = await api().copy_command(c.dataset.copy);
      showToast(r.ok ? "命令已复制" : "复制失败");
      return;
    }
    const s = e.target.closest("[data-open-shortcuts]");
    if (s) api().open_shortcuts_app();
  });

  /* ====== Tab 切换：display 切换，不重建 DOM ====== */
  const renderers = { home: renderHome, history: renderHistory, dict: renderDict, hotkey: renderHotkey };
  let currentTab = "home";

  function switchTab(tab) {
    if (!panels[tab]) return;
    currentTab = tab;
    document.querySelectorAll(".nav-item").forEach((b) => {
      b.classList.toggle("active", b.dataset.tab === tab);
    });
    for (const k of Object.keys(panels)) {
      panels[k].hidden = k !== tab;
    }
    renderers[tab](false);
    try { api() && api().track("view", tab); } catch (e) { /* ignore */ }
  }

  document.querySelectorAll(".nav-item").forEach((b) => {
    b.addEventListener("click", () => switchTab(b.dataset.tab));
  });

  // sidebar 底部 icon 排
  document.querySelectorAll("[data-foot]").forEach((b) => {
    b.addEventListener("click", async () => {
      const k = b.dataset.foot;
      if (k === "kb") api().open_kb();
      else if (k === "report") {
        const r = await api().open_design_report();
        if (!r.ok) showToast("报告未生成");
      } else if (k === "events") {
        api().open_path("/Users/linxiaolan10/tools/ai-archiver/.history/events.jsonl");
      }
    });
  });

  waitForApi().then(() => switchTab("home"));
})();
