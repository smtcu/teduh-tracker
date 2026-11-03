#!/usr/bin/env python3
"""Pre-launch watch, phase 2: the daily GitHub sources.

  python3 scripts/watch_prelaunch.py                    # the daily run
  python3 scripts/watch_prelaunch.py --report out.md    # report only, writes nothing else

Reads a fixed list of free sources once a day, after the morning refresh:
Google News RSS (one search per no-code projects.csv row and one per area
word), the developer sites, sitemaps and Lowyat boards in
prelaunch_sources.csv (each developer's front page and up to three of its
project-list pages one level down), and the pages saved in data/prelaunch_pages.csv.
Anything new that names a no-code row, or that announces a launch in one of
her area words, becomes a line in data/prelaunch_finds.csv with status "new".

Each find carries the ticks agreed on 29 Oct 2026 as evidence for her to
judge -- name, place, developer, size, current (6 months), not resale -- and a
level: Strong = name + place + developer + current + not resale, Possible =
name + one more, Weak = name only. A launch in an area word that names no
tracked project is a "new in your area" check (blank project).

data/prelaunch_seen.json remembers every link already seen, and a saved
page's key facts (prices, dates, launch words). The first run, with no
memory file, is a silent baseline: it records what is already out there and
makes no finds, so day one is not hundreds of old items.

The news search looks back 30 days, except once per no-code row: the first
run that sees a row searches all its news, so a project unveiled long ago
(The Eclipse, Nov 2025) still turns up once. seen.json's "backfilled" list
records which rows have had that search.

data/prelaunch_teduh.csv ties a no-code row to TEDUH codes it hangs on but
does not track (8 Conlay's suspended 14159-1/-2): each run reads them, and a
changed name, permit, SPV, status or sold count is a find -- see teduh_watch().

It never writes projects.csv -- adding a project is always her Accept. One
request per source, a pause between each, nothing retried, and a time
budget: a slow or broken source is skipped for the day and caught tomorrow.
Social media, the Meta Ad Library and the sites that block GitHub stay on
the laptop runs (prelaunch_sources.csv rows marked "blocked", "browser only",
"laptop" or "untested" are skipped here).
"""
import argparse, csv, html as htmlmod, json, os, re, sys, time
import urllib.error, urllib.parse, urllib.request
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECTS = os.path.join(ROOT, "projects.csv")
SOURCES = os.path.join(ROOT, "prelaunch_sources.csv")
FINDS = os.path.join(ROOT, "data", "prelaunch_finds.csv")
PAGES = os.path.join(ROOT, "data", "prelaunch_pages.csv")
SEEN = os.path.join(ROOT, "data", "prelaunch_seen.json")
PLACES = os.path.join(ROOT, "data", "prelaunch_places.csv")
RUNS = os.path.join(ROOT, "data", "prelaunch_runs.csv")   # when each pre-launch check last ran
TEDUH_WATCH = os.path.join(ROOT, "data", "prelaunch_teduh.csv")   # TEDUH codes a no-code row hangs on
TEDUH_API = "https://teduh.kpkt.gov.my/api/projek-swasta/{}"
TEDUH_UNITS = "https://teduh.kpkt.gov.my/api/unit-projek-swasta/{}"
TEDUH_UA = "Mozilla/5.0 (compatible; teduh-tracker/1.0)"         # what fill_apdl.py sends
TEDUH_PAUSE = 1.1                                                  # scrape_teduh.py's pace
TEDUH_NEXT_MAX = 3      # new phases probed past the highest known, per developer code
NEWS_PER_ROW = 3        # one story is often carried by four outlets
FIELDS = ["seen", "tracker", "project", "source", "kind", "url", "stage", "event_date",
          "ad_since", "permit", "by", "ads", "price_from", "confidence", "status", "note"]

PAUSE = 1.0
TIMEOUT = 20
BUDGET = 540            # seconds; the workflow step's hard limit is 10 minutes
CURRENT_DAYS = 183      # "current" = within 6 months
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")   # what probe_sources.py tested with

# Her four areas and their 20 words (the same list as the laptop Run B).
AREA_WORDS = {
    "seputeh": ["Seputeh", "Old Klang Road", "Mid Valley", "Bangsar", "Damansara Heights", "Mont Kiara"],
    "status13": ["Cheras", "Cochrane", "Sri Petaling", "Salak Selatan", "Taman Desa"],
    "johor": ["Permas Jaya", "JBCC", "Senibong", "Tebrau"],
    "ukay": ["Ukay", "Ampang", "Melawati", "Ulu Kelang", "Kemensah"],
}
AREA_LOWER = {w.lower() for ws in AREA_WORDS.values() for w in ws}
LAUNCH_WORDS = ["new launch", "launching", "pre-launch", "prelaunch", "preview", "register interest",
                "register now", "sales gallery", "show unit", "showroom", "groundbreaking",
                "pelancaran", "projek baharu", "new project", "upcoming"]
RESALE_WORDS = ["for sale", "for rent", "subsale", "sub-sale", "auction", "lelong", "rental",
                "disewa", "to let", "below market value"]
# Furthest stage wins; the five names are STAGES in build_dashboard.py.
STAGE_WORDS = [
    ("Launched", ["now open for sale", "open for sale", "sold out", "fully sold", "now selling", "launched"]),
    ("Official launch", ["official launch", "grand launch", "launching ceremony", "pelancaran rasmi"]),
    ("Gallery opens", ["sales gallery", "show unit", "showroom", "gallery opening"]),
    ("Private viewing / VVIP", ["private preview", "private viewing", "priority viewing", "vvip", "vip preview"]),
    ("Register interest", ["register interest", "register your interest", "register now", "pre-register",
                           "daftar minat"]),
]
TRACKING = re.compile(r"^(utm_|gclid$|gbraid$|wbraid$|gad_source$|gad_campaignid$|fbclid$|mc_eid$|igsh$)")
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug",
                                      "sep", "oct", "nov", "dec"], 1)}


# ---------------------------------------------------------------- reading

def read(path):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def clean_url(url):
    """Drop tracking codes; store the address the way prelaunch_pages.csv does."""
    try:
        u = urllib.parse.urlsplit(url.strip())
    except ValueError:
        return url.strip()
    q = [(k, v) for k, v in urllib.parse.parse_qsl(u.query, keep_blank_values=True) if not TRACKING.match(k)]
    return urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, urllib.parse.urlencode(q), ""))


def simple(name):
    """Project name as a search phrase: '@ Place', '(alias)', '*' and stray symbols removed."""
    n = re.sub(r"\(.*?\)", " ", name.split("@")[0])
    n = re.sub(r"[^\w\s'&-]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def read_places():
    """data/prelaunch_places.csv: tracker,project,places (';'-separated) -- where a
    no-code row is, as a source stated it. projects.csv has no place column, and
    without one the Place tick (and so Strong) is out of reach for developer rows."""
    out = {}
    for r in read(PLACES):
        out[(r["tracker"].strip(), r["project"].strip().upper())] = \
            [w.strip() for w in (r.get("places") or "").split(";") if w.strip()]
    return out


def place_of(row, places):
    """Place words for the Place tick: what follows '@' in the name, the area
    words of an area tracker, and the row's line in prelaunch_places.csv."""
    words = []
    if "@" in row["project"]:
        words.append(re.sub(r"\(.*?\)|[*]", "", row["project"].split("@", 1)[1]).strip(" ,"))
    words += AREA_WORDS.get(row["tracker"], [])
    words += places.get((row["tracker"], row["project"].strip().upper()), [])
    return [w for w in words if len(w) >= 3]


def developer_words(row):
    """Words that identify the developer: its projects.csv name and the tracker's label."""
    words = []
    dev = re.sub(r"\(.*?\)|\b(sdn|bhd|berhad|s/b|group|property|properties|land|development)\b\.?", " ",
                 (row.get("developer") or ""), flags=re.I)
    dev = re.sub(r"[^\w\s]", " ", dev).strip()
    if len(dev) >= 3:
        words.append(dev)
    label = (row.get("tracker_label") or "").strip()
    if label and label.lower() not in ("seputeh hills", "klang valley", "johor", "ukay"):
        words.append(label)
    return words


def has(text, phrase):
    return re.search(r"(?<![\w])" + re.escape(phrase.lower()) + r"(?![\w])", text) is not None


def too_broad(key):
    """'The Eclipse', 'Permas', 'Damansara Heights': a name that alone matches
    unrelated stories (solar eclipses, area news). It is searched and counted
    only next to its developer -- the HAN-YA lesson in reverse."""
    core = re.sub(r"^the\s+", "", key)
    return key in AREA_LOWER or " " not in core or len(core) < 8


# ---------------------------------------------------------------- fetching

class Fetcher:
    def __init__(self, budget):
        self.start, self.budget = time.time(), budget
        self.errors, self.skipped, self.asked = [], [], 0

    def get(self, url, label):
        if time.time() - self.start > self.budget:
            self.skipped.append(label)
            return None
        time.sleep(PAUSE)
        self.asked += 1
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-MY,en;q=0.8"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                raw = r.read(3_000_000)
                cs = r.headers.get_content_charset() or "utf-8"
            return raw.decode(cs, "replace")
        except (urllib.error.URLError, OSError, ValueError) as e:
            self.errors.append(f"{label}: {getattr(e, 'code', '') or type(e).__name__} {getattr(e, 'reason', '')}".strip())
            return None

    def teduh(self, url, label):
        """(json, reached) from TEDUH. A 404 is an answer ("no such code"),
        not a failure, so it is not listed among the day's problems."""
        if time.time() - self.start > self.budget:
            self.skipped.append(label)
            return None, False
        time.sleep(TEDUH_PAUSE)
        self.asked += 1
        try:
            req = urllib.request.Request(url, headers={"User-Agent": TEDUH_UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode("utf-8")), True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None, True
            self.errors.append(f"{label}: {e.code}")
        except (urllib.error.URLError, OSError, ValueError) as e:
            self.errors.append(f"{label}: {type(e).__name__} {getattr(e, 'reason', '')}".strip())
        return None, False


def text_of(html):
    html = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", html)
    return re.sub(r"\s+", " ", htmlmod.unescape(re.sub(r"(?s)<[^>]+>", " ", html))).strip()


def summary_of(html):
    """The page's own description (meta description, og:description). Sites built
    by JavaScript, like eclipsejb.com, show nothing else to a plain fetch."""
    out = []
    for tag in re.findall(r"(?is)<meta\b[^>]*>", html):
        if re.search(r"""(?i)(?:name|property)\s*=\s*["'](?:description|og:description|twitter:description)["']""", tag):
            m = re.search(r"""(?is)content\s*=\s*(["'])(.*?)\1""", tag)
            if m:
                text = re.sub(r"\s+", " ", htmlmod.unescape(m.group(2))).strip()
                if text and text not in out:
                    out.append(text)
    return " ".join(out)


def links_of(html, base):
    """(absolute url, anchor text) for every link on the page."""
    out = []
    for href, inner in re.findall(r'(?is)<a\b[^>]*href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>', html):
        if href.startswith(("mailto:", "tel:", "javascript:", "whatsapp:")):
            continue
        out.append((urllib.parse.urljoin(base, htmlmod.unescape(href)), text_of(inner)))
    return out


# A developer's project list: the page its front page links to under one of
# these words (BRDB /property, Mah Sing /projects/, KSL /developments/). Read
# daily, one level down, so a project tile that is not on the front page --
# BRDB's damansara-heights-coming-soon -- is still seen. Added 3 Nov 2026.
LISTING_PATH = re.compile(r"/(?:propert(?:y|ies)|portfolio|projects?|developments?|our-developments|"
                          r"residential|new-launch(?:es)?|upcoming|townships?)/?$", re.I)
LISTING_MAX = 3         # listing pages followed per developer


def listing_pages(links, host):
    """The developer's own project-list pages among a front page's links:
    same website, address ending in a listing word, no ?filter copies
    (Chin Hin's ?category=Nature), at most LISTING_MAX, front page excluded."""
    out = []
    for link, _ in links:
        u = urllib.parse.urlsplit(link)
        if u.netloc != host or u.query or not LISTING_PATH.search(u.path):
            continue
        clean = urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, "", ""))
        if clean.rstrip("/") not in {x.rstrip("/") for x in out}:
            out.append(clean)
    return out[:LISTING_MAX]


def slug_words(url):
    """The last part of a link's address as words: .../damansara-heights-coming-soon
    -> 'damansara heights coming soon'. Project tiles are often a picture with no
    text, so the address is the only name the link carries."""
    last = urllib.parse.urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    last = re.sub(r"\.(?:html?|php|aspx?)$", "", last, flags=re.I)
    return re.sub(r"[-_+]+", " ", urllib.parse.unquote(last)).strip()


def rss_items(xml):
    items = []
    for block in re.findall(r"(?is)<item>(.*?)</item>", xml):
        def tag(t):
            m = re.search(rf"(?is)<{t}[^>]*>(.*?)</{t}>", block)
            return htmlmod.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", m.group(1))).strip() if m else ""
        when = None
        try:
            when = parsedate_to_datetime(tag("pubDate")).date()
        except (TypeError, ValueError):
            pass
        items.append({"title": text_of(tag("title")), "url": tag("link"), "date": when,
                      "text": text_of(tag("description")), "via": tag("source") or "Google News"})
    return items


def gnews(query, recent=True):
    q = urllib.parse.quote_plus(query + (" when:30d" if recent else ""))
    return f"https://news.google.com/rss/search?q={q}&hl=en-MY&gl=MY&ceid=MY:en"


# ---------------------------------------------------------------- judging

def stage_of(text):
    for stage, words in STAGE_WORDS:
        if any(has(text, w) for w in words):
            return stage
    return ""


def price_of(text):
    m = re.search(r"\bRM\s?\d[\d,.]*\s?(?:k|mil|million|juta)?\b", text, re.I)
    return m.group(0).strip() if m else ""


def event_of(text, today):
    """The first date in the text that is today or later: '5 Dec 2026', '5 December 2026'."""
    for d, mon, y in re.findall(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(20\d\d)\b", text):
        m = MONTHS.get(mon[:3].lower())
        if not m:
            continue
        try:
            when = date(int(y), m, int(d))
        except ValueError:
            continue
        if when >= today:
            return when.isoformat()
    return ""


def units_of(text):
    return [int(n.replace(",", "")) for n in re.findall(r"\b(\d[\d,]{1,5})\s+(?:units|unit|residences|homes)\b", text, re.I)]


def ticks_for(row, text, item, today, from_own_site, places):
    name = has(text, simple(row["project"]))
    pw = place_of(row, places)
    place = any(has(text, p) for p in pw) if pw else None     # None = no place known for this row
    dev = from_own_site or any(has(text, w) for w in developer_words(row))
    total = 0
    try:
        total = int(float(row.get("total_units") or 0))
    except ValueError:
        pass
    size = bool(total) and any(abs(n - total) <= total * 0.10 for n in units_of(text))
    current = item["date"] is None or (today - item["date"]).days <= CURRENT_DAYS
    not_resale = not any(has(text, w) for w in RESALE_WORDS)
    return {"name": name, "place": place, "developer": dev, "size": size,
            "current": current, "not resale": not_resale}


def level(t):
    if t["name"] and t["place"] and t["developer"] and t["current"] and t["not resale"]:
        return "strong"
    if t["name"] and (t["place"] or t["developer"] or t["size"]):
        return "possible"
    return "weak"


def tick_line(t):
    return "Ticks: " + " ".join(k + (" ?" if v is None else " yes" if v else " no") for k, v in t.items())


# ---------------------------------------------------------------- TEDUH status

def loose(d, *names):
    """First matching key of a dict, ignoring case and underscores: TEDUH
    mixes permitMula and permit_mula in the same payload."""
    if not isinstance(d, dict):
        return ""
    table = {re.sub(r"[^a-z0-9]", "", k.lower()): v for k, v in d.items()}
    for n in names:
        v = table.get(re.sub(r"[^a-z0-9]", "", n.lower()))
        if v not in (None, "", [], {}) and not isinstance(v, (dict, list)):
            return str(v).strip()
    return ""


def iso_date(v):
    """'2024-01-06', '2024-01-06T00:00:00' or '06 Jan 2024' -> '2024-01-06', else as given."""
    v = (v or "").strip()
    m = re.match(r"(\d{4}-\d\d-\d\d)", v)
    if m:
        return m.group(1)
    for fmt in ("%d %b %Y", "%d %B %Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(v, fmt).date().isoformat()
        except ValueError:
            pass
    return v


def teduh_status(fetch, code):
    """What TEDUH says about one code today, as a flat dict; None if the code
    does not exist; False if TEDUH could not be asked."""
    detail, reached = fetch.teduh(TEDUH_API.format(code), "TEDUH " + code)
    if not reached:
        return False
    if not isinstance(detail, dict):
        return None
    proj = detail.get("projek") if isinstance(detail.get("projek"), dict) else {}
    pem = detail.get("pemaju") if isinstance(detail.get("pemaju"), dict) else {}
    st = {"name": loose(proj, "nama") or loose(detail, "nama", "namaPemajuan"),
          "spv": loose(pem, "nama", "nama_pemaju"),
          "status": loose(detail, "status") or loose(proj, "status"),
          "permit_from": iso_date(loose(proj, "permitMula") or loose(detail, "permitMula")),
          "permit_to": iso_date(loose(proj, "permitTamat") or loose(detail, "permitTamat")),
          "permits": str(1 + len([r for r in detail.get("lesen_records") or [] if isinstance(r, dict)])),
          "units": loose(detail.get("unitSummary") or {}, "unit"),
          "sold": ""}
    units, reached = fetch.teduh(TEDUH_UNITS.format(code), "TEDUH units " + code)
    if reached and isinstance(units, dict):
        groups = [g for g in units.get("unitGroups") or [] if isinstance(g, dict)]
        alls = [u for g in groups for u in g.get("units") or [] if isinstance(u, dict)]
        if alls:
            st["sold"] = str(sum(1 for u in alls if u.get("status") == "sold"))
            st["units"] = st["units"] or str(len(alls))
    return st


STATUS_WORDS = {"name": "registered name", "spv": "SPV", "status": "TEDUH status",
                "permit_from": "permit start", "permit_to": "permit end",
                "permits": "permits on record", "units": "units", "sold": "sold"}


def permit_text(st, today):
    if not st.get("permit_to"):
        return "no permit shown" if not st.get("permit_from") else "from " + st["permit_from"]
    live = st["permit_to"] >= today.isoformat()
    return f"{st.get('permit_from') or '?'} to {st['permit_to']} ({'current' if live else 'expired'})"


def teduh_watch(fetch, seen, today, nocode_keys):
    """data/prelaunch_teduh.csv ties a no-code row to TEDUH codes it hangs on:
    8 Conlay's suspended 14159-1 and 14159-2, which are not tracked. Each run
    reads what TEDUH says about them and makes a find when any of it changes --
    a new permit, a new registered name (a relaunch often renames), new sales,
    a new SPV. A bare developer code (14159) is also probed one phase past the
    highest known, so a relaunch registered as 14159-3 shows up too.

    The first reading of a code is a find as well: it is the row's TEDUH
    status, which is what she asked the watch to report. Nothing here writes
    projects.csv; putting a code on the row stays hers."""
    mem = seen.setdefault("teduh", {})          # code -> last reading
    reads = {}                                  # today's readings, so no code is asked twice

    def status(code):
        if code not in reads:
            reads[code] = teduh_status(fetch, code)
        return reads[code]

    nxt = seen.setdefault("teduh_next", {})     # developer code -> highest phase known
    rows = []
    watch = [r for r in read(TEDUH_WATCH)
             if ((r.get("tracker") or "").strip(), (r.get("project") or "").strip().upper()) in nocode_keys]
    codes = []                                   # (code, row) to read today
    for r in watch:
        v = (r.get("value") or "").strip()
        if re.fullmatch(r"\d+-\d+", v):
            codes.append((v, r))
        elif v.isdigit():
            # Highest phase already known: the codes listed, and any found earlier.
            known = [int(c.split("-")[1]) for c, _ in codes if c.split("-")[0] == v]
            known += [int(c.split("-")[1]) for c in mem if c.split("-")[0] == v]
            high = max([nxt.get(v, 0)] + known)
            for _ in range(TEDUH_NEXT_MAX):
                code = f"{v}-{high + 1}"
                st = status(code)
                if not st:                       # None = not registered; False = not asked
                    break
                high += 1
                codes.append((code, dict(r, label=f"new phase under {v}")))
                mem.setdefault(code, None)       # a find on first reading below
            nxt[v] = high
            # Phases found on earlier days are followed like the listed codes.
            for c in sorted(mem):
                if c.split("-")[0] == v and c not in {x for x, _ in codes}:
                    codes.append((c, dict(r, label=f"phase found under {v}")))
    done = set()
    for code, r in codes:
        if code in done:
            continue
        done.add(code)
        st = status(code)
        if st is False or st is None:
            continue
        before = mem.get(code)
        mem[code] = st
        label = (r.get("label") or "").strip()
        head = code + (f" ({label})" if label else "")
        if not before:
            facts = [f"TEDUH {head}: registered as {st['name'] or 'no name shown'}"
                     + (f", {st['spv']}" if st["spv"] else ""),
                     (f"{code}: {st['sold']} of {st['units']} sold" if st["sold"] and st["units"]
                      else f"{code}: {st['units'] or '?'} units, sold not shown"),
                     f"{code} permit: {permit_text(st, today)}"]
            if st["status"]:
                facts.append(f"{code} TEDUH status: {st['status']}")
        else:
            changed = [k for k in STATUS_WORDS if (before.get(k) or "") != (st.get(k) or "")]
            if not changed:
                continue
            facts = [f"Changed on TEDUH: {head}"] + \
                    [f"{code} {STATUS_WORDS[k]}: {before.get(k) or 'blank'} -> {st.get(k) or 'blank'}"
                     for k in changed]
        rows.append({"seen": today.isoformat(), "tracker": r["tracker"].strip(), "project": r["project"].strip(),
                     "source": f"TEDUH {code}", "kind": "teduh", "url": TEDUH_API.format(code),
                     "stage": "", "event_date": "", "ad_since": "", "permit": permit_text(st, today),
                     "by": "", "ads": "", "price_from": "", "confidence": "strong", "status": "new",
                     "note": "; ".join(f.replace(";", ",") for f in facts)})
    return rows


def mark_run(note):
    """Stamp the 'web' row of data/prelaunch_runs.csv with now in Malaysian
    time. The site shows it, because the pre-launch checks run on their own
    clock, not with the morning TEDUH refresh."""
    rows = read(RUNS)
    now = datetime.now(timezone.utc) + timedelta(hours=8)
    for r in rows:
        if r["run"] == "web":
            r["last_run"] = now.strftime("%Y-%m-%d %H:%M")
            r["note"] = note
    if rows:
        with open(RUNS, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", metavar="FILE", help="report only: list what would be found, write nothing else")
    ap.add_argument("--budget", type=int, default=BUDGET)
    args = ap.parse_args()
    today = date.today()
    report = bool(args.report)

    projects = read(PROJECTS)
    nocode = [p for p in projects if not (p.get("code") or "").strip()]
    # One entry per name: Horizon 27 sits on two trackers.
    by_name = {}
    for p in nocode:
        by_name.setdefault(simple(p["project"]).lower(), p)
    # Every tracked name, for "already tracked" on new-in-area checks.
    tracked = {simple(p.get("project") or "").lower() for p in projects} - {""}
    tracked = {n for n in tracked if len(n) >= 5}

    finds = read(FINDS)
    known_urls = {clean_url(f["url"]) for f in finds if f.get("url")}
    dismissed = {(f["tracker"], f["project"], f["stage"], f["event_date"]) for f in finds
                 if (f.get("status") or "").strip() == "dismissed"}

    seen = None
    if os.path.exists(SEEN):
        with open(SEEN, encoding="utf-8") as fh:
            seen = json.load(fh)
    baseline = seen is None and not report
    seen = seen or {"links": {}, "pages": {}}
    backfilled = seen.setdefault("backfilled", {})

    fetch = Fetcher(args.budget)
    items = []          # every item read today: dicts with title, url, date, text, via, kind, own

    # 0. TEDUH codes a no-code row hangs on (data/prelaunch_teduh.csv). First,
    # because it is a handful of requests and must not lose out to the budget.
    nocode_keys = {(p["tracker"].strip(), p["project"].strip().upper()) for p in nocode}
    teduh_rows = teduh_watch(fetch, seen, today, nocode_keys)

    # 1. Google News: one search per no-code name, one per area word.
    for key, p in by_name.items():
        q = f'"{simple(p["project"])}"'
        dev = developer_words(p)
        if too_broad(key) and dev:
            q += f' "{dev[0]}"'                     # '"The Eclipse" "Chin Hin"', not solar eclipses
        # A row's first search has no 30-day limit (not on the silent baseline,
        # which would bury the old news it is meant to surface).
        backfill = not baseline and key not in backfilled
        xml = fetch.get(gnews(q, recent=not backfill), "Google News " + q + (" (all dates)" if backfill else ""))
        if backfill and xml is not None:
            backfilled[key] = today.isoformat()
        for it in rss_items(xml or ""):
            items.append(dict(it, kind="news", own=None, backfill=backfill))
    for tracker, words in AREA_WORDS.items():
        for w in words:
            xml = fetch.get(gnews(f'"{w}" ("new launch" OR "pelancaran" OR "preview" OR "register interest")'),
                            "Google News " + w)
            for it in rss_items(xml or ""):
                items.append(dict(it, kind="news", own=None))

    # 2. Developer sites, sitemaps and Lowyat boards from prelaunch_sources.csv.
    for s in read(SOURCES):
        kind, url, probe = s["kind"], s["url"], (s.get("probe") or "").lower()
        if kind not in ("developer", "sitemap", "forum"):
            continue                                    # social links are for the laptop Run C
        if any(w in probe for w in ("blocked", "browser only", "laptop", "untested")):
            continue
        page = fetch.get(url, f"{kind} {s['developer']}")
        if page is None:
            continue
        if kind == "sitemap":
            for loc in re.findall(r"(?is)<loc>\s*(.*?)\s*</loc>", page):
                slug = urllib.parse.urlsplit(loc).path.strip("/").split("/")[-1].replace("-", " ")
                items.append({"title": slug, "url": loc, "date": None, "text": "", "via": s["developer"] + " sitemap",
                              "kind": "sitemap", "own": s.get("tracker")})
            continue
        host = urllib.parse.urlsplit(url).netloc
        front = links_of(page, url)
        if kind == "forum":
            for link, anchor in front:
                if "/topic/" in link:
                    items.append({"title": anchor, "url": link, "date": None, "text": "",
                                  "via": "Lowyat " + s["developer"].replace("Lowyat ", ""),
                                  "kind": "forum", "own": None})
            continue
        # A developer site: the front page, then its project-list pages one level down.
        pages = [(front, s["developer"] + " website")]
        for lp in listing_pages(front, host):
            sub = fetch.get(lp, f"listing {s['developer']} {urllib.parse.urlsplit(lp).path}")
            if sub is not None:
                pages.append((links_of(sub, lp), s["developer"] + " website " + urllib.parse.urlsplit(lp).path))
        for links, via in pages:
            for link, anchor in links:
                if urllib.parse.urlsplit(link).netloc != host:
                    continue
                # The address counts as text too: a picture tile has no words.
                items.append({"title": anchor or slug_words(link), "url": link, "date": None,
                              "text": slug_words(link), "via": via,
                              "kind": "developer page", "own": s.get("tracker")})

    # 3. Saved pages: a change in their key facts is the news.
    page_changes = []
    owners = {}
    for pg in read(PAGES):
        owners.setdefault(pg["url"], pg)
    for url, pg in owners.items():
        page = fetch.get(url, "page " + (pg.get("label") or url))
        if page is None:
            continue
        txt = text_of(page) + " " + summary_of(page)
        facts = sorted(set(re.findall(r"\bRM\s?\d[\d,.]*\s?(?:k|mil|million)?\b", txt, re.I))
                       | {s for s, ws in STAGE_WORDS if any(has(txt.lower(), w) for w in ws)}
                       | set(re.findall(r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+20\d\d\b", txt)))
        before = seen["pages"].get(url)
        seen["pages"][url] = facts
        if report or (before is not None and before != facts):
            added = [f for f in facts if before is None or f not in before]
            if added:
                page_changes.append((pg, added, txt))

    # Judge.
    new_rows, taken, news_count = [], set(), {}
    places = read_places()
    # Stories with a stage word first, so the per-row cap keeps the informative ones.
    items.sort(key=lambda it: (it["kind"] != "news", not stage_of((it["title"] + " " + it["text"]).lower())))
    for it in items:
        url = clean_url(it["url"])
        if not url.startswith(("http://", "https://")):
            continue
        is_new = url not in seen["links"]
        seen["links"].setdefault(url, today.isoformat())
        # An all-dates story may already be in memory from the silent baseline; it still counts once.
        if baseline or (not report and not is_new and not it.get("backfill")) or url in known_urls or url in taken:
            continue
        text = (it["title"] + " " + it["text"]).lower()
        if not text.strip():
            continue
        hit = None
        for key, p in by_name.items():
            if not has(text, key):
                continue
            if too_broad(key) and it["own"] != p["tracker"] and \
                    not any(has(text, w.lower()) for w in developer_words(p)):
                continue
            hit = p
            break
        stage, price, event = stage_of(text), price_of(it["title"] + " " + it["text"]), event_of(it["title"] + " " + it["text"], today)
        if hit:
            t = ticks_for(hit, text, it, today, bool(it["own"]) and it["own"] == hit["tracker"], places)
            if (hit["tracker"], hit["project"], stage, event) in dismissed:
                continue
            if it.get("backfill") and level(t) == "weak":
                continue                # old name-only stories: a fish farm in Manitoba, not Sapphire Springs
            if it["kind"] == "news":
                n = news_count.get(hit["project"], 0)
                if n >= NEWS_PER_ROW:
                    continue
                news_count[hit["project"]] = n + 1
            row = {"tracker": hit["tracker"], "project": hit["project"], "confidence": level(t), "ticks": t}
        else:
            if it.get("backfill"):
                continue                # all-dates searches are for their row only, not area news from 2017
            area = next((tr for tr, ws in AREA_WORDS.items() if any(has(text, w) for w in ws)), None)
            if not area or not any(has(text, w) for w in LAUNCH_WORDS):
                continue
            if any(has(text, w) for w in RESALE_WORDS) or any(has(text, n) for n in tracked):
                continue
            current = it["date"] is None or (today - it["date"]).days <= CURRENT_DAYS
            row = {"tracker": area, "project": "", "confidence": "possible" if current else "weak", "ticks": None}
        taken.add(url)
        title = it["title"].replace(";", ",").strip()[:160]
        note = [title] if title else []
        if it["date"]:
            note.append("dated " + it["date"].isoformat())
        if row["ticks"]:
            note.append(tick_line(row["ticks"]))
        new_rows.append({"seen": today.isoformat(), "tracker": row["tracker"], "project": row["project"],
                         "source": it["via"], "kind": it["kind"], "url": url, "stage": stage,
                         "event_date": event, "ad_since": "", "permit": "",
                         "by": "Developer" if it["own"] else "", "ads": "", "price_from": price,
                         "confidence": row["confidence"], "status": "new", "note": "; ".join(note)})

    new_rows += teduh_rows

    for pg, added, txt in page_changes:
        stage = stage_of(" ".join(added).lower())
        new_rows.append({"seen": today.isoformat(), "tracker": pg["tracker"], "project": pg["project"],
                         "source": "saved page " + (pg.get("label") or pg["url"]), "kind": "page change",
                         "url": clean_url(pg["url"]), "stage": stage if stage else "", "event_date": "",
                         "ad_since": "", "permit": "", "by": "", "ads": "",
                         "price_from": next((a for a in added if a.upper().startswith("RM")), ""),
                         "confidence": "possible", "status": "new",
                         "note": "New on the page: " + ", ".join(added)[:200]})

    # Write.
    if report:
        lines = [f"# Pre-launch watch -- report only ({today.isoformat()})", "",
                 "Nothing was written. Memory was ignored, so every match is listed as if it were new.", "",
                 f"Sources asked: {fetch.asked}. Items read: {len(items)}. Would-be finds: {len(new_rows)}.", ""]
        for lvl in ("strong", "possible", "weak"):
            rows = [r for r in new_rows if r["confidence"] == lvl]
            lines += [f"## {lvl.capitalize()} ({len(rows)})", ""]
            for r in rows:
                what = r["project"] or f"NEW IN {r['tracker'].upper()}"
                lines.append(f"- **{what}** -- {r['source']} -- {r['stage'] or 'no stage'}"
                             f"{' -- ' + r['event_date'] if r['event_date'] else ''}"
                             f"{' -- ' + r['price_from'] if r['price_from'] else ''}  ")
                lines.append(f"  {r['note']}  ")
                lines.append(f"  {r['url']}")
            lines.append("")
        lines += ["## Problems", ""] + [f"- {e}" for e in fetch.errors] + \
                 [f"- skipped (time budget): {s}" for s in fetch.skipped] + [""]
        with open(args.report, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        print(f"report: {len(new_rows)} would-be finds from {len(items)} items; {len(fetch.errors)} errors -> {args.report}")
        return

    with open(SEEN, "w", encoding="utf-8") as fh:
        json.dump(seen, fh, indent=0, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    mark_run(f"{fetch.asked} sources asked, {len(fetch.errors)} failed, {len(new_rows) if not baseline else 0} new finds")
    if baseline:
        print(f"baseline: remembered {len(seen['links'])} links and {len(seen['pages'])} pages; no finds on the first run")
        return
    if new_rows:
        with open(FINDS, "a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            for r in new_rows:
                w.writerow(r)
    print(f"{len(new_rows)} new finds ({sum(r['confidence'] == 'strong' for r in new_rows)} strong) "
          f"from {len(items)} items; {len(fetch.errors)} sources failed, {len(fetch.skipped)} skipped")
    for e in fetch.errors + [f"skipped: {s}" for s in fetch.skipped]:
        print("  " + e)


if __name__ == "__main__":
    sys.exit(main())
