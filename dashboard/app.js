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
    <section data-panel="profile" class="panel" hidden></section>
    <section data-panel="history" class="panel" hidden></section>
    <section data-panel="dict" class="panel" hidden></section>
    <section data-panel="logs" class="panel" hidden></section>
    <section data-panel="feedback" class="panel" hidden></section>
  `;
  const panels = {
    home: root.querySelector('[data-panel="home"]'),
    profile: root.querySelector('[data-panel="profile"]'),
    history: root.querySelector('[data-panel="history"]'),
    dict: root.querySelector('[data-panel="dict"]'),
    logs: root.querySelector('[data-panel="logs"]'),
    feedback: root.querySelector('[data-panel="feedback"]'),
  };

  // 每个 panel 是否已加载过（避免重复 RPC）
  const loaded = { home: false, profile: false, history: false, dict: false, logs: false, feedback: false };

  /* ====== 首页 ====== */
  async function renderHome(force = false) {
    if (!force && loaded.home) return;
    if (!loaded.home) panels.home.innerHTML = `<div class="loading">加载中…</div>`;
    const [data, dictData] = await Promise.all([
      api().get_overview(),
      api().get_dictionary().catch(() => ({ entries: [] })),
    ]);
    applyTheme(data.app_theme || "light");
    const s = data.stats;
    const last = data.last_record || {};
    const def = data.default_target;
    const defDisplay = data.default_target_display || def || "";
    const dictEntries = (dictData && dictData.entries) || [];
    panels.home.innerHTML = `
      <div class="stats-grid">
        <div class="stat-card"><div class="label">累计字数</div><div class="value">${s.chars.toLocaleString()}</div><div class="sub">字</div></div>
        <div class="stat-card"><div class="label">已归档</div><div class="value">${s.archived}</div><div class="sub">条</div></div>
        <div class="stat-card"><div class="label">节省时间</div><div class="value">${s.saved_hhmm}</div><div class="sub">估算</div></div>
        <div class="stat-card"><div class="label">复制次数</div><div class="value">${s.count}</div><div class="sub">累计</div></div>
      </div>

      <div class="card default-doc-card">
        <h3>知识库 <span class="hint">胶囊归档写入这里 · AI 精简也会读它做术语对齐 / 关联补充</span></h3>
        ${
          def
            ? `<div class="default-doc-row">
                 <div class="default-doc-path" data-act="open-def" title="${escapeHtml(data.default_target_path || def)}（点击在 Finder 中打开）">${escapeHtml(defDisplay)}</div>
                 <button class="btn" data-act="change-def">更换…</button>
                 <button class="btn" data-act="new-def">新建…</button>
               </div>
               <div class="kb-aware-tip">✓ 每次精简会自动参考此文档最近 ~2400 字</div>`
            : `<div class="default-doc-row">
                 <div class="default-doc-empty">尚未设置 · 选一个 .md 让 AI 既能归档、又能参考你的笔记</div>
                 <button class="btn btn-primary" data-act="change-def">选择…</button>
                 <button class="btn" data-act="new-def">新建…</button>
               </div>`
        }
      </div>

      <section class="card" id="dict-card">
        <h3>纠错词典 <span class="hint">写错的写法 → 正确的写法。下次精简时会自动替换。</span></h3>
        <div class="dict-tip">⚡ 自动条目是 AI 学的，建议偶尔扫一眼有没有学歪</div>
        <div id="dict-card-body">${renderDictTable(dictEntries)}</div>
        <div class="dict-add-row">
          <input type="text" id="dict-wrong-input" placeholder="错的写法（如：陈列然）" autocomplete="off" spellcheck="false" />
          <input type="text" id="dict-right-input" placeholder="正确的写法（如：陈睿然）" autocomplete="off" spellcheck="false" />
          <button class="btn btn-primary" id="dict-add-btn">+ 添加</button>
        </div>
      </section>

      <div class="card memory-card" id="memory-card">
        <h3>
          <span>今日摘要</span>
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
          <h3>常用文档 <span class="hint">点一下，切换为默认归档目标</span></h3>
          ${
            data.favorites.length
              ? `<div class="fav-list">${data.favorites
                  .map((f) => {
                    const raw = f.raw || "";
                    const isCur = raw === def;
                    return `<button type="button" class="fav-item ${isCur ? "current" : ""}"
                      data-act="switch-def" data-target="${escapeHtml(raw)}"
                      title="${escapeHtml(raw)}${isCur ? "（当前默认）" : "（点击设为默认）"}">
                      <span class="fav-dot">${isCur ? "✓" : "○"}</span>
                      <span class="fav-name">${escapeHtml(f.display || raw)}</span>
                    </button>`;
                  })
                  .join("")}</div>`
              : `<div class="empty">暂无常用，去归档几次就有了</div>`
          }
        </div>

        <div class="card">
          <h3>外观 <span class="hint">浅色 / 深色</span></h3>
          <div class="segment" data-act="theme-seg">
            <button data-theme="light" class="${(data.app_theme || "light") === "light" ? "active" : ""}">浅色</button>
            <button data-theme="dark" class="${data.app_theme === "dark" ? "active" : ""}">深色</button>
          </div>
        </div>
      </div>
    `;
    loaded.home = true;
    bindDictHomeHandlers();
    // 异步加载 memory（不阻塞首页其它内容）
    loadMemoryCard();
  }

  /* —— 首页内嵌：纠错词典（路线 A 编辑面板）—— */
  function renderDictSourceChip(src) {
    if (src === "auto") {
      return `<span class="dict-src dict-src-auto" title="AI 检测到疑似拼写后自动学习">⚡ 自动</span>`;
    }
    return `<span class="dict-src dict-src-manual" title="你手动添加或确认过">👤 手动</span>`;
  }

  function renderDictTable(entries) {
    if (!entries || !entries.length) {
      return `<div class="dict-empty">还没有纠错条目。胶囊里检测到疑似拼写时会自动学习，也可以在下方手动添加。</div>`;
    }
    return `
      <table class="dict-table">
        <thead>
          <tr>
            <th>错</th>
            <th>对</th>
            <th class="src">来源</th>
            <th class="num">命中</th>
            <th class="act"></th>
          </tr>
        </thead>
        <tbody>
          ${entries.map((e) => `
            <tr>
              <td><code>${escapeHtml(e.wrong || "")}</code></td>
              <td><code>${escapeHtml(e.right || "")}</code></td>
              <td class="src">${renderDictSourceChip(e.source || "manual")}</td>
              <td class="num">${Number(e.hits || 0)}</td>
              <td class="act">
                <button class="btn-mini" data-dict-rm="${escapeHtml(e.wrong || "")}">删除</button>
              </td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    `;
  }

  async function refreshDictCard() {
    const body = document.getElementById("dict-card-body");
    if (!body) return;
    const d = await api().get_dictionary().catch(() => ({ entries: [] }));
    body.innerHTML = renderDictTable((d && d.entries) || []);
  }

  function bindDictHomeHandlers() {
    const wIn = document.getElementById("dict-wrong-input");
    const rIn = document.getElementById("dict-right-input");
    if (wIn) {
      wIn.onkeydown = (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          if (rIn) rIn.focus();
        }
      };
    }
    if (rIn) {
      rIn.onkeydown = (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          const btn = document.getElementById("dict-add-btn");
          if (btn) btn.click();
        }
      };
    }
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
    // 纠错词典：添加
    if (e.target.closest("#dict-add-btn")) {
      const wIn = document.getElementById("dict-wrong-input");
      const rIn = document.getElementById("dict-right-input");
      const w = (wIn && wIn.value || "").trim();
      const r = (rIn && rIn.value || "").trim();
      if (!w || !r) { showToast("错/对 都要填"); return; }
      if (w === r) { showToast("错和对不能一样"); return; }
      const res = await api().add_dictionary_entry(w, r);
      if (res && res.ok) {
        if (wIn) wIn.value = "";
        if (rIn) rIn.value = "";
        showToast("已添加：" + w + " → " + r);
        await refreshDictCard();
      } else {
        showToast("添加失败：" + (res && res.error || ""));
      }
      return;
    }
    // 纠错词典：删除
    const rmBtn = e.target.closest("[data-dict-rm]");
    if (rmBtn) {
      const w = rmBtn.dataset.dictRm;
      if (!w) return;
      const res = await api().delete_dictionary_entry(w);
      if (res && res.ok) {
        showToast("已删除：" + w);
        await refreshDictCard();
      } else {
        showToast("删除失败：" + (res && res.error || ""));
      }
      return;
    }
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
    } else if (act === "switch-def") {
      const target = t.dataset.target;
      if (!target) return;
      const r = await api().switch_default_target(target);
      if (r.ok) {
        showToast("已切换为：" + (r.default_target_display || r.default_target));
        renderHome(true);
      } else if (!r.cancelled) {
        showToast("切换失败：" + (r.error || ""));
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
        <h2 class="page-title">历史</h2>
        <p class="page-lead">你复制过的文字和图片，按时间排列。</p>
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
    const d = await api().get_skip_dict();
    panels.dict.innerHTML = `
      <h2 class="page-title">黑名单</h2>
      <p class="page-lead">命中黑名单的内容不会弹胶囊，但仍会记在「历史」里。菜单栏「添加到黑名单」可快速添加。</p>
      <div class="card">
        <h3>添加规则</h3>
        <div class="dict-add">
          <input type="text" id="new-skip" placeholder="关键词或链接，如 https:// 或 某公众号名" />
          <button class="btn btn-primary" id="add-skip">添加</button>
        </div>
        ${renderDictGroup("你添加的", d.manual, "manual", "manual")}
        ${renderDictGroup("自动添加", d.auto, "auto", "auto")}
        ${renderDictGroup("内置规则", d.builtin, "builtin", null)}
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

  /* ====== 档案（SOUL / USER / TOOLS）====== */
  const PROFILE_CARDS = [
    {
      kind: "soul",
      title: "SOUL.md",
      subtitle: "Skillless 是谁 · 视角补充段的人格 / 口吻 / 价值观",
      hint: "只对「📚 你的视角补充」段生效；精简正文不受影响。",
    },
    {
      kind: "user",
      title: "USER.md",
      subtitle: "关于你 · AI 在写视角补充时的人物画像",
      hint: "AI 用这段决定该用什么角度看你的新输入；不会拿来模仿你的文风写精简正文。",
    },
    {
      kind: "tools",
      title: "TOOLS.md",
      subtitle: "项目 / 术语 / 关键人物 · 视角补充段的私密备忘录",
      hint: "让视角补充能直说「张三那个项目」；精简正文不解释术语。",
    },
  ];

  async function renderProfile(force = false) {
    if (!force && loaded.profile) return;
    if (!loaded.profile) panels.profile.innerHTML = `<div class="loading">加载中…</div>`;
    const data = await api().get_profile().catch(() => ({ soul: "", user: "", tools: "" }));
    panels.profile.innerHTML = `
      <h2 class="page-title">档案 <span class="hint" style="font-size: 12px; margin-left: 8px;">三层人格记忆 · 告别冷启动</span></h2>
      <p class="page-lead">
        Skillless 通过 <strong>SOUL / USER / TOOLS</strong> 三个 markdown 文件认识你。
        <strong>每次精简时 AI 都会读它们做「视角补充」</strong>——改完点保存即生效，不需要重启。
        <br/>这三份档案<strong>只服务于「📚 你的视角补充」段</strong>；精简正文还是按基础规则走，不会被影响。
      </p>

      <div class="card" style="display: flex; align-items: center; justify-content: space-between; gap: 12px;">
        <div style="font-size: 13px; color: #475569; line-height: 1.6;">
          想直接编辑文件、加图、做版本对比？打开 Finder。
        </div>
        <button class="btn" data-act="open-profile-dir">📂 在 Finder 中打开</button>
      </div>

      <div class="profile-grid">
        ${PROFILE_CARDS.map((c) => `
          <section class="card profile-card" data-card="${c.kind}">
            <h3>
              <span>${escapeHtml(c.title)} <span class="hint" style="margin-left: 6px;">${escapeHtml(c.subtitle)}</span></span>
              <button class="btn btn-primary profile-save-btn" data-kind="${c.kind}">保存</button>
            </h3>
            <div class="profile-hint">${escapeHtml(c.hint)}</div>
            <textarea class="profile-textarea" data-kind="${c.kind}" spellcheck="false">${escapeHtml(data[c.kind] || "")}</textarea>
          </section>
        `).join("")}
      </div>
    `;

    // 绑定保存按钮：每张卡独立保存
    panels.profile.querySelectorAll(".profile-save-btn").forEach((btn) => {
      btn.onclick = async () => {
        const kind = btn.dataset.kind;
        const ta = panels.profile.querySelector(`.profile-textarea[data-kind="${kind}"]`);
        if (!ta) return;
        const content = ta.value || "";
        btn.disabled = true;
        const oldText = btn.textContent;
        btn.textContent = "保存中…";
        try {
          const r = await api().save_profile_part(kind, content);
          if (r && r.ok) {
            showToast(`已保存 ${kind.toUpperCase()}.md · ${content.length} 字符`);
          } else {
            showToast(`保存失败：${(r && r.error) || "未知错误"}`);
          }
        } catch (e) {
          showToast("保存失败：" + (e && e.message || e));
        } finally {
          btn.disabled = false;
          btn.textContent = oldText;
        }
      };
    });

    // 绑定 Finder 入口
    const openBtn = panels.profile.querySelector('[data-act="open-profile-dir"]');
    if (openBtn) {
      openBtn.onclick = async () => {
        try {
          const r = await api().open_profile_dir();
          if (r && r.ok) showToast("已打开 profile 目录");
          else showToast("打开失败：" + ((r && r.error) || ""));
        } catch (e) {
          showToast("打开失败：" + (e && e.message || e));
        }
      };
    }

    loaded.profile = true;
  }

  /* ====== 日志 ====== */
  let activeLogName = "clip_watcher.log";

  async function renderLogs(force = false) {
    if (!force && loaded.logs) return;
    const data = await api().list_logs();
    const items = data.items || [];
    panels.logs.innerHTML = `
      <h2 class="page-title">日志</h2>
      <p class="page-lead">排查「复制没弹胶囊」等问题时看这里。点文件名切换，下方显示最近内容。</p>
      <div class="card">
        <div class="log-tabs" id="log-tabs">
          ${items.map((it) => `
            <button type="button" class="log-tab ${it.name === activeLogName ? "active" : ""} ${it.exists ? "" : "empty"}"
              data-log="${escapeHtml(it.name)}">
              ${escapeHtml(it.label)}
              <small>${it.exists ? Math.max(1, Math.round(it.size / 1024)) + " KB" : "空"}</small>
            </button>`).join("")}
        </div>
        <div class="log-actions">
          <button class="btn-mini" id="log-refresh">刷新</button>
          <button class="btn-mini" id="log-open-folder">打开文件夹</button>
        </div>
        <pre class="log-view" id="log-view">加载中…</pre>
      </div>
    `;
    panels.logs.querySelector("#log-tabs").addEventListener("click", async (e) => {
      const b = e.target.closest("[data-log]");
      if (!b) return;
      activeLogName = b.dataset.log;
      panels.logs.querySelectorAll(".log-tab").forEach((el) => {
        el.classList.toggle("active", el.dataset.log === activeLogName);
      });
      await loadLogBody();
    });
    panels.logs.querySelector("#log-refresh").onclick = () => renderLogs(true);
    panels.logs.querySelector("#log-open-folder").onclick = () => api().open_logs_folder();
    loaded.logs = true;
    await loadLogBody();
  }

  async function loadLogBody() {
    const view = panels.logs.querySelector("#log-view");
    if (!view) return;
    const r = await api().read_log(activeLogName, 300);
    if (!r.ok) {
      view.textContent = r.error || "读取失败";
      return;
    }
    if (r.empty) {
      view.textContent = "（暂无内容）";
      return;
    }
    view.textContent = r.content || "";
  }

  /* ====== 反馈 / 问题报告 ====== */
  async function renderFeedback(force = false) {
    if (!force && loaded.feedback) return;
    if (!loaded.feedback) panels.feedback.innerHTML = `<div class="loading">加载中…</div>`;
    const status = await api().feedback_status().catch(() => ({}));
    const channel = status.webhook_configured
      ? (status.channel === "feishu" ? "飞书机器人" : status.channel)
      : "未配置（提交后将复制到剪贴板，请粘贴给开发者）";
    panels.feedback.innerHTML = `
      <h2 class="page-title">反馈 / 问题报告</h2>
      <p class="page-lead">写一句话告诉开发者你遇到的问题、想要的功能。提交时会随附最近日志、版本、系统信息。
        <strong>不会发送你的笔记原文、剪贴板内容、API Key 或词典条目。</strong></p>

      <div class="card fb-card">
        <h3>说点什么 <span class="hint">越具体越容易修</span></h3>
        <textarea id="fb-desc" class="fb-textarea" placeholder="例：会议记录粘进来胶囊不出现 / 视角补充能不能再短一点 / 在 macOS 26 上启动崩溃……" maxlength="600"></textarea>
        <div class="fb-row">
          <span class="fb-meter"><span id="fb-count">0</span> / 600 字</span>
          <span class="fb-channel">通道：${escapeHtml(channel)}</span>
        </div>
        <div class="fb-actions">
          <button class="btn" id="fb-preview-btn">预览要发的内容</button>
          <button class="btn btn-primary" id="fb-send-btn">提交反馈</button>
        </div>
        <div id="fb-result" class="fb-result"></div>
      </div>

      <div class="card fb-card">
        <h3>设置</h3>
        <div class="fb-settings">
          <label class="fb-setting-row">
            <span class="fb-label">反馈署名</span>
            <input type="text" id="fb-handle" class="fb-input" value="${escapeHtml(status.user_handle || "")}" placeholder="昵称（开发者看到这个名字回你）" />
            <small class="hint">默认从「档案 → USER.md」读取，也可在这里覆写</small>
          </label>
          <label class="fb-setting-row">
            <span class="fb-label">自动错误上报</span>
            <span>
              <input type="checkbox" id="fb-auto" ${status.auto_error_enabled ? "checked" : ""} />
              <small class="hint">遇到崩溃 / 网络挂了，自动发一条精简事件给开发者（30s 限流，避免刷屏）</small>
            </span>
          </label>
          <label class="fb-setting-row fb-advanced">
            <span class="fb-label">自定义 webhook</span>
            <input type="text" id="fb-webhook" class="fb-input" value="${escapeHtml(status.custom_webhook || "")}" placeholder="（仅自架收件时填，留空走打包默认）" autocomplete="off" />
            <small class="hint">填入后将覆盖默认通道。常用于内测时把反馈发到自己群</small>
          </label>
          <div class="fb-actions">
            <button class="btn" id="fb-save-settings">保存设置</button>
          </div>
        </div>
      </div>

      <div class="card fb-card fb-preview-wrap" id="fb-preview-wrap" hidden>
        <h3>预览（这就是开发者会看到的内容）</h3>
        <pre id="fb-preview-pre" class="fb-preview"></pre>
      </div>
    `;

    const desc = panels.feedback.querySelector("#fb-desc");
    const count = panels.feedback.querySelector("#fb-count");
    desc.addEventListener("input", () => { count.textContent = String(desc.value.length); });

    panels.feedback.querySelector("#fb-preview-btn").onclick = async () => {
      const r = await api().feedback_preview(desc.value || "");
      const wrap = panels.feedback.querySelector("#fb-preview-wrap");
      const pre = panels.feedback.querySelector("#fb-preview-pre");
      if (r.ok) {
        wrap.hidden = false;
        pre.textContent = JSON.stringify(r.payload, null, 2);
      } else {
        toast("预览失败：" + (r.error || ""));
      }
    };

    panels.feedback.querySelector("#fb-send-btn").onclick = async () => {
      const text = (desc.value || "").trim();
      const result = panels.feedback.querySelector("#fb-result");
      if (!text) {
        result.innerHTML = `<div class="fb-warn">请先写点什么</div>`;
        return;
      }
      result.innerHTML = `<div class="fb-info">发送中…</div>`;
      const r = await api().feedback_send(text);
      if (r.ok) {
        result.innerHTML = `<div class="fb-ok">✓ 已发送给开发者（通道：${escapeHtml(r.channel || "")}）</div>`;
        desc.value = ""; count.textContent = "0";
      } else if (r.fallback === "clipboard") {
        result.innerHTML = `<div class="fb-warn">网络发送失败（${escapeHtml(r.reason || "")}），反馈包已复制到剪贴板，请粘给开发者</div>`;
      } else {
        result.innerHTML = `<div class="fb-warn">发送失败：${escapeHtml(r.reason || r.error || "")}</div>`;
      }
    };

    panels.feedback.querySelector("#fb-save-settings").onclick = async () => {
      const handle = panels.feedback.querySelector("#fb-handle").value.trim();
      const webhook = panels.feedback.querySelector("#fb-webhook").value.trim();
      const auto = panels.feedback.querySelector("#fb-auto").checked;
      const r = await api().feedback_save_settings({
        user_handle: handle,
        custom_webhook: webhook,
        auto_error_enabled: auto,
      });
      if (r.ok) {
        toast("设置已保存");
        renderFeedback(true);
      } else {
        toast("保存失败：" + (r.error || ""));
      }
    };

    loaded.feedback = true;
  }

  /* ====== Tab 切换：display 切换，不重建 DOM ====== */
  const renderers = { home: renderHome, profile: renderProfile, history: renderHistory, dict: renderDict, logs: renderLogs, feedback: renderFeedback };
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

  waitForApi().then(() => switchTab("home"));
})();
