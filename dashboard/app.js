(function () {
  const content = document.getElementById("content");
  const toast = document.getElementById("toast");
  let currentTab = "home";
  let historyFilter = null;

  function api() {
    return window.pywebview && window.pywebview.api;
  }
  function waitForApi() {
    return new Promise((r) => {
      const tick = () => (api() ? r(api()) : setTimeout(tick, 50));
      tick();
    });
  }

  function showToast(msg) {
    toast.textContent = msg;
    toast.classList.add("show");
    setTimeout(() => toast.classList.remove("show"), 1800);
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
    const md = `${d.getMonth() + 1}/${d.getDate()}`;
    return `${md} ${hh}:${mm}`;
  }

  /* —— 首页 —— */
  async function renderHome() {
    content.innerHTML = `<div class="loading">加载中…</div>`;
    const data = await api().get_overview();
    const s = data.stats;
    const last = data.last_record || {};
    content.innerHTML = `
      <h2 class="page-title">📊 首页</h2>
      <p class="page-lead">知识库：${escapeHtml(data.kb_root)} · 默认文档：${escapeHtml(data.default_target || "未设置")}</p>

      <div class="stats-grid">
        <div class="stat-card">
          <div class="label">喂养龙虾</div>
          <div class="value">${s.chars.toLocaleString()}</div>
          <div class="sub">字（累计复制）</div>
        </div>
        <div class="stat-card">
          <div class="label">已归档</div>
          <div class="value">${s.archived}</div>
          <div class="sub">条</div>
        </div>
        <div class="stat-card">
          <div class="label">节省时间</div>
          <div class="value">${s.saved_hhmm}</div>
          <div class="sub">按 1 条/分钟</div>
        </div>
        <div class="stat-card">
          <div class="label">历史条目</div>
          <div class="value">${s.count}</div>
          <div class="sub">总复制次数</div>
        </div>
      </div>

      <div class="card">
        <h3>📋 最后一次复制</h3>
        ${
          last.ts
            ? `
          <div style="font-size:11px;color:#6d8099;margin-bottom:8px">
            ${fmtTime(last.ts)} · ${escapeHtml(last.type || "text")}${
                last.len ? " · " + last.len + " 字" : ""
              }
          </div>
          ${
            last.type === "image"
              ? `<img src="${escapeHtml(last.img_url || "")}" style="max-width:100%;max-height:220px;border-radius:6px"/>`
              : `<div class="last-preview">${escapeHtml(last.preview || "")}</div>`
          }
        `
            : `<div class="empty">还没有任何复制记录</div>`
        }
      </div>

      <div class="card">
        <h3>⭐ 常用文档</h3>
        ${
          data.favorites.length
            ? `<div style="font-size:13px;color:#b8c5d6;line-height:1.8">${data.favorites
                .map((f) => `<div>· ${escapeHtml(f)}</div>`)
                .join("")}</div>`
            : `<div class="empty">暂无常用，去归档几次就有了</div>`
        }
      </div>`;
  }

  /* —— 历史 —— */
  async function renderHistory() {
    content.innerHTML = `<div class="loading">加载中…</div>`;
    const items = await api().list_history(historyFilter, 200);
    const filterBtn = (key, label) => `
      <button type="button" class="${historyFilter === key ? "active" : ""}" data-filter="${key ?? ""}">${label}</button>`;
    content.innerHTML = `
      <h2 class="page-title">📜 历史记录</h2>
      <p class="page-lead">最近 200 条剪贴板（按时间倒序），文字和图片都在。</p>

      <div class="filter-bar">
        ${filterBtn(null, "全部")}
        ${filterBtn("text", "文字")}
        ${filterBtn("image", "图片")}
        <div class="spacer"></div>
        <button type="button" id="clear-history" style="color:#ff9eb0">清空历史</button>
      </div>

      <div class="history-list" id="history-list">
        ${
          items.length === 0
            ? `<div class="empty">还没有历史记录</div>`
            : items.map(renderHistoryItem).join("")
        }
      </div>`;

    content.querySelectorAll(".filter-bar [data-filter]").forEach((b) => {
      b.onclick = () => {
        const f = b.dataset.filter || null;
        historyFilter = f;
        renderHistory();
      };
    });
    document.getElementById("clear-history").onclick = async () => {
      if (!confirm("确认清空所有历史？图片文件也会一并删除。")) return;
      await api().clear_history();
      showToast("已清空");
      renderHistory();
    };
    content.querySelectorAll("[data-action=copy]").forEach((b) => {
      b.onclick = async () => {
        const ts = Number(b.dataset.ts);
        const r = await api().get_record_text(ts);
        if (!r.ok) return showToast("内容已不在");
        await api().copy_command(r.text);
        showToast("已复制到剪贴板");
      };
    });
    content.querySelectorAll("[data-action=archive]").forEach((b) => {
      b.onclick = async () => {
        const ts = Number(b.dataset.ts);
        const r = await api().get_record_text(ts);
        if (!r.ok) return showToast("内容已不在");
        const res = await api().archive_text(r.text, null, "auto");
        showToast(res.ok ? `已归档到 ${res.target}` : `失败：${res.error || ""}`);
      };
    });
    content.querySelectorAll("[data-action=open]").forEach((b) => {
      b.onclick = async () => {
        await api().open_path(b.dataset.path);
      };
    });
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
            <img class="thumb" src="${escapeHtml(url)}" data-action="open" data-path="${escapeHtml(r.img_path || "")}"/>
            <span style="color:#6d8099;font-size:12px">点击在 Finder 打开</span>
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

  /* —— 词典 —— */
  async function renderDict() {
    content.innerHTML = `<div class="loading">加载中…</div>`;
    const d = await api().get_dictionary();
    content.innerHTML = `
      <h2 class="page-title">📕 词典</h2>
      <p class="page-lead">匹配下面正则的复制内容不会触发归档弹窗。</p>

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
      </div>`;

    document.getElementById("add-skip").onclick = async () => {
      const input = document.getElementById("new-skip");
      const v = input.value.trim();
      if (!v) return;
      const r = await api().add_skip(v);
      input.value = "";
      showToast(r.ok ? "已添加" : "已存在");
      renderDict();
    };
    document.getElementById("new-skip").onkeydown = (e) => {
      if (e.key === "Enter") document.getElementById("add-skip").click();
    };
    content.querySelectorAll("[data-rm]").forEach((x) => {
      x.onclick = async () => {
        const p = x.dataset.rm;
        const scope = x.dataset.scope;
        await api().remove_skip(p, scope);
        showToast("已删除");
        renderDict();
      };
    });
  }

  function renderDictGroup(title, items, klass, removable) {
    if (!items || !items.length) {
      return `
        <div class="dict-group">
          <h4>${title}</h4>
          <div style="font-size:12px;color:#6d8099;padding:6px 0">（空）</div>
        </div>`;
    }
    return `
      <div class="dict-group">
        <h4>${title}（${items.length}）</h4>
        <div class="dict-tags">
          ${items
            .map(
              (p) => `
            <span class="tag ${klass}">
              <code>${escapeHtml(p)}</code>
              ${removable ? `<span class="x" data-rm="${escapeHtml(p)}" data-scope="${removable}" title="删除">×</span>` : ""}
            </span>`
            )
            .join("")}
        </div>
      </div>`;
  }

  /* —— 快捷键 —— */
  async function renderHotkey() {
    content.innerHTML = `<div class="loading">加载中…</div>`;
    const hk = await api().get_hotkeys();
    const row = (key, info) => `
      <div class="hotkey-row">
        <div class="hotkey-name">
          ${escapeHtml(info.name)}
          <small>${escapeHtml(info.cmd)}</small>
        </div>
        <input type="text" data-key="${key}" value="${escapeHtml(info.shortcut)}" placeholder="点这里，然后按快捷键" readonly />
        <button class="btn-mini" data-copy="${escapeHtml(info.cmd)}">复制命令</button>
        <button class="btn-mini" data-open-shortcuts>打开 Shortcuts</button>
      </div>`;
    content.innerHTML = `
      <h2 class="page-title">⌨️ 快捷键</h2>
      <p class="page-lead">点击输入框后直接按组合键即可保存。菜单栏 App 会全局监听这些快捷键；Shortcuts 仍保留为备用方案。</p>

      <div class="card">
        ${row("input", hk.input)}
        ${row("translate", hk.translate)}
        ${row("ask", hk.ask)}

        <div class="hotkey-help">
          <strong>怎么用：</strong><br/>
          1. 点输入框，直接按你想要的组合键，例如 <code>⌃⌥⌘A</code><br/>
          2. 保存后通常立即生效；若没反应，再点菜单「🔄 重新加载配置」或重启菜单栏<br/>
          3. 如果系统没有响应，请到「系统设置 → 隐私与安全性 → 辅助功能」允许 Terminal / Python / Cursor 控制电脑<br/>
          <br/>
          <strong>备用方案：</strong>点「复制命令」并在 Shortcuts 里绑定同一个快捷键。
        </div>
      </div>`;

    content.querySelectorAll("input[data-key]").forEach((inp) => {
      inp.onkeydown = async (e) => {
        e.preventDefault();
        const combo = comboFromEvent(e);
        if (!combo) {
          showToast("请按组合键，例如 ⌃⌥⌘A");
          return;
        }
        inp.value = combo;
        const r = await api().update_hotkey(inp.dataset.key, combo);
        showToast(r.ok ? "已保存，通常立即生效" : (r.error || "保存失败"));
      };
    });
    content.querySelectorAll("[data-copy]").forEach((b) => {
      b.onclick = async () => {
        const r = await api().copy_command(b.dataset.copy);
        showToast(r.ok ? "命令已复制" : "复制失败");
      };
    });
    content.querySelectorAll("[data-open-shortcuts]").forEach((b) => {
      b.onclick = () => api().open_shortcuts_app();
    });
  }

  /* —— Tab 切换 —— */
  const renderers = {
    home: renderHome,
    history: renderHistory,
    dict: renderDict,
    hotkey: renderHotkey,
  };

  function switchTab(tab) {
    currentTab = tab;
    document.querySelectorAll(".nav-item").forEach((b) => {
      b.classList.toggle("active", b.dataset.tab === tab);
    });
    (renderers[tab] || renderHome)();
  }

  document.querySelectorAll(".nav-item").forEach((b) => {
    b.onclick = () => switchTab(b.dataset.tab);
  });
  document.getElementById("open-kb").onclick = () => api().open_kb();

  waitForApi().then(() => switchTab("home"));
})();
