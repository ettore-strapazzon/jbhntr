// Boardroom: tab switching, per-agent team filter, and live chat (poll every 2s
// and append new messages so the Founder sees the CEO reply without refreshing).
// Progressive enhancement — if this fails, the plain POST form still works.
// CSP-safe: served from 'self', no inline handlers; bodies rendered via textContent.
(function () {
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
    if (e.ts) bits.push(e.ts);
    if (bits.length) {
      var rest = document.createElement("span");
      rest.textContent = " · " + bits.join(" · ");
      meta.appendChild(rest);
    }
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
      sm.textContent = "Detail";
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

  // ---- Live chat ----
  var thread = document.getElementById("thread");
  if (!thread) return;
  var last = parseInt(thread.getAttribute("data-last") || "0", 10) || 0;
  var typing = document.getElementById("ceo-typing");
  var emptyMsg = document.getElementById("thread-empty");
  var form = document.getElementById("chat-form");

  function addMsg(m) {
    var wrap = document.createElement("div");
    wrap.className = "msg msg-" + m.role;
    var meta = document.createElement("div");
    meta.className = "msg-meta";
    var b = document.createElement("b");
    b.textContent = m.role_label;
    var sp = document.createElement("span");
    sp.className = "muted";
    sp.textContent = " · " + m.ts;
    meta.appendChild(b);
    meta.appendChild(sp);
    var body = document.createElement("div");
    body.className = "msg-body";
    body.textContent = m.body;
    wrap.appendChild(meta);
    wrap.appendChild(body);
    thread.appendChild(wrap);
    if (emptyMsg) emptyMsg.hidden = true;
  }

  function poll() {
    fetch("/boardroom/messages.json?after=" + last, { headers: { Accept: "application/json" } })
      .then(function (r) { return r.ok ? r.json() : []; })
      .then(function (rows) {
        rows.forEach(function (m) {
          if (m.id > last) last = m.id;
          addMsg(m);
          if (m.role === "ceo" && typing) typing.hidden = true;
        });
      })
      .catch(function () {});
  }
  setInterval(poll, 2000);

  if (form) {
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var ta = form.querySelector("textarea");
      var text = (ta.value || "").trim();
      if (!text) return;
      var body = new URLSearchParams();
      body.append("body", text);
      var tok = form.querySelector('input[name="csrf"]');
      body.append("csrf", tok ? tok.value : "");   // R3-19: send needs the admin CSRF token
      fetch("/boardroom/send", {
        method: "POST",
        body: body,
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
      })
        .then(function (r) {
          if (!r.ok) throw new Error("send " + r.status);   // don't clear a refused message
          ta.value = "";
          if (typing) typing.hidden = false;
          poll();
        })
        .catch(function () { form.submit(); });
    });
  }
})();
