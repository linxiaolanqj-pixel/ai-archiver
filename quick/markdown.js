// 极简 Markdown 渲染器：标题 h1-h3 / 段落 / 有序 / 无序 / 加粗 / 行内代码 / 表格 / 引用。
window.renderMarkdown = (function () {
  function escapeHtml(s) {
    return String(s).replace(/[&<>]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c];
    });
  }
  function inline(s) {
    s = escapeHtml(s);
    s = s.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/`([^`\n]+)`/g, "<code>$1</code>");
    return s;
  }
  function stripBlocked(line) {
    return line.replace(/!\[[^\]]*\]\([^)]*\)/g, "");
  }
  function splitRow(line) {
    var s = line.trim().replace(/^\|/, "").replace(/\|$/, "");
    return s.split("|").map(function (c) { return c.trim(); });
  }
  function isDividerRow(line) {
    return /^\s*\|?[\s:|-]+\|[\s:|-]+\|?\s*$/.test(line) && /-/.test(line);
  }
  return function renderMarkdown(md) {
    if (!md) return "";
    var lines = md.replace(/\r\n/g, "\n").split("\n");
    var out = [];
    var inUl = false, inOl = false;
    var closeList = function () {
      if (inUl) { out.push("</ul>"); inUl = false; }
      if (inOl) { out.push("</ol>"); inOl = false; }
    };
    for (var i = 0; i < lines.length; i++) {
      var line = stripBlocked(lines[i]);

      // 表格：第一行 | a | b | + 第二行 | --- | --- |
      if (/^\s*\|/.test(line) && i + 1 < lines.length && isDividerRow(lines[i + 1])) {
        closeList();
        var header = splitRow(line);
        var trs = [];
        i += 2;
        while (i < lines.length && /^\s*\|/.test(lines[i])) {
          trs.push(splitRow(lines[i]));
          i++;
        }
        i--;
        out.push("<table><thead><tr>");
        header.forEach(function (h) { out.push("<th>" + inline(h) + "</th>"); });
        out.push("</tr></thead><tbody>");
        trs.forEach(function (row) {
          out.push("<tr>");
          row.forEach(function (c) { out.push("<td>" + inline(c) + "</td>"); });
          out.push("</tr>");
        });
        out.push("</tbody></table>");
        continue;
      }

      if (/^\s*(---|\*\*\*|___)\s*$/.test(line)) {
        closeList();
        out.push("<hr/>");
        continue;
      }
      var m = line.match(/^(#{1,3})\s+(.*)$/);
      if (m) {
        closeList();
        var lvl = m[1].length;
        out.push("<h" + lvl + ">" + inline(m[2]) + "</h" + lvl + ">");
        continue;
      }
      m = line.match(/^\s*>\s?(.*)$/);
      if (m) {
        closeList();
        out.push("<blockquote>" + inline(m[1]) + "</blockquote>");
        continue;
      }
      m = line.match(/^\s*(\d+)\.\s+(.*)$/);
      if (m) {
        if (!inOl) { closeList(); out.push("<ol>"); inOl = true; }
        out.push("<li>" + inline(m[2]) + "</li>");
        continue;
      }
      m = line.match(/^\s*[-*•]\s+(.*)$/);
      if (m) {
        if (!inUl) { closeList(); out.push("<ul>"); inUl = true; }
        out.push("<li>" + inline(m[1]) + "</li>");
        continue;
      }
      if (!line.trim()) { closeList(); continue; }
      closeList();
      out.push("<p>" + inline(line) + "</p>");
    }
    closeList();
    return out.join("");
  };
})();
