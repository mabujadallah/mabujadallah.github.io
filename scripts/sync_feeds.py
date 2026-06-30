#!/usr/bin/env python3
"""Sync Medium articles and YouTube videos into the site.

For Medium this now mirrors the *full* article onto the site:
  * data/posts.json     cumulative source of truth (full HTML kept forever,
                        so the archive never shrinks when a post ages out of
                        Medium's ~10-item RSS window)
  * data/articles.json  lean card index that media.html renders
  * posts/<slug>.html   a styled, standalone page per article (re-rendered
                        every run, so template tweaks propagate to all posts)
  * sitemap.xml         post URLs injected for discoverability

For YouTube it still writes data/videos.json (cards only).

Stdlib-only so it runs unchanged in CI and locally. Used by the sync-feeds
GitHub Action (daily, 06:00 UTC) and can be run by hand at any time.
"""
import json
import re
import sys
import html
import datetime
import urllib.parse
import urllib.request
from pathlib import Path
from string import Template
from xml.etree import ElementTree as ET

MEDIUM_USER = "mabujadallah"
YT_HANDLE = "mahmoudabujadallah"
BASE_URL = "https://mabujadallah.github.io"
AUTHOR = "Mahmoud S. Y. Abujadallah"

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
POSTS = ROOT / "posts"
UA = "Mozilla/5.0 (compatible; portfolio-feed-sync/1.0)"
MAX_ITEMS = 12


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def strip_html(s, limit=180):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return (s[:limit].rstrip() + "…") if len(s) > limit else s


def esc(s, quote=False):
    """Escape a string for safe placement in HTML text (or an attribute)."""
    s = (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if quote:
        s = s.replace('"', "&quot;")
    return s


def iso(value):
    """Normalise a few common feed date formats to YYYY-MM-DD."""
    if not value:
        return ""
    value = value.strip()
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z",
                "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S+00:00"):
        try:
            return datetime.datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return value[:10]


def pretty_date(d):
    try:
        return datetime.datetime.strptime(d, "%Y-%m-%d").strftime("%B %-d, %Y")
    except ValueError:
        try:  # Windows strftime has no %-d
            return datetime.datetime.strptime(d, "%Y-%m-%d").strftime("%B %d, %Y").replace(" 0", " ")
        except ValueError:
            return d


def slugify(url, title):
    """Stable, readable slug from a Medium URL (drops the trailing hash id)."""
    path = urllib.parse.urlsplit(url).path
    last = path.rstrip("/").split("/")[-1]
    last = re.sub(r"-[0-9a-f]{6,}$", "", last)          # strip Medium's hash id
    last = re.sub(r"[^a-z0-9-]+", "-", last.lower()).strip("-")
    if not last:
        last = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return last or "post"


def reading_time(content_html):
    words = len(strip_html(content_html, 10 ** 9).split())
    return max(1, round(words / 220))


# --------------------------------------------------------------------------- #
#  Medium
# --------------------------------------------------------------------------- #
def fetch_medium():
    url = f"https://medium.com/feed/@{MEDIUM_USER}"
    root = ET.fromstring(get(url))
    ns = {"content": "http://purl.org/rss/1.0/modules/content/"}
    items = []
    for it in root.findall("./channel/item")[:MAX_ITEMS]:
        body = (it.findtext("content:encoded", default="", namespaces=ns)
                or it.findtext("description", default=""))
        img = re.search(r'<img[^>]+src="([^"]+)"', body or "")
        link = (it.findtext("link") or "").strip().split("?")[0]
        title = (it.findtext("title") or "").strip()
        items.append({
            "slug": slugify(link, title),
            "title": title,
            "url": link,
            "date": iso(it.findtext("pubDate")),
            "snippet": strip_html(body),
            "tags": [c.text for c in it.findall("category") if c.text][:3],
            "image": img.group(1) if img else "",
            "content": (body or "").strip(),
        })
    return items


def merge_posts(existing, fresh):
    """Cumulative merge keyed by slug; newest content wins, archive is kept."""
    by_slug = {p["slug"]: p for p in existing}
    for p in fresh:
        by_slug[p["slug"]] = p          # refresh existing / add new
    merged = list(by_slug.values())
    merged.sort(key=lambda p: (p.get("date", ""), p.get("slug", "")), reverse=True)
    return merged


# --------------------------------------------------------------------------- #
#  Static post pages
# --------------------------------------------------------------------------- #
PAGE = Template("""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>$title_text — $author</title>
<meta name="description" content="$desc">
<meta name="author" content="$author">
<meta name="robots" content="index, follow">
<meta name="theme-color" content="#0969DA">
<link rel="canonical" href="$canonical">
<link rel="icon" type="image/svg+xml" href="../favicon.svg">
<link rel="alternate" type="application/rss+xml" title="$author — Writing" href="/feed.xml">
<meta property="og:type" content="article">
<meta property="article:author" content="$author">
<meta property="article:published_time" content="$date">
<meta property="og:title" content="$title_text">
<meta property="og:description" content="$desc">
<meta property="og:url" content="$page_url">
<meta property="og:image" content="$image">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="$title_text">
<meta name="twitter:description" content="$desc">
<meta name="twitter:image" content="$image">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@400;450;500;600&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="../css/site.css">
<script>
  document.documentElement.classList.add('js');
  (function(){try{
    var t=localStorage.getItem('theme')||(matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light');
    if(t==='dark')document.documentElement.setAttribute('data-theme','dark');
  }catch(e){}})();
</script>
</head>
<body>
<div class="scroll-progress" aria-hidden="true"></div>
<a class="skip" href="#main">Skip to content</a>

<header class="nav">
  <div class="wrap nav-inner">
    <a class="brand" href="../index.html"><span class="mono-badge">MA</span><span>Mahmoud&nbsp;Abujadallah</span></a>
    <nav class="nav-links" aria-label="Primary">
      <a href="../index.html#research">Research</a>
      <a href="../publications.html">Publications</a>
      <a href="../datasets.html">Data</a>
      <a href="../projects.html">Projects</a>
      <a href="../media.html" aria-current="page">Writing &amp; Talks</a>
      <a href="../index.html#about">About</a>
    </nav>
    <div class="nav-tools">
      <button class="icon-btn" id="themeToggle" type="button" aria-label="Toggle dark mode" title="Toggle theme">
        <svg class="ic-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M21 12.8A8.5 8.5 0 1 1 11.2 3a6.6 6.6 0 0 0 9.8 9.8z" stroke-linecap="round" stroke-linejoin="round"/></svg>
        <svg class="ic-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" stroke-linecap="round"/></svg>
      </button>
    </div>
  </div>
</header>

<main id="main">
  <div class="wrap $layout_class">
    <article class="article-main">
      <div class="article-head">
        <a class="back" href="../media.html">← Writing &amp; Talks</a>
        <h1>$title_text</h1>
        <div class="article-meta">
          <span>$pretty_date</span>
          <span>$reading min read</span>
          <a href="$canonical" target="_blank" rel="noopener">Originally on Medium ↗</a>
        </div>
      </div>
      <div class="prose">
$body_html
      </div>
      <div class="article-foot">
        <a class="read-on-medium" href="$canonical" target="_blank" rel="noopener">Read &amp; clap on Medium ↗</a>
        <a class="back" href="../media.html">← All writing &amp; talks</a>
      </div>
    </article>
$rail_html
  </div>
</main>

<footer>
  <div class="wrap foot-inner">
    <span>© $year $author</span>
    <span>ÉTS Montréal · Gaza, Palestine</span>
  </div>
</footer>
<script src="../css/site.js" defer></script>
</body>
</html>
""")


def lazyload_images(content):
    """Defer offscreen images so the page paints sooner (less scroll lag)."""
    return re.sub(r"<img(?![^>]*\bloading=)",
                  '<img loading="lazy" decoding="async"', content or "")


def render_rail(all_posts, current_slug, limit=6):
    """Right-hand 'More writing' list of the other posts."""
    others = [p for p in all_posts if p["slug"] != current_slug][:limit]
    if not others:
        return "", "article-layout solo"
    items = "\n".join(
        f'          <li><a href="{p["slug"]}.html">'
        f'<span class="rail-title">{esc(p["title"])}</span>'
        f'<span class="rail-date">{esc(pretty_date(p["date"]))}</span></a></li>'
        for p in others)
    rail = ('    <aside class="article-rail" aria-label="More writing">\n'
            '      <div class="rail-sticky">\n'
            '        <span class="rail-label">More writing</span>\n'
            '        <ul class="rail-list">\n'
            f'{items}\n'
            '        </ul>\n'
            '        <a class="rail-all" href="../media.html">All writing &amp; talks →</a>\n'
            '      </div>\n'
            '    </aside>')
    return rail, "article-layout"


def render_post(item, all_posts):
    rail_html, layout_class = render_rail(all_posts, item["slug"])
    return PAGE.substitute(
        title_text=esc(item["title"]),
        author=esc(AUTHOR),
        desc=esc(item.get("snippet", ""), quote=True),
        canonical=esc(item["url"], quote=True),
        page_url=f"{BASE_URL}/posts/{item['slug']}.html",
        image=esc(item.get("image", ""), quote=True),
        date=esc(item.get("date", ""), quote=True),
        pretty_date=esc(pretty_date(item.get("date", ""))),
        reading=reading_time(item.get("content", "")),
        body_html=lazyload_images(item.get("content", "")),
        layout_class=layout_class,
        rail_html=rail_html,
        year=datetime.date.today().year,
    )


def write_posts(posts):
    POSTS.mkdir(exist_ok=True)
    for p in posts:
        (POSTS / f"{p['slug']}.html").write_text(render_post(p, posts), "utf-8")
    print(f"rendered {len(posts)} post page(s) in posts/")


def write_articles_index(posts):
    """Lean card index for media.html (no full content)."""
    items = [{
        "title": p["title"],
        "local": f"posts/{p['slug']}.html",
        "url": p["url"],
        "date": p["date"],
        "snippet": p["snippet"],
        "tags": p["tags"],
        "image": p["image"],
    } for p in posts]
    payload = {
        "source": f"https://medium.com/@{MEDIUM_USER}",
        "items": items,
        "updated": now_iso(),
    }
    (DATA / "articles.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    print(f"wrote articles.json: {len(items)} items")


def update_sitemap(posts):
    sm = ROOT / "sitemap.xml"
    if not sm.exists():
        return
    text = sm.read_text("utf-8")
    # Drop any previously-injected post URLs, then re-inject the current set.
    text = re.sub(r"\s*<url>\s*<loc>[^<]*/posts/[^<]*</loc>.*?</url>",
                  "", text, flags=re.S)
    block = "".join(
        f"\n  <url>\n    <loc>{BASE_URL}/posts/{p['slug']}.html</loc>\n"
        f"    <lastmod>{p['date']}</lastmod>\n"
        f"    <changefreq>monthly</changefreq>\n    <priority>0.6</priority>\n  </url>"
        for p in posts)
    text = text.replace("</urlset>", block + "\n</urlset>")
    sm.write_text(text, "utf-8")
    print(f"sitemap.xml: {len(posts)} post URL(s)")


# --------------------------------------------------------------------------- #
#  RSS feed + IndexNow (instant search-engine notification)
# --------------------------------------------------------------------------- #
INDEXNOW_KEY = "a7f3c1e94b6d2058f1c8e3a9d4b70e62"


def rfc822(date_str):
    """YYYY-MM-DD -> RFC-822 datetime (midnight UTC) for RSS pubDate."""
    try:
        d = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        d = datetime.datetime.now(datetime.timezone.utc)
    return d.replace(tzinfo=datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")


def write_feed(posts, limit=20):
    """RSS 2.0 feed of the latest posts, linking to the on-site article pages."""
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    items = []
    for p in posts[:limit]:
        link = f"{BASE_URL}/posts/{p['slug']}.html"
        cats = "".join(f"\n      <category>{esc(t)}</category>"
                       for t in (p.get("tags") or []))
        items.append(
            "    <item>\n"
            f"      <title>{esc(p.get('title', ''))}</title>\n"
            f"      <link>{link}</link>\n"
            f'      <guid isPermaLink="true">{link}</guid>\n'
            f"      <pubDate>{rfc822(p.get('date', ''))}</pubDate>\n"
            f"      <description>{esc(p.get('snippet', ''))}</description>"
            f"{cats}\n"
            "    </item>"
        )
    feed = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "  <channel>\n"
        f"    <title>{esc(AUTHOR)} — Writing</title>\n"
        f"    <link>{BASE_URL}/media.html</link>\n"
        f'    <atom:link href="{BASE_URL}/feed.xml" rel="self" type="application/rss+xml"/>\n'
        "    <description>Essays on AI for software engineering, AI coding agents, "
        "and large language models.</description>\n"
        "    <language>en</language>\n"
        f"    <lastBuildDate>{now}</lastBuildDate>\n"
        + "\n".join(items) + "\n"
        "  </channel>\n"
        "</rss>\n"
    )
    (ROOT / "feed.xml").write_text(feed, "utf-8")
    print(f"wrote feed.xml: {min(len(posts), limit)} item(s)")


def ensure_indexnow_key():
    """The IndexNow key must be fetchable as a text file at the site root."""
    key_file = ROOT / f"{INDEXNOW_KEY}.txt"
    if not key_file.exists():
        key_file.write_text(INDEXNOW_KEY, "utf-8")


def changed_post_urls(old_items, posts):
    """URLs of posts that are new or whose title/content changed since last run."""
    old = {p.get("slug"): p for p in old_items}
    urls = []
    for p in posts:
        prev = old.get(p["slug"])
        if (prev is None or prev.get("content") != p.get("content")
                or prev.get("title") != p.get("title")):
            urls.append(f"{BASE_URL}/posts/{p['slug']}.html")
    return urls


def ping_indexnow(urls):
    """Notify IndexNow (Bing, Yandex, …) that these URLs changed. Best-effort."""
    urls = [u for u in dict.fromkeys(urls) if u]   # de-dupe, drop blanks
    if not urls:
        print("indexnow: nothing to submit, skipping")
        return
    ensure_indexnow_key()
    payload = json.dumps({
        "host": urllib.parse.urlsplit(BASE_URL).netloc,
        "key": INDEXNOW_KEY,
        "keyLocation": f"{BASE_URL}/{INDEXNOW_KEY}.txt",
        "urlList": urls,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.indexnow.org/indexnow", data=payload, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        print(f"indexnow: submitted {len(urls)} url(s) -> HTTP {r.status}")


# --------------------------------------------------------------------------- #
#  YouTube (cards only, unchanged behaviour)
# --------------------------------------------------------------------------- #
def resolve_channel_id():
    page = get(f"https://www.youtube.com/@{YT_HANDLE}")
    m = (re.search(r'"channelId":"(UC[0-9A-Za-z_-]+)"', page)
         or re.search(r'youtube\.com/channel/(UC[0-9A-Za-z_-]+)', page))
    if not m:
        raise RuntimeError("could not resolve YouTube channel id from handle")
    return m.group(1)


def fetch_youtube():
    cid = resolve_channel_id()
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
    root = ET.fromstring(get(url))
    ns = {"a": "http://www.w3.org/2005/Atom",
          "yt": "http://www.youtube.com/xml/schemas/2015",
          "media": "http://search.yahoo.com/mrss/"}
    items = []
    for e in root.findall("a:entry", ns)[:MAX_ITEMS]:
        vid = e.findtext("yt:videoId", default="", namespaces=ns)
        group = e.find("media:group", ns)
        desc = group.findtext("media:description", default="", namespaces=ns) if group is not None else ""
        items.append({
            "title": (e.findtext("a:title", default="", namespaces=ns)).strip(),
            "url": f"https://www.youtube.com/watch?v={vid}",
            "id": vid,
            "date": iso(e.findtext("a:published", default="", namespaces=ns)),
            "thumb": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
            "snippet": strip_html(desc, 140),
        })
    return {"source": f"https://www.youtube.com/@{YT_HANDLE}",
            "channelId": cid, "items": items, "updated": now_iso()}


# --------------------------------------------------------------------------- #
def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(name, default):
    p = DATA / name
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text("utf-8"))
    except (ValueError, OSError):
        return default


def sync_medium():
    fresh = fetch_medium()
    store = load_json("posts.json", {"items": []})
    posts = merge_posts(store.get("items", []), fresh)
    DATA.mkdir(exist_ok=True)
    (DATA / "posts.json").write_text(
        json.dumps({"items": posts, "updated": now_iso()},
                   ensure_ascii=False, indent=2), "utf-8")
    write_posts(posts)
    write_articles_index(posts)
    update_sitemap(posts)
    write_feed(posts)
    ensure_indexnow_key()
    try:  # search-engine ping is best-effort; never fail the sync over it
        changed = changed_post_urls(store.get("items", []), posts)
        if changed:
            ping_indexnow([f"{BASE_URL}/media.html", f"{BASE_URL}/feed.xml"] + changed)
    except Exception as exc:
        print(f"WARN indexnow: {exc}", file=sys.stderr)
    print(f"medium: {len(fresh)} from feed, {len(posts)} total in archive")


def sync_youtube():
    payload = fetch_youtube()
    DATA.mkdir(exist_ok=True)
    (DATA / "videos.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    print(f"wrote videos.json: {len(payload.get('items', []))} items")


def main():
    failures = 0
    for label, fn in (("medium", sync_medium), ("youtube", sync_youtube)):
        try:
            fn()
        except Exception as exc:  # keep last good data on transient failures
            failures += 1
            print(f"WARN {label}: {exc}", file=sys.stderr)
    return 1 if failures == 2 else 0


if __name__ == "__main__":
    # `python sync_feeds.py indexnow <url> [<url> ...]` pings IndexNow only
    # (used by the push-triggered workflow for hand-edited pages). Best-effort.
    if len(sys.argv) > 1 and sys.argv[1] == "indexnow":
        try:
            ping_indexnow(sys.argv[2:])
        except Exception as exc:
            print(f"WARN indexnow: {exc}", file=sys.stderr)
        sys.exit(0)
    sys.exit(main())
