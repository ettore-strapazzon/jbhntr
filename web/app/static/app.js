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

// Live formatted preview of the CV draft (best-effort match to the uploaded CV's
// style). Classifies each line and renders styled nodes; downloads use the same
// classifier so the file matches this preview.
(function () {
  var ed = document.getElementById('doc-editor');
  var pv = document.getElementById('doc-preview');
  if (!ed || !pv) return;
  var font = pv.getAttribute('data-font') || '';
  var accent = pv.getAttribute('data-accent') || '#1f2a24';
  var upper = pv.getAttribute('data-upper') === '1';
  var boldHeads = pv.getAttribute('data-bold') !== '0';
  pv.style.fontFamily = font;

  var BULLETS = '-\u2022*\u25aa\u25e6\u00b7';
  var PHONE = /\+?\d[\d\s()./-]{6,}\d/;

  // Mirror of export.py::_strip_md \u2014 keep the two in lock-step so the preview
  // and the downloaded file render identically.
  function stripMd(line) {
    return line
      .replace(/^\s{0,3}#{1,6}\s+/, '')
      .replace(/\*\*(.+?)\*\*/g, '$1')
      .replace(/__(.+?)__/g, '$1')
      .replace(/`([^`]+)`/g, '$1')
      .replace(/(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)/g, '$1');
  }

  var ROLE_DATE = /\([^)]*(?:(?:19|20)\d{2}|[Pp]resent)[^)]*\)/;
  var ORG_SEP = /\s[-\u2013\u2014]\s/;

  function toTitle(s) {
    return s.replace(/\w\S*/g, function (w) { return w.charAt(0).toUpperCase() + w.slice(1).toLowerCase(); });
  }
  function isRole(s) { return ROLE_DATE.test(s) && s.length <= 120; }
  function isHeading(s) {
    if (s.length > 40 || /[.,;]$/.test(s)) return false;
    if (s === s.toUpperCase() || s.slice(-1) === ':') return true;
    return s === toTitle(s) && s.split(/\s+/).length <= 5;
  }

  // Mirror of export.py::parse_lines \u2014 returns [{kind, text}].
  function parseLines(text) {
    var lines = text.split('\n');
    var stripped = lines.map(function (r) { return stripMd(r).trim(); });
    function nextIsRole(i) {
      for (var j = i + 1; j < stripped.length; j++) {
        if (stripped[j]) return isRole(stripped[j]);
      }
      return false;
    }
    var out = [];
    var seenName = false, seenHeading = false, subtitleDone = false;
    lines.forEach(function (raw, i) {
      var line = stripMd(raw);
      var s = line.trim();
      if (!s) { out.push({ kind: 'blank', text: '' }); return; }
      if (!seenName) { out.push({ kind: 'name', text: s }); seenName = true; return; }
      if (BULLETS.indexOf(s[0]) >= 0 && !(s.length > 1 && BULLETS.indexOf(s[1]) >= 0)) {
        out.push({ kind: 'bullet', text: s.replace(/^[-\u2022*\u25aa\u25e6\u00b7\s]+/, '') });
        return;
      }
      if (!seenHeading) {
        if (s.indexOf('@') >= 0 || PHONE.test(s)) { out.push({ kind: 'contact', text: s }); return; }
        if (isHeading(s)) { seenHeading = true; out.push({ kind: 'heading', text: s }); return; }
        if (!subtitleDone) { out.push({ kind: 'subtitle', text: s }); subtitleDone = true; return; }
        out.push(s.indexOf('|') >= 0 ? { kind: 'contact', text: s } : { kind: 'body', text: line });
        return;
      }
      if (isRole(s)) { out.push({ kind: 'role', text: s }); return; }
      var m = ORG_SEP.exec(s);
      var dashOrg = m && m.index <= 35 && s.length <= 90 && !/[.;:]$/.test(s);
      var peekOrg = nextIsRole(i) && s.length <= 90 && !/[.;:]$/.test(s);
      if (dashOrg || peekOrg) { out.push({ kind: 'org', text: s }); return; }
      if (isHeading(s)) { out.push({ kind: 'heading', text: s }); return; }
      out.push({ kind: 'body', text: line });
    });
    return out;
  }

  function render() {
    pv.textContent = '';                 // clear
    var ul = null;
    parseLines(ed.value || '').forEach(function (row) {
      var k = row.kind;
      if (k !== 'bullet') ul = null;
      if (k === 'blank') { pv.appendChild(document.createElement('br')); return; }
      if (k === 'name') {
        var n = document.createElement('div');
        n.className = 'pv-name';
        n.style.color = accent;
        n.textContent = row.text;      // keep the candidate's own casing
        pv.appendChild(n);
      } else if (k === 'subtitle') {
        var st = document.createElement('div');
        st.className = 'pv-sub';
        st.textContent = row.text;
        pv.appendChild(st);
      } else if (k === 'org') {
        var o = document.createElement('div');
        o.className = 'pv-org';
        var om = /\s[-–—]\s|,\s/.exec(row.text);
        var ob = document.createElement('b');
        ob.textContent = om ? row.text.slice(0, om.index) : row.text;
        o.appendChild(ob);
        if (om) {
          var os = document.createElement('span'); os.className = 'pv-muted';
          os.textContent = ' — ' + row.text.slice(om.index).replace(/^\s*[-–—,]\s*/, '');
          o.appendChild(os);
        }
        pv.appendChild(o);
      } else if (k === 'role') {
        var rl = document.createElement('div');
        rl.className = 'pv-role';
        var dm = row.text.match(/\([^)]*(?:(?:19|20)\d{2}|[Pp]resent)[^)]*\)/);
        var rb = document.createElement('b');
        rb.textContent = dm ? row.text.slice(0, dm.index).trim() : row.text;
        rl.appendChild(rb);
        if (dm) {
          var rs = document.createElement('span'); rs.className = 'pv-muted';
          rs.textContent = ' ' + row.text.slice(dm.index).trim();
          rl.appendChild(rs);
        }
        pv.appendChild(rl);
      } else if (k === 'contact') {
        var c = document.createElement('div');
        c.className = 'pv-contact';
        c.textContent = row.text;
        pv.appendChild(c);
      } else if (k === 'heading') {
        var h = document.createElement('div');
        h.className = 'pv-h';
        h.style.color = accent;
        if (!boldHeads) h.style.fontWeight = '600';
        h.textContent = upper ? row.text.toUpperCase() : row.text;
        pv.appendChild(h);
      } else if (k === 'bullet') {
        if (!ul) { ul = document.createElement('ul'); ul.className = 'pv-ul'; pv.appendChild(ul); }
        var li = document.createElement('li');
        li.textContent = row.text;
        ul.appendChild(li);
      } else {
        var p = document.createElement('div');
        p.className = 'pv-p';
        p.textContent = row.text;
        pv.appendChild(p);
      }
    });
  }

  ed.addEventListener('input', render);
  render();
})();
