/* Pulseboard - global UI behaviour (theme, nav, toasts, forms, count-up) */
(function () {
  'use strict';

  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var root = document.documentElement;
  var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var PB = window.PB = { reduced: reduced };

  function fmt(n, d) {
    return Number(n).toLocaleString('en-US', { minimumFractionDigits: d || 0, maximumFractionDigits: d || 0 });
  }
  PB.fmt = fmt;

  /* ---------- count-up numbers ---------- */
  PB.countUp = function (el, target, opts) {
    opts = opts || {};
    var dec = opts.decimals || 0;
    target = Number(target) || 0;
    if (reduced || target === 0) { el.textContent = fmt(target, dec); return; }
    var dur = opts.duration || 1300, start = null;
    if (el._raf) cancelAnimationFrame(el._raf);
    function step(ts) {
      if (start === null) start = ts;
      var t = Math.min((ts - start) / dur, 1);
      var e = t === 1 ? 1 : 1 - Math.pow(2, -10 * t);
      el.textContent = fmt(target * e, dec);
      if (t < 1) el._raf = requestAnimationFrame(step);
    }
    el._raf = requestAnimationFrame(step);
  };
  $$('[data-count]').forEach(function (el) { PB.countUp(el, el.getAttribute('data-count'), { duration: 1100 }); });

  /* ---------- theme ---------- */
  function setTheme(t) {
    root.dataset.theme = t;
    try { localStorage.setItem('pb-theme', t); } catch (e) {}
    document.dispatchEvent(new CustomEvent('themechange', { detail: t }));
  }
  $$('[data-theme-toggle]').forEach(function (b) {
    b.addEventListener('click', function () { setTheme(root.dataset.theme === 'dark' ? 'light' : 'dark'); });
  });

  /* ---------- sidebar (mobile) ---------- */
  var burger = $('#burger'), scrim = $('#scrim');
  function closeNav() { document.body.classList.remove('nav-open'); }
  if (burger) burger.addEventListener('click', function () { document.body.classList.toggle('nav-open'); });
  if (scrim) scrim.addEventListener('click', closeNav);
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeNav(); });

  /* ---------- toasts ---------- */
  function dismiss(t) {
    if (t._gone) return;
    t._gone = true;
    t.classList.add('out');
    setTimeout(function () { if (t.parentNode) t.parentNode.removeChild(t); }, 380);
  }
  $$('.toast').forEach(function (t, i) {
    t.style.animationDelay = (i * 90) + 'ms';
    setTimeout(function () { dismiss(t); }, 5600 + i * 400);
    var x = $('.toast-x', t);
    if (x) x.addEventListener('click', function () { dismiss(t); });
  });

  /* ---------- password show/hide + strength ---------- */
  $$('[data-toggle-pw]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var input = $('input', btn.parentNode);
      var show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      btn.classList.toggle('on', show);
      btn.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
    });
  });
  $$('input[data-strength]').forEach(function (input) {
    var meter = $(input.getAttribute('data-strength'));
    if (!meter) return;
    var note = $('em', meter);
    var labels = ['Use 8 or more characters with a letter and a number.', 'Weak. Add more characters.', 'Fair. Mix upper and lower case.', 'Good. Add a symbol to make it stronger.', 'Strong password.'];
    input.addEventListener('input', function () {
      var v = input.value, s = 0;
      if (v.length >= 8) s++;
      if (/[a-z]/.test(v) && /[A-Z]/.test(v)) s++;
      if (/\d/.test(v) && /[A-Za-z]/.test(v)) s++;
      if (/[^A-Za-z0-9]/.test(v) || v.length >= 14) s++;
      if (!v) s = 0;
      meter.setAttribute('data-level', s);
      if (note) note.textContent = labels[s];
    });
  });

  /* ---------- demo account buttons ---------- */
  $$('[data-fill-email]').forEach(function (b) {
    b.addEventListener('click', function () {
      var e = $('#email'), p = $('#password');
      if (e) e.value = b.getAttribute('data-fill-email');
      if (p) p.value = b.getAttribute('data-fill-pass');
      if (p) p.focus();
    });
  });

  /* ---------- button ripple ---------- */
  document.addEventListener('click', function (e) {
    var btn = e.target.closest && e.target.closest('.btn');
    if (!btn || reduced) return;
    var r = btn.getBoundingClientRect(), size = Math.max(r.width, r.height);
    var s = document.createElement('span');
    s.className = 'ripple';
    s.style.width = s.style.height = size + 'px';
    s.style.left = (e.clientX - r.left - size / 2) + 'px';
    s.style.top = (e.clientY - r.top - size / 2) + 'px';
    btn.appendChild(s);
    setTimeout(function () { if (s.parentNode) s.parentNode.removeChild(s); }, 650);
  });

  /* ---------- KPI spotlight ---------- */
  $$('.kpi').forEach(function (k) {
    k.addEventListener('pointermove', function (e) {
      var r = k.getBoundingClientRect();
      k.style.setProperty('--mx', (e.clientX - r.left) + 'px');
      k.style.setProperty('--my', (e.clientY - r.top) + 'px');
    });
  });

  /* ---------- forms: confirm, autosubmit, print ---------- */
  $$('form[data-confirm]').forEach(function (f) {
    f.addEventListener('submit', function (e) {
      if (!window.confirm(f.getAttribute('data-confirm'))) e.preventDefault();
    });
  });
  $$('select[data-autosubmit]').forEach(function (s) {
    s.addEventListener('change', function () { s.form.requestSubmit ? s.form.requestSubmit() : s.form.submit(); });
  });
  $$('[data-print]').forEach(function (b) { b.addEventListener('click', function () { window.print(); }); });

  /* ---------- report images fade in ---------- */
  $$('.figure img').forEach(function (img) {
    var show = function () { img.classList.add('loaded'); };
    if (img.complete) show(); else { img.addEventListener('load', show); img.addEventListener('error', show); }
  });
})();
