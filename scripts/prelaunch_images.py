#!/usr/bin/env python3
"""Pre-launch pictures: one building picture per no-code row, linked, not copied.

  python3 scripts/prelaunch_images.py --report out.md   # test: lists what it would pick, writes nothing
  python3 scripts/prelaunch_images.py                   # the daily run (not switched on yet)

Her rules (5 Nov 2026):
  * credible sources only -- the developer's own website, or an established
    news site (NEWS_OUTLETS). Never agent sites, forums, portals or social media.
  * the whole building, not a logo.
  * stored as a link to the picture on the source site; nothing is copied.

Where a picture comes from, best first:
  0. her own picks in data/prelaunch_images_manual.csv -- a picture's own
     address, used as it is, or a page, whose preview picture is used. Her
     choice, so none of the rules below apply (5 Nov 2026: Aetas Taman Desa
     from wikiproperty.my, THE SHANG RESIDENCE's render);
  1. the project's official pages in data/prelaunch_pages.csv (kind
     "official" -- Ukay Spring's ukayspring.com.my, BRDB's coming-soon page);
  2. finds in data/prelaunch_finds.csv (not dismissed, not weak) whose page is
     on a developer website in prelaunch_sources.csv -- not its front page,
     whose picture is the company's, not the project's;
  3. finds that are news stories from one of NEWS_OUTLETS. A Google News link
     is first turned into the article's own address. The story must name the
     project in its headline or summary (the LBS awards story found for
     Sherwood did not), and a headline about an event -- an award, an opening
     ceremony -- is skipped: its picture is people, not the building.

The picture is the page's own preview picture (og:image / twitter:image) --
the one the site chose to show when the page is shared. It is kept only if:
  * its address and description carry none of LOGO_WORDS (logo, icon, ...)
    and none of EVENT_WORDS (ceremony, opening, award, ... -- The Eclipse's
    "grandopeningceremony" picture, 5 Nov 2026);
  * it is a photo format (not .svg / .gif / .ico);
  * it is at least MIN_WIDTH pixels wide, read from the page's tags or from
    the first bytes of the picture itself;
  * it is not square-ish (SQUARE_LO..SQUARE_HI), the usual logo shape;
  * the same picture is not offered for two different rows (a site-wide default).
What the rules cannot catch -- a news photo of people at a launch -- is what
the "Wrong picture? Remove" link on the site is for: a file in
data/prelaunch_images_removed/ named by the picture's id. Removed pictures
are never offered again.

data/prelaunch_images.csv keeps every page looked at, kept or not, with the
reason, so a page is read once. Like the rest of the pre-launch watch it
never writes projects.csv. One request at a time, a pause between each,
nothing retried, a time budget.
"""
import argparse, csv, hashlib, json, os, re, struct, sys, time
import html as htmlmod
import urllib.error, urllib.parse, urllib.request
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from watch_prelaunch import read, clean_url, simple, has, UA, PAUSE, TIMEOUT  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECTS = os.path.join(ROOT, "projects.csv")
SOURCES = os.path.join(ROOT, "prelaunch_sources.csv")
FINDS = os.path.join(ROOT, "data", "prelaunch_finds.csv")
PAGES = os.path.join(ROOT, "data", "prelaunch_pages.csv")
MANUAL = os.path.join(ROOT, "data", "prelaunch_images_manual.csv")   # her own picks, which always win
IMAGES = os.path.join(ROOT, "data", "prelaunch_images.csv")
REMOVED = os.path.join(ROOT, "data", "prelaunch_images_removed")
FIELDS = ["tracker", "project", "page", "source", "kind", "image", "width", "height",
          "status", "reason", "checked"]

BUDGET = 300            # seconds
MIN_WIDTH = 600
SQUARE_LO, SQUARE_HI = 0.85, 1.18
# Established news outlets, as Google News names them in the finds' source column.
NEWS_OUTLETS = ["edgeprop", "the edge malaysia", "the edge markets", "the star", "starproperty",
                "nst online", "new straits times", "malay mail", "bernama", "the malaysian reserve",
                "free malaysia today", "the sun"]
NEWS_HOSTS = ["edgeprop.my", "theedgemalaysia.com", "thestar.com.my", "starproperty.my", "nst.com.my",
              "malaymail.com", "bernama.com", "themalaysianreserve.com", "freemalaysiatoday.com",
              "thesun.my"]
# Whole words in a picture's address or description. Not "brand": EdgeProp's
# Selayang Mulia render was turned down for it on the first test run.
LOGO_WORDS = ["logo", "icon", "favicon", "avatar", "profile", "placeholder", "default", "sprite",
              "qr", "whatsapp", "badge", "author", "columnist", "headshot"]
# Anywhere in a picture's address or description, run-together names included
# ("theeclipsegrandopeningceremonythumb"): the picture is an event, not a building.
EVENT_WORDS = ["ceremony", "opening", "award", "signing", "groundbreaking", "ground-breaking",
               "handover", "gala", "launchingevent", "prize"]
# Whole words in a news headline that make the story an event, not the project.
EVENT_HEADLINE = ["award", "awards", "recognised", "recognized", "ceremony", "opening ceremony",
                  "signing", "mou", "groundbreaking", "ground-breaking", "handover", "gala", "accolade"]


def image_id(url):
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def removed_ids():
    if not os.path.isdir(REMOVED):
        return set()
    return {f for f in os.listdir(REMOVED) if not f.startswith(".")}


def host_of(url):
    h = urllib.parse.urlsplit(url).netloc.lower()
    return h[4:] if h.startswith("www.") else h


# ---------------------------------------------------------------- fetching

class Net:
    def __init__(self, budget):
        self.start, self.budget, self.asked, self.errors = time.time(), budget, 0, []

    def _open(self, req, label, limit):
        if time.time() - self.start > self.budget:
            self.errors.append(f"{label}: skipped (time budget)")
            return None, None
        time.sleep(PAUSE)
        self.asked += 1
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return r.read(limit), r
        except (urllib.error.URLError, OSError, ValueError) as e:
            self.errors.append(f"{label}: {getattr(e, 'code', '') or type(e).__name__}")
            return None, None

    def page(self, url, label):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-MY,en;q=0.8"})
        raw, r = self._open(req, label, 3_000_000)
        if raw is None:
            return None, url
        return raw.decode(r.headers.get_content_charset() or "utf-8", "replace"), r.geturl()

    def head_bytes(self, url, label):
        """The first 64 KB of a picture: enough for its width and height."""
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": "bytes=0-65535"})
        raw, _ = self._open(req, label, 65536)
        return raw

    def post(self, url, body, label):
        req = urllib.request.Request(url, data=body.encode("utf-8"), headers={
            "User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
        raw, _ = self._open(req, label, 1_000_000)
        return raw.decode("utf-8", "replace") if raw else None


def gnews_target(net, url):
    """A news.google.com/rss/articles/... link -> the article's own address.
    Google hides it behind a page that redirects in the browser, so this asks
    the same endpoint that page asks. None if Google does not say."""
    m = re.search(r"news\.google\.com/(?:rss/)?articles/([^?/#]+)", url)
    if not m:
        return url
    aid = m.group(1)
    page, _ = net.page(f"https://news.google.com/articles/{aid}", "Google News link")
    if not page:
        return None
    sg = re.search(r'data-n-a-sg="([^"]+)"', page)
    ts = re.search(r'data-n-a-ts="([^"]+)"', page)
    if not (sg and ts):
        return None
    inner = json.dumps(["garturlreq", [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None,
                                        None, None, None, 0, 1], "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
                        aid, int(ts.group(1)), sg.group(1)])
    body = "f.req=" + urllib.parse.quote(json.dumps([[["Fbv4je", inner, None, "generic"]]]))
    out = net.post("https://news.google.com/_/DotsSplashUi/data/batchexecute", body, "Google News decode")
    if not out:
        return None
    try:
        part = out.split("\n\n", 1)[1]
        return json.loads(json.loads(part)[0][2])[1]
    except (IndexError, ValueError, TypeError):
        return None


# ---------------------------------------------------------------- the picture

def meta_tags(html):
    """{property/name: [content, ...]} for the page's meta tags."""
    out = {}
    for tag in re.findall(r"(?is)<meta\b[^>]*>", html):
        k = re.search(r"""(?i)(?:property|name)\s*=\s*["']([^"']+)["']""", tag)
        v = re.search(r"""(?is)content\s*=\s*(["'])(.*?)\1""", tag)
        if k and v:
            out.setdefault(k.group(1).lower(), []).append(htmlmod.unescape(v.group(2)).strip())
    return out


def size_of(b):
    """(width, height) from the first bytes of a JPEG, PNG, WebP or GIF; None if unknown."""
    if not b:
        return None
    if b[:8] == b"\x89PNG\r\n\x1a\n" and len(b) >= 24:
        return struct.unpack(">II", b[16:24])
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return struct.unpack("<HH", b[6:10])
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        c = b[12:16]
        if c == b"VP8X" and len(b) >= 30:
            return 1 + int.from_bytes(b[24:27], "little"), 1 + int.from_bytes(b[27:30], "little")
        if c == b"VP8 " and len(b) >= 30:
            w, h = struct.unpack("<HH", b[26:30])
            return w & 0x3FFF, h & 0x3FFF
        if c == b"VP8L" and len(b) >= 25:
            v = int.from_bytes(b[21:25], "little")
            return (v & 0x3FFF) + 1, ((v >> 14) & 0x3FFF) + 1
    if b[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(b):
            if b[i] != 0xFF:
                i += 1
                continue
            marker = b[i + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            seg = struct.unpack(">H", b[i + 2:i + 4])[0]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack(">HH", b[i + 5:i + 9])
                return w, h
            i += 2 + seg
    return None


def headline_of(html):
    tags = meta_tags(html)
    title = (tags.get("og:title") or tags.get("twitter:title") or [""])[0]
    if not title:
        m = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
        title = htmlmod.unescape(re.sub(r"\s+", " ", m.group(1))).strip() if m else ""
    desc = " ".join(tags.get("og:description", []) + tags.get("description", []))
    return title, desc


def news_reason(html, project):
    """Why a news story's picture cannot be the project's, or ''."""
    title, desc = headline_of(html)
    low = title.lower()
    ev = next((w for w in EVENT_HEADLINE if has(low, w)), None)
    if ev:
        return f"headline is about an event ('{ev}'): {title[:90]}"
    name = simple(project).lower()
    if name and not has((title + " " + desc).lower(), name):
        return f"story does not name {simple(project)}: {title[:90]}"
    return ""


def judge(net, html, page_url):
    """(image, width, height, '') for an acceptable picture, or ('', 0, 0, reason)."""
    tags = meta_tags(html)
    cands = []
    for k in ("og:image:secure_url", "og:image", "og:image:url", "twitter:image", "twitter:image:src"):
        for v in tags.get(k, []):
            u = urllib.parse.urljoin(page_url, v)
            if u.startswith(("http://", "https://")) and u not in cands:
                cands.append(u)
    if not cands:
        return "", 0, 0, "page has no preview picture"
    alt = " ".join(tags.get("og:image:alt", []) + tags.get("twitter:image:alt", [])).lower()
    why = []
    for u in cands:
        low = urllib.parse.unquote(u).lower()
        word = next((w for w in LOGO_WORDS if re.search(r"(?<![a-z])" + w + r"(?![a-z])", low)
                     or re.search(r"(?<![a-z])" + w + r"(?![a-z])", alt)), None)
        if word:
            why.append(f"'{word}' in its name")
            continue
        ev = next((w for w in EVENT_WORDS if w in low or w in alt), None)
        if ev:
            why.append(f"an event picture ('{ev}' in its name)")
            continue
        if re.search(r"\.(svg|gif|ico)(?:$|\?)", low):
            why.append("not a photo format")
            continue
        w = h = 0
        try:
            w = int((tags.get("og:image:width") or ["0"])[0])
            h = int((tags.get("og:image:height") or ["0"])[0])
        except ValueError:
            pass
        if not (w and h):
            wh = size_of(net.head_bytes(u, "picture size"))
            if not wh:
                why.append("size unknown")
                continue
            w, h = wh
        if w < MIN_WIDTH:
            why.append(f"too small ({w}x{h})")
            continue
        if SQUARE_LO <= w / max(h, 1) <= SQUARE_HI:
            why.append(f"square, logo-shaped ({w}x{h})")
            continue
        return u, w, h, ""
    return "", 0, 0, "; ".join(why)


# ---------------------------------------------------------------- which pages

def candidates():
    """(row key, find) for each find a picture may come from, best first."""
    projects = read(PROJECTS)
    nocode = {(p["tracker"].strip(), p["project"].strip()) for p in projects if not (p.get("code") or "").strip()}
    dev_hosts = {host_of(s["url"]) for s in read(SOURCES) if s.get("kind") == "developer"}
    out = []
    for pg in read(PAGES):
        key = ((pg.get("tracker") or "").strip(), (pg.get("project") or "").strip())
        if key in nocode and (pg.get("kind") or "").strip() == "official" and pg.get("url"):
            f = {"url": pg["url"], "source": "official site " + (pg.get("label") or host_of(pg["url"])),
                 "seen": pg.get("first_seen") or "", "confidence": "strong"}
            out.append(((-1, 0), f["seen"], key, "official", f))
    for f in read(FINDS):
        key = ((f.get("tracker") or "").strip(), (f.get("project") or "").strip())
        url = (f.get("url") or "").strip()
        if key not in nocode or not url or (f.get("status") or "").strip() == "dismissed" \
                or (f.get("confidence") or "") == "weak":
            continue
        h = host_of(url)
        path = urllib.parse.urlsplit(url).path.strip("/")
        if h in dev_hosts:
            if not path:
                continue                    # front page: the company's picture, not the project's
            kind = "developer"
        elif "news.google.com" in h:
            src = (f.get("source") or "").lower()
            if not any(o == src or src.startswith(o) for o in NEWS_OUTLETS):
                continue
            kind = "news"
        elif any(h == n or h.endswith("." + n) for n in NEWS_HOSTS):
            kind = "news"
        else:
            continue                        # agent sites, portals, social media, forums
        rank = (0 if kind == "developer" else 1, 0 if f.get("confidence") == "strong" else 1)
        out.append((rank, f.get("seen") or "", key, kind, f))
    out.sort(key=lambda x: x[1], reverse=True)    # newest find first ...
    out.sort(key=lambda x: x[0])                   # ... within developer, then news; strong first
    return [(key, kind, f) for _, _, key, kind, f in out]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", metavar="FILE", help="test: list what would be picked, write nothing")
    ap.add_argument("--budget", type=int, default=BUDGET)
    args = ap.parse_args()
    report = bool(args.report)
    today = date.today().isoformat()

    old = {} if report else {r["page"]: r for r in read(IMAGES)}
    gone = removed_ids()
    net = Net(args.budget)
    rows, used = [], {}
    for m in read(MANUAL):
        key = ((m.get("tracker") or "").strip(), (m.get("project") or "").strip())
        url = (m.get("url") or "").strip()
        if not url.startswith("https://"):
            continue
        r = {"tracker": key[0], "project": key[1], "page": url, "source": "your pick",
             "kind": "her pick", "image": "", "width": "", "height": "", "status": "rejected",
             "reason": "", "checked": today}
        # The picture itself: its address ends in a picture type, or it is a
        # site's resizing link (ivygohproperty.com's /_next/image?url=...jpg).
        if re.search(r"\.(jpe?g|png|webp|avif)(?:$|\?)", urllib.parse.urlsplit(url).path.lower() + "?") \
                or re.search(r"/_next/image\?|\.(jpe?g|png|webp|avif)(?:&|$)", url.lower()):
            r.update(image=url, status="ok")
        else:
            html, final = net.page(url, "her pick")
            pics = [urllib.parse.urljoin(final, v) for k in ("og:image:secure_url", "og:image", "twitter:image")
                    for v in (meta_tags(html).get(k, []) if html else [])]
            # A site that fills its pictures in later (wikiproperty.my) shows a
            # plain fetch only its placeholder: that is no picture at all.
            pics = [u for u in pics if not re.search(r"placeholder|\.svg(?:$|\?)", u.lower())]
            if pics:
                r.update(image=pics[0], status="ok", source="your pick (" + host_of(final) + ")")
            elif html is not None:
                r["reason"] = "page shows only a placeholder: copy the picture's own address instead"
            else:
                r["reason"] = "page did not load" if html is None else "page has no preview picture"
        if r["image"] and image_id(r["image"]) in gone:
            r.update(image="", status="rejected", reason="removed by her")
        old.pop(url, None)
        rows.append(r)
    for key, kind, f in candidates():
        page_url = clean_url(f["url"])
        if page_url in old:
            rows.append(old.pop(page_url))
            continue
        r = {"tracker": key[0], "project": key[1], "page": page_url, "source": f.get("source", ""),
             "kind": kind, "image": "", "width": "", "height": "", "status": "rejected", "reason": "",
             "checked": today}
        target = gnews_target(net, page_url) if kind == "news" else page_url
        if not target:
            r["reason"] = "Google News did not give the article address"
            rows.append(r)
            continue
        if kind == "news" and not any(host_of(target) == n or host_of(target).endswith("." + n) for n in NEWS_HOSTS):
            r["reason"] = f"article is on {host_of(target)}, not an established news site"
            rows.append(r)
            continue
        html, final = net.page(target, f"{kind} page")
        if html is None:
            r["reason"] = "page did not load"
            rows.append(r)
            continue
        why = news_reason(html, key[1]) if kind == "news" else ""
        img, w, h = "", 0, 0
        if not why:
            img, w, h, why = judge(net, html, final)
        r["source"] = r["source"] + (f" ({host_of(final)})" if kind == "news" else "")
        if img and image_id(img) in gone:
            img, why = "", "removed by her"
        if img:
            r.update(image=img, width=str(w), height=str(h), status="ok")
        else:
            r["reason"] = why
        rows.append(r)
    rows += list(old.values())          # finds since dismissed: keep the record

    # A picture offered for two different rows is a site-wide default, not either project.
    owners = {}
    for r in rows:
        if r["status"] == "ok":
            owners.setdefault(r["image"], set()).add((r["tracker"], r["project"]))
    for r in rows:
        if r["status"] == "ok" and r["kind"] != "her pick" and len(owners[r["image"]]) > 1:
            r.update(status="rejected", reason="same picture used for several projects")

    chosen = {}
    for r in rows:
        k = (r["tracker"], r["project"])
        if r["status"] == "ok" and k not in chosen:
            chosen[k] = r

    if report:
        lines = [f"# Pre-launch pictures -- test run ({today})", "",
                 "Nothing was written. Each project shows the picture that would go on its card, "
                 "then every page that was looked at and why it was or was not used.", "",
                 f"Requests: {net.asked}. Pages looked at: {len(rows)}. Projects with a picture: {len(chosen)}.", ""]
        for k in sorted({(r["tracker"], r["project"]) for r in rows}, key=lambda x: x[1].lower()):
            lines.append(f"## {k[1]}  ({k[0]})")
            c = chosen.get(k)
            if c:
                lines += ["", f"<img src=\"{c['image']}\" width=\"360\">", "",
                          f"From {c['source']} -- {c['width']}x{c['height']} -- [page]({c['page']})", ""]
            else:
                lines += ["", "No picture.", ""]
            for r in rows:
                if (r["tracker"], r["project"]) == k:
                    verdict = "USED" if r is c else ("ok (not first)" if r["status"] == "ok" else r["reason"])
                    lines.append(f"- {r['kind']}, {r['source']}: {verdict} -- [page]({r['page']})"
                                 + (f" -- [picture]({r['image']})" if r["image"] else ""))
            lines.append("")
        lines += ["## Problems", ""] + [f"- {e}" for e in net.errors] + [""]
        with open(args.report, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        print(f"report: {len(chosen)} projects with a picture from {len(rows)} pages; "
              f"{len(net.errors)} problems -> {args.report}")
        return

    with open(IMAGES, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"{len(chosen)} projects with a picture from {len(rows)} pages; {len(net.errors)} problems")
    for e in net.errors:
        print("  " + e)


if __name__ == "__main__":
    sys.exit(main())
