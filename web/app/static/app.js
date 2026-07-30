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

// Live counter for the 300-character feedback boxes.
document.addEventListener("input", function (e) {
  if (e.target && e.target.matches("textarea[data-counter]")) {
    var max = parseInt(e.target.getAttribute("maxlength") || "300", 10);
    var out = document.getElementById(e.target.getAttribute("data-counter"));
    if (out) out.textContent = (max - e.target.value.length) + " left";
  }
});
