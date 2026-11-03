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

  // ---- Team filter ----
  var filters = document.getElementById("team-filters");
  var teamLog = document.getElementById("team-log");
  if (filters && teamLog) {
    filters.addEventListener("click", function (e) {
      var btn = e.target.closest("button");
      if (!btn) return;
      var agent = btn.getAttribute("data-agent") || "";
      filters.querySelectorAll("button").forEach(function (b) {
        b.classList.toggle("active", b === btn);
      });
      teamLog.querySelectorAll(".tl").forEach(function (row) {
        row.hidden = agent !== "" && row.getAttribute("data-agent") !== agent;
      });
    });
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
      fetch("/boardroom/send", {
        method: "POST",
        body: body,
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
      })
        .then(function () {
          ta.value = "";
          if (typing) typing.hidden = false;
          poll();
        })
        .catch(function () { form.submit(); });
    });
  }
})();
