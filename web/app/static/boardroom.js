// Boardroom: tab switching, per-agent team filter, and live chat (poll every 2s
// and append new messages so the Founder sees the CEO reply without refreshing).
// Progressive enhancement — if this fails, the plain POST form still works.
// CSP-safe: served from 'self', no inline handlers; bodies rendered via textContent.
(function () {
  // ---- Times (R3-49): the server sends ISO UTC; every timestamp shows in the browser's zone,
  // 24 h, short zone name, UTC in the tooltip. Pure functions (tested in node) up to the end marker.
  function parseTime(iso) {
    if (iso == null || iso === "") return null;
    var t = Date.parse(String(iso).replace(/(\.\d{3})\d+/, "$1"));   // Python sends microseconds; older Safari rejects them
    return isNaN(t) ? null : new Date(t);
  }
  function zoneName(d, tz) {   // "CET"/"EST" where a short name exists, else "GMT+9"
    function get(loc) {
      try {
        var ps = new Intl.DateTimeFormat(loc, { timeZone: tz, timeZoneName: "short" }).formatToParts(d);
        for (var k = 0; k < ps.length; k++) if (ps[k].type === "timeZoneName") return ps[k].value;
      } catch (e) {}
      return "";
    }
    var z = get("en-GB"), u;
    if (!z || /^GMT[+-]/.test(z)) { u = get("en-US"); if (u && !/^GMT[+-]/.test(u)) z = u; }
    return z;
  }
  function fmt_time(iso, tz) {   // tz omitted = the browser's zone
    var d = parseTime(iso);
    if (!d) return iso == null || iso === "" ? "" : String(iso) + " UTC";
    try {
      var p = {};
      new Intl.DateTimeFormat("en-GB", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit", hourCycle: "h23" })
        .formatToParts(d).forEach(function (x) { p[x.type] = x.value; });
      return (p.year + "-" + p.month + "-" + p.day + " " + p.hour + ":" + p.minute + " " + zoneName(d, tz)).trim();
    } catch (e) { return String(iso) + " UTC"; }
  }
  function utc_time(iso) { return fmt_time(iso, "UTC"); }
  // ---- end times
  // ---- Working (R3-46): rows newest first ({key, status, cycle, iso}) → per row "12 min" if that
  // `started` row is still working, else "". Same rule as _team_feed() on the server. Pure (tested in node).
  var WORKING_MAX_H = 6, WORK_END = ["shipped", "blocked", "review"];
  function elapsed(ms) {
    var m = Math.max(0, Math.floor(ms / 60000));
    return m < 60 ? m + " min" : Math.floor(m / 60) + " h " + (m % 60) + " min";
  }
  function workingNow(rows, now) {
    var ended = {};
    return rows.map(function (r) {
      var k = JSON.stringify([r.key, r.cycle]), d = parseTime(r.iso), out = "";
      if (r.status === "started" && !ended[k] && d && now - d < WORKING_MAX_H * 36e5) out = elapsed(now - d);
      if (WORK_END.indexOf(r.status) >= 0) ended[k] = true;
      return out;
    });
  }
  // ---- end working
  // ---- Code vs prose (R3-48): each shell command in a chat message gets its own block with a copy
  // button. A command = first word is a shell/PowerShell command (or ./x, ~/x, $var=, a Verb-Noun cmdlet),
  // on an indented line, after "Verify:/Run:/Then:/Check:", or inside a ``` fence. Tested in node up to the end marker.
  var CMD = /^(?:(?:git|python3?|py|pip3?|node|npm|npx|ssh|scp|sudo|cd|ls|cat|tail|head|grep|cut|awk|sed|curl(?:\.exe)?|wget|crontab|systemctl|journalctl|date|echo|export|source|bash|sh|mkdir|cp|mv|chmod|tar|docker|psql|railway|gh|uv|nano|ps|uptime|which|winget|powershell|pytest|alembic|uvicorn|[A-Z][a-z]+-[A-Z][A-Za-z]+)(?=\s|$)|exit$|\.\/\S|~\/\S|\$\w+\s*=|\$env:)/;
  // English words that are also commands: "  date is fine." / "  cat the logs" stay prose.
  var PROSE = /^(?:cat|date|head|tail|cut|source|export|echo|which|cd|cp|mv|ps|sh)\s+[A-Za-z]+(?:\s+[A-Za-z,']+)+[.!?]?$/;
  function isCommand(s) { s = String(s).trim(); return CMD.test(s) && !/[a-z]{2}\.$/.test(s) && !PROSE.test(s); }
  function cmdLine(l) {   // indented command line, or "Verify: <command>" -> { label, cmd }; anything else -> null
    var m = /^(\s*)(?:(Verify|Run|Then|Check):\s+)?(\S.*?)\s*$/.exec(l);
    if (!m || (!m[2] && m[1].length < 2) || !isCommand(m[3])) return null;
    return { label: m[2] ? m[1] + m[2] + ":" : "", cmd: m[3] };
  }
  function fenceBlocks(code) {   // a fence of single-line commands -> one block each; any other fence stays whole
    var ls = code.filter(function (x) { return x.trim(); });
    var split = ls.length > 1 && ls.every(function (x) { return isCommand(x) && !/[\\`^]$/.test(x.trim()); });
    return split ? ls.map(function (x) { return x.trim(); }) : [code.join("\n")];
  }
  function parts(src) {   // chat text -> [{k:"text"|"block", v}]
    var lines = String(src).replace(/\r/g, "").split("\n"), out = [], buf = [], i = 0;
    function flush() { if (buf.length) out.push({ k: "text", v: buf.join("\n") }); buf = []; }
    function block(v) { flush(); out.push({ k: "block", v: v }); }
    while (i < lines.length) {
      var l = lines[i];
      if (/^\s*```/.test(l)) { var code = []; i++; while (i < lines.length && !/^\s*```/.test(lines[i])) code.push(lines[i++]); i++; fenceBlocks(code).forEach(block); continue; }
      var c = cmdLine(l);
      if (c) { if (c.label) buf.push(c.label); block(c.cmd); i++; continue; }
      buf.push(l); i++;
    }
    flush();
    return out;
  }
  function rich(box, body) {   // fill box with text nodes + code blocks (DOM + textContent only)
    box.textContent = "";
    parts(body).forEach(function (p) {
      if (p.k !== "block") { box.appendChild(document.createTextNode(p.v)); return; }
      var w = document.createElement("div"), pre = document.createElement("pre"), code = document.createElement("code"),
          b = document.createElement("button");
      w.className = "cb"; code.textContent = p.v; pre.appendChild(code); w.appendChild(pre);
      b.type = "button"; b.className = "copy"; b.textContent = "copy"; b.setAttribute("aria-label", "Copy command");
      w.appendChild(b); box.appendChild(w);
    });
    return box;
  }
  function copyText(t) {   // Clipboard API on https, else a hidden-textarea fallback
    function legacy() {
      var ta = document.createElement("textarea"); ta.value = t; ta.setAttribute("readonly", "");
      ta.style.position = "fixed"; ta.style.top = "0"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select(); var ok = false;
      try { ok = document.execCommand("copy"); } catch (e) {}
      document.body.removeChild(ta);
      return ok ? Promise.resolve() : Promise.reject(new Error("copy"));
    }
    return navigator.clipboard && window.isSecureContext ? navigator.clipboard.writeText(t).catch(legacy) : legacy();
  }
  function onCopy(e) {
    var b = e.target.closest("button.copy"); if (!b) return;
    var code = b.parentNode.querySelector("code"); if (!code) return;
    copyText(code.textContent).then(function () { b.textContent = "copied"; }, function () { b.textContent = "select + Ctrl+C"; });
    clearTimeout(b._t); b._t = setTimeout(function () { b.textContent = "copy"; }, 1500);
  }
  // ---- end code
  // ---- Documents (R3-51): every company/ file in fixed-order groups (CHARTER, state, updates, agents, docs,
  // other folders, top-level files), a filter that needs every typed term in the path, and a viewer whose
  // relative links stay inside company/. DOM + textContent only. Tested in node up to the end marker.
  var DOC_GROUPS = ["CHARTER", "state", "updates", "agents", "docs"];
  function docEl(tag, cls, text) { var n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; }
  function docGroup(p) { return p.indexOf("/") < 0 ? (p === "CHARTER.md" ? "CHARTER" : "root") : p.split("/")[0]; }
  function docTree(paths, q) {   // -> { total, shown, groups: [{ name, files }] }
    var terms = String(q || "").toLowerCase().split(/\s+/).filter(Boolean), by = {}, shown = 0;
    paths.slice().sort().forEach(function (p) {
      var lp = p.toLowerCase();
      if (!terms.every(function (t) { return lp.indexOf(t) >= 0; })) return;
      var g = docGroup(p); (by[g] = by[g] || []).push(p); shown++;
    });
    function rank(g) { var i = DOC_GROUPS.indexOf(g); return i >= 0 ? i : g === "root" ? 99 : 50; }
    var names = Object.keys(by).sort(function (a, b) { return rank(a) - rank(b) || (a < b ? -1 : a > b ? 1 : 0); });
    return { total: paths.length, shown: shown, groups: names.map(function (g) { return { name: g, files: by[g] }; }) };
  }
  function resolveDoc(href, from) {   // [x](y.md) seen in company/<from> -> company/-relative path, or null
    var h = String(href || "").split(/[?#]/)[0];
    if (!h || /^[a-z][a-z0-9+.-]*:/i.test(h) || !/\.(md|txt|csv)$/i.test(h)) return null;
    var segs = (h.charAt(0) === "/" ? h : String(from || "").split("/").slice(0, -1).join("/") + "/" + h).split("/"), out = [];
    for (var i = 0; i < segs.length; i++) {
      if (segs[i] === "..") { if (!out.length) return null; out.pop(); }   // climbing out of company/ is refused
      else if (segs[i] && segs[i] !== ".") out.push(segs[i]);
    }
    return out.join("/");
  }
  function docLink(label, href, from) {   // http(s) -> new tab; company doc -> viewer; anything else -> plain text
    var a;
    if (/^https?:\/\//i.test(href)) { a = docEl("a", null, label); a.href = href; a.target = "_blank"; a.rel = "noopener noreferrer"; return a; }
    var t = resolveDoc(href, from);
    if (!t) return docEl("span", null, label);
    a = docEl("a", null, label); a.href = "/boardroom/doc?path=" + encodeURIComponent(t); a.setAttribute("data-doc", t);
    return a;
  }
  function docInline(parent, s, from) {   // **bold**, `code`, [label](href), *em*; the rest stays text nodes
    var re = /\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\(([^)\s]+)\)|\*([^*\s][^*]*)\*/g, m, last = 0;
    s = String(s);
    while ((m = re.exec(s))) {
      if (m.index > last) parent.appendChild(document.createTextNode(s.slice(last, m.index)));
      if (m[1] != null) parent.appendChild(docEl("strong", null, m[1]));
      else if (m[2] != null) parent.appendChild(docEl("code", null, m[2]));
      else if (m[3] != null) parent.appendChild(docLink(m[3], m[4], from));
      else parent.appendChild(docEl("em", null, m[5]));
      last = re.lastIndex;
    }
    if (last < s.length) parent.appendChild(document.createTextNode(s.slice(last)));
    return parent;
  }
  function docMd(src, from) {   // the Markdown our docs use: fences, headings, tables, rules, quotes, lists, paragraphs
    var root = docEl("div"), lines = String(src).replace(/\r/g, "").split("\n"), i = 0, list = null, l, m;
    var ROW = /^\s*\|.*\|\s*$/, BLOCK = /^\s*(```|#{1,6}\s|\||>|(?:[-*+]|\d+[.)])\s|(?:---|\*\*\*|___)\s*$)/;
    while (i < lines.length) {
      l = lines[i];
      if (!/^\s*(?:[-*+]|\d+[.)])\s/.test(l)) list = null;
      if (/^\s*```/.test(l)) {
        var code = []; i++;
        while (i < lines.length && !/^\s*```/.test(lines[i])) code.push(lines[i++]);
        i++; var pre = docEl("pre"); pre.appendChild(docEl("code", null, code.join("\n"))); root.appendChild(pre);
      } else if ((m = /^(#{1,6})\s+(.*)$/.exec(l))) {
        root.appendChild(docInline(docEl("h" + Math.min(m[1].length + 2, 6)), m[2], from)); i++;   // h2 is the viewer title
      } else if (ROW.test(l)) {
        var t = docEl("table"), k = 0;   // shortcut: a `|` inside backticks splits the cell; fine for our tables
        while (i < lines.length && ROW.test(lines[i])) {
          var r = lines[i++].trim();
          if (/^\|[\s:|-]+\|$/.test(r)) continue;
          var tr = docEl("tr"), cell = k++ ? "td" : "th";
          r.slice(1, -1).split("|").forEach(function (c) { tr.appendChild(docInline(docEl(cell), c.trim(), from)); });
          t.appendChild(tr);
        }
        root.appendChild(t);
      } else if (/^\s*(?:---|\*\*\*|___)\s*$/.test(l)) { root.appendChild(docEl("hr")); i++; }
      else if (/^>\s?/.test(l)) { root.appendChild(docInline(docEl("blockquote"), l.replace(/^>\s?/, ""), from)); i++; }
      else if ((m = /^\s*(?:[-*+]|\d+[.)])\s+(.*)$/.exec(l))) {
        if (!list) { list = docEl(/^\s*\d/.test(l) ? "ol" : "ul"); root.appendChild(list); }
        list.appendChild(docInline(docEl("li"), m[1], from)); i++;
      } else if (!l.trim()) i++;
      else {
        var p = docInline(docEl("p"), l, from); i++;
        while (i < lines.length && lines[i].trim() && !BLOCK.test(lines[i])) { p.appendChild(document.createTextNode(" ")); docInline(p, lines[i++], from); }
        root.appendChild(p);
      }
    }
    return root;
  }
  function docBody(text, path) { return /\.(txt|csv)$/i.test(path || "") ? docEl("pre", "doc-txt", String(text)) : docMd(text, path); }
  // ---- end documents
  function localise(t) {   // a <time datetime="ISO UTC"> → local text + UTC tooltip
    var iso = t.getAttribute("datetime");
    t.textContent = fmt_time(iso);
    t.title = utc_time(iso);
  }
  function timeEl(iso) {
    var t = document.createElement("time");
    t.setAttribute("datetime", iso || "");
    localise(t);
    return t;
  }
  document.querySelectorAll("time[datetime]").forEach(localise);   // server-rendered first load

  // ---- Tabs ----
  var tabsNav = document.getElementById("tabs");
  var panels = document.querySelectorAll(".panel");
  function activate(name) {
    var found = false;
    document.querySelectorAll(".tab").forEach(function (t) {
      var on = t.getAttribute("data-tab") === name;
      t.classList.toggle("active", on);
      if (on) found = true;
    });
    panels.forEach(function (p) {
      p.classList.toggle("active", p.getAttribute("data-panel") === name);
    });
    if (found) { try { localStorage.setItem("jbhntr:board-tab", name); } catch (e) {} }
    return found;
  }
  if (tabsNav) {
    tabsNav.addEventListener("click", function (e) {
      var btn = e.target.closest(".tab");
      if (btn) activate(btn.getAttribute("data-tab"));
    });
    var start = "main";
    try { start = localStorage.getItem("jbhntr:board-tab") || "main"; } catch (e) {}
    if (!activate(start)) activate("main");
  }

  // ---- Live team feed (poll + prepend newest on top) ----
  var filters = document.getElementById("team-filters");
  var teamLog = document.getElementById("team-log");
  var teamEmpty = document.getElementById("team-empty");
  var teamFilter = "";

  function applyTeamFilter(agent) {
    teamFilter = agent;
    if (filters) {
      filters.querySelectorAll("button").forEach(function (b) {
        b.classList.toggle("active", (b.getAttribute("data-agent") || "") === agent);
      });
    }
    if (teamLog) {
      teamLog.querySelectorAll(".tl").forEach(function (row) {
        row.hidden = agent !== "" && row.getAttribute("data-agent") !== agent;
      });
    }
  }
  if (filters) {
    filters.addEventListener("click", function (e) {
      var btn = e.target.closest("button");
      if (btn) applyTeamFilter(btn.getAttribute("data-agent") || "");
    });
  }

  function ensureFilterBtn(agent) {
    if (!filters || !agent) return;
    if (filters.querySelector('button[data-agent="' + agent.replace(/"/g, "") + '"]')) return;
    var b = document.createElement("button");
    b.type = "button";
    b.setAttribute("data-agent", agent);
    b.textContent = agent;
    filters.appendChild(b);
  }

  function addTeam(e) {
    var row = document.createElement("div");
    row.className = "tl";
    row.setAttribute("data-agent", e.agent || "");
    row.setAttribute("data-key", e.key || "");
    row.setAttribute("data-status", e.status || "");
    row.setAttribute("data-cycle", e.cycle || "");
    var meta = document.createElement("div");
    meta.className = "tl-meta";
    var ag = document.createElement("span");
    ag.className = "tl-agent";
    ag.textContent = e.agent || "—";
    meta.appendChild(ag);
    var bits = [];
    if (e.status) bits.push(e.status);
    if (e.cycle) bits.push("cycle " + e.cycle);
    if (bits.length) {
      var rest = document.createElement("span");
      rest.textContent = " · " + bits.join(" · ");
      meta.appendChild(rest);
    }
    if (e.ts) { meta.appendChild(document.createTextNode(" · ")); meta.appendChild(timeEl(e.ts)); }
    row.appendChild(meta);
    if (e.task) {
      var t = document.createElement("div");
      var b = document.createElement("b");
      b.textContent = e.task;
      t.appendChild(b);
      row.appendChild(t);
    }
    if (e.summary) {
      var s = document.createElement("div");
      s.className = "msg-body";
      s.textContent = e.summary;
      row.appendChild(s);
    }
    if (e.detail_html) {
      var d = document.createElement("details");
      d.className = "tl-detail";
      var sm = document.createElement("summary");
      sm.textContent = "Details";
      d.appendChild(sm);
      var body = document.createElement("div");
      body.innerHTML = e.detail_html; // server-sanitised by _safe_html (no raw HTML, no links)
      d.appendChild(body);
      row.appendChild(d);
    }
    if (teamFilter && (e.agent || "") !== teamFilter) row.hidden = true;
    teamLog.insertBefore(row, teamLog.firstChild);
    ensureFilterBtn(e.agent);
    if (teamEmpty) teamEmpty.hidden = true;
  }

  // Badge text, not colour only: "working now · 12 min", recomputed from the DOM rows.
  function refreshWorking() {
    var rows = Array.prototype.slice.call(teamLog.querySelectorAll(".tl"));
    var live = workingNow(rows.map(function (r) {
      var t = r.querySelector("time[datetime]");
      return { key: r.getAttribute("data-key") || "", status: r.getAttribute("data-status") || "",
               cycle: r.getAttribute("data-cycle") || "", iso: t ? t.getAttribute("datetime") : "" };
    }), Date.now());
    rows.forEach(function (r, i) {
      var w = r.querySelector(".tl-working"), meta = r.querySelector(".tl-meta");
      if (!live[i]) { if (w) w.remove(); return; }
      if (!w && meta) {
        w = document.createElement("span");
        w.className = "tl-working";
        meta.appendChild(document.createTextNode(" "));
        meta.appendChild(w);
      }
      if (w) w.textContent = "working now · " + live[i];
    });
  }

  if (teamLog) {
    var teamLast = parseInt(teamLog.getAttribute("data-last") || "0", 10) || 0;
    var pollTeam = function () {
      fetch("/boardroom/team.json?after=" + teamLast, { headers: { Accept: "application/json" } })
        .then(function (r) { return r.ok ? r.json() : []; })
        .then(function (rows) {
          rows.forEach(function (e) {
            if (e.id > teamLast) teamLast = e.id;
            addTeam(e);
          });
          refreshWorking();
        })
        .catch(function () {});
    };
    setInterval(pollTeam, 3000);
    refreshWorking();
    setInterval(refreshWorking, 30000);
  }

  // ---- Founder's tasks (R3-45): keep only the Founder's deviations from the server default
  // (open request = expanded, later/closed + groups = collapsed), per R id / group, in localStorage.
  // Pure (tested via node): a toggle back to the default forgets the choice, so a status change gets the new default.
  function reqToggle(mem, id, open, def) { if (open === def) delete mem[id]; else mem[id] = open; return mem; }
  var REQ_KEY = "jbhntr:req-open", reqMem = {};
  try { reqMem = JSON.parse(localStorage.getItem(REQ_KEY) || "{}") || {}; } catch (e) {}
  document.querySelectorAll("details[data-req], details[data-group]").forEach(function (d) {
    var id = d.getAttribute("data-req") || "group:" + d.getAttribute("data-group");
    var def = d.hasAttribute("open");
    if (typeof reqMem[id] === "boolean") d.open = reqMem[id];
    d.addEventListener("toggle", function () {
      reqToggle(reqMem, id, d.open, def);
      try { localStorage.setItem(REQ_KEY, JSON.stringify(reqMem)); } catch (e) {}
    });
  });

  // ---- Documents tab + viewer (R3-51) ----
  var docsTree = document.getElementById("docs-tree"), docsFilter = document.getElementById("docs-filter"),
      docsCount = document.getElementById("docs-count"), viewer = document.getElementById("viewer"), docPaths = [], docFrom = null;
  try { docPaths = JSON.parse(docsTree.getAttribute("data-paths") || "[]"); } catch (e) {}
  function renderDocs() {
    var q = docsFilter.value.trim(), t = docTree(docPaths, q);
    docsTree.textContent = "";
    docsCount.textContent = t.shown + " of " + t.total + " files";
    if (!t.shown) docsTree.appendChild(docEl("p", "muted", t.total ? "No file matches “" + q + "”." : "No documents yet."));
    t.groups.forEach(function (g) {
      var d = docEl("details", "docs-group"), lastDir = null;
      d.open = !!q || g.name === "CHARTER";
      var sum = docEl("summary", null, g.name === "root" ? "Top-level files" : g.name === "CHARTER" ? "CHARTER" : g.name + "/");
      sum.appendChild(docEl("span", "n", String(g.files.length)));
      d.appendChild(sum);
      g.files.forEach(function (p) {
        var dir = p.split("/").slice(1, -1).join("/"), a = docEl("a", dir ? "sub" : null, p.split("/").pop());
        if (dir && dir !== lastDir) d.appendChild(docEl("div", "dir", dir + "/"));
        lastDir = dir;
        a.href = "/boardroom/doc?path=" + encodeURIComponent(p); a.title = p;
        if (!/\.pdf$/i.test(p)) a.setAttribute("data-doc", p);   // a PDF downloads; text opens in the viewer
        d.appendChild(a);
      });
      docsTree.appendChild(d);
    });
  }
  function openDoc(p) {
    var body = document.getElementById("viewer-body");
    if (viewer.hidden) docFrom = document.activeElement;
    document.getElementById("viewer-title").textContent = p;
    body.textContent = ""; body.appendChild(docEl("p", "muted", "Loading…"));
    viewer.hidden = false; viewer.scrollTop = 0;
    document.getElementById("viewer-close").focus();
    fetch("/boardroom/doc?raw=1&path=" + encodeURIComponent(p))
      .then(function (r) { return r.ok ? r.text() : Promise.reject(r.status); })
      .then(function (t) { body.textContent = ""; body.appendChild(docBody(t, p)); },
            function () { body.textContent = ""; body.appendChild(docEl("p", "muted", "This document could not be opened (moved, deleted or not readable here).")); });
  }
  function closeDoc() { viewer.hidden = true; if (docFrom && docFrom.focus) docFrom.focus(); }
  if (docsTree && docsFilter && docsCount && viewer) {
    renderDocs();
    docsFilter.addEventListener("input", renderDocs);
    document.addEventListener("click", function (e) {
      var a = e.target.closest("a[data-doc]");
      if (!a || e.ctrlKey || e.metaKey || e.shiftKey || e.button) return;   // modified click: the href opens a full page
      e.preventDefault(); openDoc(a.getAttribute("data-doc"));
    });
    document.getElementById("viewer-close").addEventListener("click", closeDoc);
    viewer.addEventListener("click", function (e) { if (e.target === viewer) closeDoc(); });   // backdrop
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !viewer.hidden) closeDoc(); });
  }

  // ---- Live chat ----
  var thread = document.getElementById("thread");
  if (!thread) return;
  var last = parseInt(thread.getAttribute("data-last") || "0", 10) || 0;
  var typing = document.getElementById("ceo-typing");
  var emptyMsg = document.getElementById("thread-empty");
  var form = document.getElementById("chat-form");
  var toLatest = document.getElementById("to-latest");
  var first = true;
  document.querySelectorAll("#thread .msg-body").forEach(function (b) { rich(b, b.textContent); });   // server-rendered first load (R3-48)
  thread.addEventListener("click", onCopy);

  // Pure: is the box within `slack` px (default 80) of its end? (R3-44; tested via node)
  function nearBottom(box, slack) { return box.scrollHeight - box.scrollTop - box.clientHeight <= (slack == null ? 80 : slack); }
  function toBottom() { thread.scrollTop = thread.scrollHeight; if (toLatest) toLatest.hidden = true; }
  toBottom();
  thread.addEventListener("scroll", function () { if (toLatest && nearBottom(thread)) toLatest.hidden = true; });
  if (toLatest) toLatest.addEventListener("click", toBottom);
  // A hidden panel has no height, so scroll again once Main is shown.
  if (tabsNav) tabsNav.addEventListener("click", function (e) {
    var btn = e.target.closest(".tab");
    if (btn && btn.getAttribute("data-tab") === "main") toBottom();
  });
  // load doesn't bubble: capture it so any image in the thread (R3-50 thumbnails) re-sticks.
  thread.addEventListener("load", function (e) {
    if (e.target.tagName === "IMG" && nearBottom(thread, 200)) toBottom();
  }, true);

  function addMsg(m) {
    var wrap = document.createElement("div");
    wrap.className = "msg msg-" + m.role;
    var meta = document.createElement("div");
    meta.className = "msg-meta";
    var b = document.createElement("b");
    b.textContent = m.role_label;
    var sp = document.createElement("span");
    sp.className = "muted";
    sp.textContent = " · ";
    sp.appendChild(timeEl(m.ts));
    meta.appendChild(b);
    meta.appendChild(sp);
    var body = document.createElement("div");
    body.className = "msg-body";
    rich(body, m.body);
    wrap.appendChild(meta);
    wrap.appendChild(body);
    (m.attachments || []).forEach(function (a) {   // R3-40
      var d = document.createElement("div");
      d.className = "small";
      if (a.expired) {   // R3-43: file gone, no dead link
        d.className = "small muted";
        d.textContent = a.name + " (expired)";
      } else {
        var link = document.createElement("a");
        link.href = "/boardroom/attachment/" + encodeURIComponent(a.id);
        link.textContent = a.name;
        d.appendChild(link);
      }
      wrap.appendChild(d);
    });
    thread.appendChild(wrap);
    if (emptyMsg) emptyMsg.hidden = true;
  }

  function poll() {
    fetch("/boardroom/messages.json?after=" + last, { headers: { Accept: "application/json" } })
      .then(function (r) { return r.ok ? r.json() : []; })
      .then(function (rows) {
        var stick = first || nearBottom(thread);
        first = false;
        rows.forEach(function (m) {
          if (m.id > last) last = m.id;
          addMsg(m);
          if (m.role === "ceo" && typing) typing.hidden = true;
        });
        if (stick) toBottom(); else if (rows.length && toLatest) toLatest.hidden = false;
      })
      .catch(function () {});
  }
  setInterval(poll, 2000);

  if (form) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var ta = form.querySelector("textarea");
      var fileInput = form.querySelector('input[type="file"]');
      var err = document.getElementById("chat-error");
      var text = (ta.value || "").trim();
      var picked = fileInput ? Array.prototype.slice.call(fileInput.files) : [];
      if (!text && !picked.length) return;
      var body = new FormData();   // multipart: the browser sets the boundary header
      body.append("body", text);
      var tok = form.querySelector('input[name="csrf"]');
      body.append("csrf", tok ? tok.value : "");   // R3-19: send needs the admin CSRF token
      picked.forEach(function (f) { body.append("files", f); });
      if (err) err.hidden = true;
      fetch("/boardroom/send", { method: "POST", body: body })
        .then(function (r) {
          if (r.status === 400 && err) {   // a refused attachment: say why, keep the draft
            return r.text().then(function (t) { err.textContent = t; err.hidden = false; });
          }
          if (!r.ok) throw new Error("send " + r.status);   // don't clear a refused message
          ta.value = "";
          if (fileInput) fileInput.value = "";
          if (typing) typing.hidden = false;
          toBottom();
          poll();
        })
        .catch(function () { form.submit(); });
    });
  }
})();
