#!/usr/bin/env python3
"""Fetch Medium articles and YouTube videos into data/*.json.

Stdlib-only so it runs unchanged in CI and locally. Used by the
sync-feeds GitHub Action (scheduled) and can be run by hand to seed data.
"""
import json
import re
import sys
import html
import datetime
import urllib.request
from pathlib import Path
from xml.etree import ElementTree as ET

MEDIUM_USER = "mabujadallah"
YT_HANDLE = "mahmoudabujadallah"

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
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


def fetch_medium():
    url = f"https://medium.com/feed/@{MEDIUM_USER}"
    root = ET.fromstring(get(url))
    ns = {"content": "http://purl.org/rss/1.0/modules/content/"}
    items = []
    for it in root.findall("./channel/item")[:MAX_ITEMS]:
        body = (it.findtext("content:encoded", default="", namespaces=ns)
                or it.findtext("description", default=""))
        img = re.search(r'<img[^>]+src="([^"]+)"', body or "")
        items.append({
            "title": (it.findtext("title") or "").strip(),
            "url": (it.findtext("link") or "").strip(),
            "date": iso(it.findtext("pubDate")),
            "snippet": strip_html(body),
            "tags": [c.text for c in it.findall("category") if c.text][:3],
            "image": img.group(1) if img else "",
        })
    return {"source": f"https://medium.com/@{MEDIUM_USER}", "items": items}


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
            "channelId": cid, "items": items}


def write(name, payload):
    payload["updated"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    DATA.mkdir(exist_ok=True)
    (DATA / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    print(f"wrote {name}: {len(payload.get('items', []))} items")


def main():
    failures = 0
    for name, fn in (("articles.json", fetch_medium), ("videos.json", fetch_youtube)):
        try:
            write(name, fn())
        except Exception as exc:  # keep last good data on transient failures
            failures += 1
            print(f"WARN {name}: {exc}", file=sys.stderr)
    return 1 if failures == 2 else 0


if __name__ == "__main__":
    sys.exit(main())
