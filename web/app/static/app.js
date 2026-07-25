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

// Live counter for the 300-character feedback boxes.
document.addEventListener("input", function (e) {
  if (e.target && e.target.matches("textarea[data-counter]")) {
    var max = parseInt(e.target.getAttribute("maxlength") || "300", 10);
    var out = document.getElementById(e.target.getAttribute("data-counter"));
    if (out) out.textContent = (max - e.target.value.length) + " left";
  }
});
