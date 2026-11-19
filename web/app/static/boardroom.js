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
    // A later row for the same task ends any earlier "working now" badge.
    Array.prototype.forEach.call(teamLog.querySelectorAll(".tl"), function (r) {
      if (r.getAttribute("data-key") === (e.key || "")) {
        var w = r.querySelector(".tl-working");
        if (w) w.remove();
      }
    });
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
    if (e.status === "started") {
      var wk = document.createElement("span");
      wk.className = "tl-working";
      wk.textContent = "working now";
      meta.appendChild(document.createTextNode(" "));
      meta.appendChild(wk);
    }
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
        })
        .catch(function () {});
    };
    setInterval(pollTeam, 3000);
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

  // ---- Live chat ----
  var thread = document.getElementById("thread");
  if (!thread) return;
  var last = parseInt(thread.getAttribute("data-last") || "0", 10) || 0;
  var typing = document.getElementById("ceo-typing");
  var emptyMsg = document.getElementById("thread-empty");
  var form = document.getElementById("chat-form");
  var toLatest = document.getElementById("to-latest");
  var first = true;

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
    body.textContent = m.body;
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
