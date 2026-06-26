/* Shared site behavior — loaded with `defer` on every page.
   Page-agnostic only: bespoke homepage JS (hero PR-card, language toggle,
   feed teaser) stays inline in index.html. The anti-FOUC theme boot stays
   inline in each page <head> because it must run before first paint. */
(function () {
  'use strict';

  // Scroll-progress bar (driven by the --scroll-progress custom property).
  (function () {
    var root = document.documentElement;
    function update() {
      var max = Math.max(1, root.scrollHeight - innerHeight);
      root.style.setProperty('--scroll-progress', Math.min(pageYOffset / max, 1).toFixed(4));
    }
    update();
    addEventListener('scroll', update, { passive: true });
    addEventListener('resize', update);
  })();

  // Reveal-on-scroll: IntersectionObserver + a viewport pass + watchdog timers
  // so nothing is ever left hidden (e.g. if IO never fires).
  (function () {
    var reduce = matchMedia('(prefers-reduced-motion:reduce)').matches;
    var els = Array.prototype.slice.call(document.querySelectorAll('.reveal'));
    if (!els.length) return;
    var reveal = function (el) { el.classList.add('in'); };
    if (reduce) { els.forEach(reveal); return; }
    var visible = function (el) {
      var r = el.getBoundingClientRect();
      return r.top < innerHeight * 0.96 && r.bottom > 0;
    };
    var io;
    if ('IntersectionObserver' in window) {
      io = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          if (e.isIntersecting) { reveal(e.target); io.unobserve(e.target); }
        });
      }, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });
    }
    els.forEach(function (el, i) {
      el.style.transitionDelay = Math.min((i % 4) * 70, 210) + 'ms';
      if (visible(el)) reveal(el);
      else if (io) io.observe(el);
      else reveal(el);
    });
    setTimeout(function () {
      els.forEach(function (el) { if (!el.classList.contains('in') && visible(el)) reveal(el); });
    }, 900);
    setTimeout(function () { els.forEach(reveal); }, 2600);
  })();

  // Theme toggle (light / dark), persisted. The initial theme is already set
  // by the inline boot script in <head>; this only wires the button.
  (function () {
    var btn = document.getElementById('themeToggle');
    if (!btn) return;
    var root = document.documentElement;
    var sync = function () {
      btn.setAttribute('aria-pressed', root.getAttribute('data-theme') === 'dark');
    };
    sync();
    btn.addEventListener('click', function () {
      var dark = root.getAttribute('data-theme') === 'dark';
      if (dark) root.removeAttribute('data-theme'); else root.setAttribute('data-theme', 'dark');
      try { localStorage.setItem('theme', dark ? 'light' : 'dark'); } catch (e) {}
      sync();
    });
  })();

  // "Cite" buttons -> toggle the BibTeX block and copy it to the clipboard.
  // No-op on pages without .cite (e.g. the homepage, projects).
  Array.prototype.forEach.call(document.querySelectorAll('.cite'), function (btn) {
    var pub = btn.closest('.pub'); if (!pub) return;
    var bib = pub.querySelector('.bib'); if (!bib) return;
    btn.addEventListener('click', function () {
      var open = bib.classList.toggle('show');
      if (open && navigator.clipboard) {
        navigator.clipboard.writeText(bib.textContent).catch(function () {});
      }
    });
  });
})();
