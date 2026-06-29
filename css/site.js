/* Shared site behavior — loaded with `defer` on every page.
   Page-agnostic only: bespoke homepage JS (hero PR-card, language toggle,
   feed teaser) stays inline in index.html. The anti-FOUC theme boot stays
   inline in each page <head> because it must run before first paint. */
(function () {
  'use strict';

  // Scroll-progress bar (driven by the --scroll-progress custom property).
  // rAF-throttled so the layout read (scrollHeight) happens at most once per
  // frame instead of on every scroll event — keeps long pages smooth.
  (function () {
    var root = document.documentElement, ticking = false;
    function paint() {
      ticking = false;
      var max = Math.max(1, root.scrollHeight - innerHeight);
      root.style.setProperty('--scroll-progress', Math.min(pageYOffset / max, 1).toFixed(4));
    }
    function onScroll() {
      if (!ticking) { ticking = true; requestAnimationFrame(paint); }
    }
    paint();
    addEventListener('scroll', onScroll, { passive: true });
    addEventListener('resize', onScroll, { passive: true });
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

  // Global site search — a command-palette overlay injected on every page.
  // Indexes the auto-synced feeds (articles, talks) plus a small static
  // data/pages.json (publications, projects, key pages). Open with the nav
  // button, "/", or Cmd/Ctrl-K.
  (function () {
    var tools = document.querySelector('.nav-tools');
    if (!tools) return;
    var BASE = location.pathname.indexOf('/posts/') > -1 ? '../' : '';

    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'icon-btn';
    btn.id = 'siteSearchBtn';
    btn.setAttribute('aria-label', 'Search the site');
    btn.title = 'Search (press /)';
    btn.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3" stroke-linecap="round"/></svg>';
    tools.insertBefore(btn, tools.firstChild);

    var modal = document.createElement('div');
    modal.className = 'search-modal';
    modal.id = 'siteSearch';
    modal.hidden = true;
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    modal.setAttribute('aria-label', 'Search');
    modal.innerHTML =
      '<div class="search-backdrop" data-close></div>' +
      '<div class="search-panel">' +
        '<div class="search-bar">' +
          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3" stroke-linecap="round"/></svg>' +
          '<input id="searchInput" type="search" autocomplete="off" spellcheck="false" placeholder="Search articles, talks, papers, projects…" aria-label="Search query">' +
          '<kbd class="search-esc" data-close>Esc</kbd>' +
        '</div>' +
        '<div class="search-results" id="searchResults" role="listbox" aria-label="Search results"></div>' +
        '<div class="search-foot"><span><kbd>↑</kbd><kbd>↓</kbd> navigate</span><span><kbd>↵</kbd> open</span><span><kbd>esc</kbd> close</span></div>' +
      '</div>';
    document.body.appendChild(modal);

    var input = modal.querySelector('#searchInput');
    var results = modal.querySelector('#searchResults');
    var index = null, active = -1, hits = [], isOpen = false;

    function esc(s) { return (s || '').replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
    function resolve(u) { return /^https?:/i.test(u) ? u : BASE + u; }
    function fetchJSON(u) { return fetch(u).then(function (r) { return r.json(); }).catch(function () { return null; }); }

    function buildIndex() {
      if (index) return Promise.resolve(index);
      return Promise.all([
        fetchJSON(BASE + 'data/pages.json'),
        fetchJSON(BASE + 'data/articles.json'),
        fetchJSON(BASE + 'data/videos.json')
      ]).then(function (r) {
        var idx = [];
        ((r[0] && r[0].items) || []).forEach(function (p) {
          idx.push({ type: p.type || 'Page', title: p.title, snippet: p.snippet || '', tags: p.tags || [], url: resolve(p.url) });
        });
        ((r[1] && r[1].items) || []).forEach(function (a) {
          idx.push({ type: 'Article', title: a.title, snippet: a.snippet || '', tags: a.tags || [], url: resolve(a.local || a.url) });
        });
        ((r[2] && r[2].items) || []).forEach(function (v) {
          idx.push({ type: 'Talk', title: v.title, snippet: v.snippet || '', tags: v.tags || [], url: v.url });
        });
        index = idx;
        return idx;
      });
    }

    function query(q) {
      q = q.trim().toLowerCase();
      if (!q || !index) return [];
      var terms = q.split(/\s+/);
      var out = [];
      index.forEach(function (it) {
        var title = (it.title || '').toLowerCase();
        var tags = (it.tags || []).join(' ').toLowerCase();
        var snip = (it.snippet || '').toLowerCase();
        var hay = title + ' ' + tags + ' ' + snip;
        var score = 0, matched = 0;
        terms.forEach(function (t) {
          if (hay.indexOf(t) === -1) return;
          matched++;
          if (title.indexOf(t) === 0) score += 14;
          else if (title.indexOf(t) > -1) score += 10;
          if (tags.indexOf(t) > -1) score += 6;
          if (snip.indexOf(t) > -1) score += 2;
        });
        // OR semantics: keep anything matching at least one term, but reward
        // items that cover more of the query so full matches rank first.
        if (matched) out.push({ it: it, score: score + matched * 3 });
      });
      out.sort(function (a, b) { return b.score - a.score; });
      return out.slice(0, 12).map(function (o) { return o.it; });
    }

    function mark(text, terms) {
      var out = esc(text);
      terms.forEach(function (t) {
        if (!t) return;
        var re = new RegExp('(' + t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'ig');
        out = out.replace(re, '<mark>$1</mark>');
      });
      return out;
    }

    function render() {
      var q = input.value;
      hits = query(q);
      active = hits.length ? 0 : -1;
      if (!q.trim()) { results.innerHTML = '<div class="search-hint">Search articles, talks, papers, and projects.</div>'; return; }
      if (!hits.length) { results.innerHTML = '<div class="search-hint">No matches for “' + esc(q) + '”.</div>'; return; }
      var terms = q.trim().toLowerCase().split(/\s+/);
      results.innerHTML = hits.map(function (it, i) {
        var external = /^https?:/i.test(it.url);
        return '<a class="search-hit' + (i === active ? ' is-active' : '') + '" href="' + esc(it.url) + '" role="option"' +
          (external ? ' target="_blank" rel="noopener"' : '') + '>' +
          '<span class="hit-type t-' + esc((it.type || '').toLowerCase()) + '">' + esc(it.type || '') + '</span>' +
          '<span class="hit-main"><span class="hit-title">' + mark(it.title, terms) + '</span>' +
          (it.snippet ? '<span class="hit-snip">' + mark(it.snippet, terms) + '</span>' : '') +
          '</span></a>';
      }).join('');
    }

    function setActive(n) {
      var nodes = results.querySelectorAll('.search-hit');
      if (!nodes.length) return;
      active = (n + nodes.length) % nodes.length;
      Array.prototype.forEach.call(nodes, function (el, i) { el.classList.toggle('is-active', i === active); });
      nodes[active].scrollIntoView({ block: 'nearest' });
    }

    function openModal() {
      if (isOpen) return;
      isOpen = true;
      modal.hidden = false;
      document.documentElement.style.overflow = 'hidden';
      buildIndex().then(render);
      requestAnimationFrame(function () { modal.classList.add('show'); input.focus(); });
    }
    function closeModal() {
      if (!isOpen) return;
      isOpen = false;
      modal.classList.remove('show');
      document.documentElement.style.overflow = '';
      setTimeout(function () { modal.hidden = true; }, 160);
      btn.focus();
    }

    btn.addEventListener('click', openModal);
    modal.addEventListener('click', function (e) { if (e.target.closest('[data-close]')) closeModal(); });
    input.addEventListener('input', render);
    input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { e.preventDefault(); setActive(active + 1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(active - 1); }
      else if (e.key === 'Enter') {
        var node = results.querySelectorAll('.search-hit')[active];
        if (node) { e.preventDefault(); node.click(); }
      }
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && isOpen) { closeModal(); return; }
      var t = e.target, tag = t && t.tagName;
      var typing = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (t && t.isContentEditable);
      if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) { e.preventDefault(); isOpen ? closeModal() : openModal(); return; }
      if (!isOpen && !typing && e.key === '/' && !e.metaKey && !e.ctrlKey && !e.altKey) { e.preventDefault(); openModal(); }
    });
  })();

  // Article reading aids: copy-to-clipboard buttons on code blocks, and an
  // auto table of contents for long posts. No-ops where those elements absent.
  (function () {
    // --- copy buttons on code blocks (article prose + dataset snippets) ---
    Array.prototype.forEach.call(document.querySelectorAll('.prose pre, pre.code'), function (pre) {
      if (pre.querySelector('.copy-btn')) return;
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'copy-btn';
      btn.textContent = 'Copy';
      btn.setAttribute('aria-label', 'Copy code to clipboard');
      pre.appendChild(btn);
      btn.addEventListener('click', function () {
        var clone = pre.cloneNode(true);
        var b = clone.querySelector('.copy-btn'); if (b) b.remove();
        var code = (clone.textContent || '').replace(/\s+$/, '');
        var done = function () { btn.textContent = 'Copied'; setTimeout(function () { btn.textContent = 'Copy'; }, 1600); };
        if (navigator.clipboard) navigator.clipboard.writeText(code).then(done, done); else done();
      });
    });

    // --- table of contents for long articles ---
    var prose = document.querySelector('.prose');
    if (!prose) return;
    var heads = prose.querySelectorAll('h2, h3');
    if (heads.length < 3) return;
    var esc = function (s) { return (s || '').replace(/[&<>]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]; }); };
    var slug = function (s) { return (s || '').toLowerCase().replace(/[^\w\s-]/g, '').trim().replace(/\s+/g, '-').slice(0, 60) || 'section'; };
    var used = {}, items = [];
    Array.prototype.forEach.call(heads, function (h) {
      if (!h.id) {
        var base = slug(h.textContent), id = base, n = 2;
        while (used[id] || document.getElementById(id)) { id = base + '-' + n++; }
        h.id = id;
      }
      used[h.id] = true;
      items.push('<li class="toc-' + h.tagName.toLowerCase() + '"><a href="#' + h.id + '">' + esc(h.textContent) + '</a></li>');
    });
    var toc = document.createElement('details');
    toc.className = 'toc';
    toc.open = true;
    toc.innerHTML = '<summary>On this page</summary><ul>' + items.join('') + '</ul>';
    prose.parentNode.insertBefore(toc, prose);
  })();
})();
