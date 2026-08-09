// Cookie notice. Informational only — the single cookie we set is strictly
// necessary, so nothing here gates functionality.
//
// NOTE: the dismiss handler is bound here rather than with an inline onclick,
// because our Content-Security-Policy forbids inline scripts. An inline
// handler silently does nothing (which is exactly the bug this fixes).
(function () {
  var note = document.getElementById("cookie-note");
  if (!note) return;

  var seen = false;
  try { seen = !!localStorage.getItem("cookie-note-seen"); } catch (e) {}
  if (!seen) note.hidden = false;

  var button = document.getElementById("cookie-note-dismiss");
  if (button) {
    button.addEventListener("click", function () {
      try { localStorage.setItem("cookie-note-seen", "1"); } catch (e) {}
      note.hidden = true;
    });
  }
})();

// Alpha banner. Rendered visible by default (so it shows even before JS, and for
// no-JS visitors); hidden here once the tester has dismissed it. CSP forbids
// inline handlers, so the dismiss is wired here like the cookie notice.
(function () {
  var banner = document.getElementById("alpha-banner");
  if (!banner) return;
  var seen = false;
  try { seen = !!localStorage.getItem("alpha-banner-seen"); } catch (e) {}
  if (seen) { banner.hidden = true; return; }
  var x = document.getElementById("alpha-dismiss");
  if (x) {
    x.addEventListener("click", function () {
      try { localStorage.setItem("alpha-banner-seen", "1"); } catch (e) {}
      banner.hidden = true;
    });
  }
})();

// Funnel bars (V3) animate in once, the first time they scroll into view.
// Respects prefers-reduced-motion and degrades to "just show them" without
// IntersectionObserver. Inline scripts are CSP-forbidden, so this lives here.
(function () {
  var funnels = document.querySelectorAll(".funnel");
  if (!funnels.length) return;
  var reduce = window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduce || !("IntersectionObserver" in window)) {
    funnels.forEach(function (f) { f.classList.add("in"); });
    return;
  }
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (en) {
      if (en.isIntersecting) { en.target.classList.add("in"); io.unobserve(en.target); }
    });
  }, { threshold: 0.35 });
  funnels.forEach(function (f) { io.observe(f); });
})();

// Mobile full-nav sheet (Round 6). The button lives in the header; the panel is
// in normal flow beneath it. CSP forbids inline handlers, so it is wired here.
(function () {
  var toggle = document.querySelector(".nav-toggle");
  var menu = document.getElementById("mobile-menu");
  if (!toggle || !menu) return;
  function close() {
    menu.hidden = true;
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-label", "Open menu");
  }
  function open() {
    menu.hidden = false;
    toggle.setAttribute("aria-expanded", "true");
    toggle.setAttribute("aria-label", "Close menu");
  }
  toggle.addEventListener("click", function () {
    if (menu.hidden) { open(); } else { close(); }
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !menu.hidden) { close(); toggle.focus(); }
  });
  document.addEventListener("click", function (e) {
    if (menu.hidden) return;
    if (menu.contains(e.target) || toggle.contains(e.target)) return;
    close();
  });
  menu.addEventListener("click", function (e) {
    if (e.target.closest("a")) close();   // navigating away — collapse the sheet
  });
})();

// Live counter for the 300-character feedback boxes.
document.addEventListener("input", function (e) {
  if (e.target && e.target.matches("textarea[data-counter]")) {
    var max = parseInt(e.target.getAttribute("maxlength") || "300", 10);
    var out = document.getElementById(e.target.getAttribute("data-counter"));
    if (out) out.textContent = (max - e.target.value.length) + " left";
  }
});

// Toast + nav pulse when a job is saved to My Jobs.
(function () {
  function showToast(msg, href) {
    var slot = document.getElementById('toast-slot');
    if (!slot) return;
    slot.innerHTML =
      '<div class="toast" role="status">' +
        '<span></span> ' +
        '<a></a>' +
        '<button class="toast-x" aria-label="Dismiss">\u00d7</button>' +
      '</div>';
    var el = slot.firstChild;
    el.querySelector('span').textContent = msg;
    var link = el.querySelector('a');
    link.textContent = 'Open My Jobs \u2192';
    link.setAttribute('href', href);
    el.querySelector('.toast-x').addEventListener('click', function () { el.remove(); });
    setTimeout(function () { if (el) el.classList.add('out'); }, 5000);
    setTimeout(function () { if (el) el.remove(); }, 5600);
  }
  function pulseNav() {
    var nav = document.getElementById('nav-myjobs');
    if (!nav) return;
    nav.classList.add('pulse');
    setTimeout(function () { nav.classList.remove('pulse'); }, 2400);
  }
  document.body.addEventListener('jobSavedToMyJobs', function () {
    showToast('Job added to Your Jobs \u2014 Craft tailored CV and Cover Letter here to apply.', '/applications');
    pulseNav();
  });
})();
