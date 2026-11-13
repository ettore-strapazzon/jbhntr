// R3-03 /invite — copy buttons, mobile native share, and the invite_link_copied
// beacon. Loaded only by invite.html. CSP forbids inline handlers, so everything
// is wired here from data-attributes (same pattern as app.js's [data-copy]).
(function () {
  "use strict";

  function beacon(channel, source) {
    try {
      var body = new URLSearchParams();
      body.append("channel", channel);
      body.append("source", source);
      fetch("/invite/copied", {
        method: "POST", body: body, credentials: "same-origin", keepalive: true,
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
      }).catch(function () {});
    } catch (e) { /* analytics must never break the page */ }
  }

  function failNote(btn) {
    var box = btn.closest(".invite-row, .invite-msg");
    var n = box && (box.classList.contains("invite-msg")
      ? box.querySelector(".invite-copy-fail")
      : box.nextElementSibling);
    return n && n.classList.contains("invite-copy-fail") ? n : null;
  }

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      try {
        var ta = document.createElement("textarea");
        ta.value = text; ta.setAttribute("readonly", "");
        ta.style.position = "fixed"; ta.style.opacity = "0";
        document.body.appendChild(ta); ta.select();
        var ok = document.execCommand("copy");
        document.body.removeChild(ta);
        ok ? resolve() : reject();
      } catch (e) { reject(e); }
    });
  }

  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("[data-invite-copy]");
    if (btn) {
      var src = document.querySelector(btn.getAttribute("data-invite-copy"));
      if (!src) return;
      var label = btn.getAttribute("data-label") || btn.textContent;
      btn.setAttribute("data-label", label);
      var note = failNote(btn);
      copyText(src.value).then(function () {
        if (note) note.hidden = true;
        btn.textContent = "Copied";
        setTimeout(function () { btn.textContent = label; }, 2000);
        beacon(btn.getAttribute("data-channel"), "copy");
      }).catch(function () {
        if (note) note.hidden = false;
        if (src.select) src.select();
      });
      return;
    }
    var intent = e.target.closest && e.target.closest("[data-invite-intent]");
    if (intent) {
      beacon(intent.getAttribute("data-channel"), "intent");   // link still opens
      return;
    }
    var native = e.target.closest && e.target.closest("[data-invite-native]");
    if (native && navigator.share) {
      navigator.share({
        text: native.getAttribute("data-share-text"),
        url: native.getAttribute("data-share-url"),
      }).then(function () { beacon("native", "intent"); }).catch(function () {});
    }
  });

  // "Share…" only where a native share sheet exists (mobile).
  var mobile = window.matchMedia && window.matchMedia("(pointer: coarse)").matches;
  if (navigator.share && mobile) {
    [].forEach.call(document.querySelectorAll("[data-invite-native]"), function (b) {
      b.hidden = false;
    });
  }
})();
