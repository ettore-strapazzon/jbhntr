// Boardroom live chat: poll for new messages every 2s and append them, so the
// Founder sees the CEO's reply without refreshing. Progressive enhancement — if
// this fails, the plain POST form still works. CSP-safe (served from 'self', no
// inline handlers; message bodies rendered via textContent, never innerHTML).
(function () {
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
