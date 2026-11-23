#!/usr/bin/env python3
"""Pre-launch watch: the brochure / APDL check (added 21 Nov 2026).

  python3 scripts/watch_brochures.py                       # the daily run
  python3 scripts/watch_brochures.py --report out.md       # report only, writes nothing
  python3 scripts/watch_brochures.py --report out.md --only myra --pages 40

A developer puts a project's advertising permit (APDL) on its website, often
only inside a PDF ("APDL", "e-Brochure") that has to be clicked to open. The
law makes every advertisement carry the permit number, and its first part is
the project's TEDUH code: 20164-3/06-2028/0447(N)-(S) is code 20164-3. So a
permit number that shows up for a no-code row is the strongest pre-launch
sign there is -- and the code it needs.

Each run reads, within a time budget:
  1. every saved page in data/prelaunch_pages.csv that belongs to a no-code
     row (official sites, microsites, agent pages);
  2. each developer's front page and project-list pages from
     prelaunch_sources.csv (the same rows, and the same skips, as
     watch_prelaunch.py), then its project pages one level down: pages whose
     link names a no-code row every day, never-read pages next, and the rest
     again after REVISIT_DAYS -- so the whole site comes round about weekly;
  3. the PDFs linked from those pages that it has not opened before, permit
     and brochure files first (pypdf; a scanned PDF has no text to read).

It looks for permit numbers in the page text and the PDF text. A permit whose
TEDUH code is on no tracker yet, found on a no-code row's saved page or next to
the row's name on its developer's site, becomes a find in
data/prelaunch_finds.csv: kind "permit", the permit number in the Permit
column, status "new". A code on no tracker that matches no row is only listed
in the log (the developer watch probes new phases on TEDUH itself).

Memory is data/prelaunch_brochures.json: when each page was last read, every
PDF opened (once only) and every permit code seen. Like the rest of the
pre-launch watch it never writes projects.csv -- the code goes on her row only
when she says so -- and it never fills a form, so a brochure behind a sign-up
form stays out of reach.
"""
import argparse, csv, io, json, logging, os, re, signal, sys, time
import urllib.error, urllib.parse, urllib.request
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import watch_prelaunch as W   # noqa: E402 - shares fetching, matching and the finds format

MEMORY = os.path.join(W.ROOT, "data", "prelaunch_brochures.json")
TEDUH_WATCH = W.TEDUH_WATCH
BUDGET = 420            # seconds; the workflow step's hard limit is 8 minutes
PAGE_SHARE = 0.7        # of the budget for pages; the rest is for PDFs (few once each is opened)
PAGE_MAX = 150          # developer project pages read per run
PDF_MAX = 40            # PDFs opened per run
PDF_BYTES = 20_000_000  # a bigger file is skipped (brochures run to 50 MB)
PDF_PAGES = 40          # pages of text read from one PDF
PDF_SECONDS = 30        # one PDF may take this long to read
REVISIT_DAYS = 7

# 20164-3/06-2028/0447(N)-(S), 5534-32/08-2027/0754(A)-(S), 19355-4/09-2027/0893(R)-(L)
PERMIT = re.compile(r"(?<![\d/-])(\d{3,5}-\d{1,3})\s*/\s*(\d{1,2})\s*-\s*(20\d\d)\s*/\s*(\d{2,6})"
                    r"\s*(\(\s*[A-Z]\s*\)(?:\s*-\s*\(\s*[A-Z]\s*\))?)?")
_DATE = (r"\d{1,2}\s*[./-]\s*\d{1,2}\s*[./-]\s*20\d\d|\d{1,2}\s+(?:jan|feb|ma[cr]|apr|m[ae][iy]|jun|jul|"
         r"ogo|aug|sep|o[kc]t|nov|di[sc])[a-z]*\.?\s+20\d\d")
VALID = re.compile(rf"({_DATE})\s*(?:-|–|—|to|hingga|sehingga|until)\s*({_DATE})", re.I)
# Not project pages: the company's own sections.
SKIP_PATH = re.compile(r"/(?:about(?:-us)?|careers?|contact(?:-us)?|news(?:room)?|media|press|investors?|ir|"
                       r"corporate|sustainability|esg|csr|privacy|pdpa|terms|tnc|faq|login|account|cart|"
                       r"blog|events?|awards?|tag|category|author|feed|wp-json|wp-admin|search|sitemap)(?:[/.-]|$)",
                       re.I)
FILE_EXT = re.compile(r"\.(?:jpe?g|png|gif|webp|svg|mp4|mov|zip|docx?|xlsx?|pptx?|ics|vcf|xml|json|css|js)$", re.I)
# PDFs that never carry a permit: the company's paperwork.
SKIP_PDF = re.compile(r"terms|privacy|pdpa|tnc|t&c|annual|circular|quarter|agm|egm|financial|sustainab|"
                      r"prospectus|policy|announcement|career|vacanc|guide|whistle|code-of|anti-|minutes",
                      re.I)
PERMITISH = re.compile(r"apdl|permit|lesen|licen[cs]e|iklan|(?:^|[^a-z])ap(?:[^a-z]|$)", re.I)
BROCHUREISH = re.compile(r"brochure|e-?book|booklet|pamphlet|catalog|factsheet|fact-sheet|flyer|leaflet", re.I)
NOT_READ = ("facebook.com", "instagram.com", "tiktok.com", "threads.", "youtube.com", "youtu.be",
            "xiaohongshu", "linkedin.com", "wa.me", "whatsapp", "t.me/")

logging.getLogger("pypdf").setLevel(logging.ERROR)     # font warnings, not problems


# ---------------------------------------------------------------- reading

def quote_url(url):
    """File names with spaces ("Halaman 1-AP-19.08.2025-18.08.2027.pdf") must
    be encoded before urllib will ask for them."""
    u = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((u.scheme, u.netloc, urllib.parse.quote(u.path, safe="/%:@!$&'()*+,;=-._~"),
                                    u.query, ""))


class Fetch(W.Fetcher):
    def left(self):
        return self.budget - (time.time() - self.start)

    def get(self, url, label):
        q = quote_url(url)
        page = super().get(q, label)
        if q in self.final:
            self.final[url] = self.final[q]
        return page

    def get_pdf(self, url, label):
        """(bytes, "") or (None, why)."""
        if self.left() < PDF_SECONDS:
            self.skipped.append(label)
            return None, "no time left"
        time.sleep(W.PAUSE)
        self.asked += 1
        try:
            req = urllib.request.Request(quote_url(url), headers={"User-Agent": W.UA})
            with urllib.request.urlopen(req, timeout=45) as r:
                size = int(r.headers.get("Content-Length") or 0)
                if size > PDF_BYTES:
                    return None, f"too big ({size // 1_000_000} MB)"
                raw = r.read(PDF_BYTES + 1)
        except (urllib.error.URLError, OSError, ValueError) as e:
            self.errors.append(f"{label}: {getattr(e, 'code', '') or type(e).__name__}")
            return None, "could not be fetched"
        if len(raw) > PDF_BYTES:
            return None, "too big"
        if not raw.lstrip()[:5].startswith(b"%PDF"):
            return None, "not a PDF"
        return raw, ""


def pdf_text(raw):
    """(text, "") or (None, why). A PDF from the web is untrusted, so reading
    one is capped in pages and seconds."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return None, "pypdf is not installed"
    alarm = hasattr(signal, "SIGALRM")
    if alarm:
        def late(*_):
            raise TimeoutError
        old = signal.signal(signal.SIGALRM, late)
        signal.alarm(PDF_SECONDS)
    try:
        rd = PdfReader(io.BytesIO(raw))
        txt = " ".join((p.extract_text() or "") for p in rd.pages[:PDF_PAGES])
    except TimeoutError:
        return None, "took too long to read"
    except Exception as e:                          # noqa: BLE001 - a broken PDF is a skip, not a crash
        return None, f"unreadable ({type(e).__name__})"
    finally:
        if alarm:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old)
    txt = re.sub(r"\s+", " ", txt).strip()
    return (txt, "") if txt else (None, "a scan (no text to read)")


def title_of(html):
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    return W.text_of(m.group(1)) if m else ""


def pdf_links_of(html, base):
    """(absolute url, anchor) for every PDF the page links or embeds."""
    out, seen = [], set()
    for link, anchor in W.links_of(html, base):
        if urllib.parse.urlsplit(link).path.lower().endswith(".pdf") and link not in seen:
            seen.add(link)
            out.append((link, anchor))
    # iframes, data-* attributes and scripts that carry a .pdf address
    for m in re.finditer(r"""["']([^"'<>\s]+?\.pdf)(?:[?#][^"'<>\s]*)?["']""", html, re.I):
        link = urllib.parse.urljoin(base, m.group(1).replace("&amp;", "&"))
        if link.startswith(("http://", "https://")) and link not in seen:
            seen.add(link)
            out.append((link, ""))
    return out


def permits_in(text):
    """Every permit number in a text: code, number, validity, and the words
    around it (which often name the project)."""
    out, prev_end = [], 0
    for m in PERMIT.finditer(text or ""):
        around = text[max(0, m.start() - 250): m.end() + 250]
        # The validity usually follows its own number; two permits in one
        # block must not borrow each other's dates.
        nxt = PERMIT.search(text, m.end())
        v = VALID.search(text[m.end(): min(m.end() + 250, nxt.start() if nxt else len(text))]) \
            or (VALID.search(text[m.start() - 120: m.start()]) if prev_end <= m.start() - 120 else None)
        prev_end = m.end()
        # Tidied outside the f-string: Python 3.11 (what the workflows run)
        # refuses a backslash inside an f-string's {...}.
        valid = ""
        if v:
            start = re.sub(r"\s+", " ", v.group(1))
            end = re.sub(r"\s+", " ", v.group(2))
            valid = f"{start} - {end}"
        out.append({"code": m.group(1), "number": re.sub(r"\s+", "", m.group(0)),
                    "valid": valid,
                    "around": re.sub(r"\s+", " ", around)})
    return out


def pdf_rank(url, anchor):
    """Which PDFs to open first: permit files, then brochures, then the rest."""
    words = urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1]) + " " + anchor
    if PERMITISH.search(words):
        return 0
    if BROCHUREISH.search(words):
        return 1
    return 2


# ---------------------------------------------------------------- matching

def code_list(value):
    return {c for c in re.split(r"[\s,;/]+", value or "") if re.fullmatch(r"\d{3,5}-\d{1,3}", c)}


def known_codes(projects):
    """Codes already on a tracker, plus the ones deliberately watched but not
    tracked (8 Conlay's suspended 14159-1/-2): neither is news here."""
    out = set()
    for p in projects:
        out |= code_list(p.get("code"))
    for r in W.read(TEDUH_WATCH):
        out |= code_list(r.get("value"))
    return out


def row_for(text, nocode, own_tracker):
    """The no-code row a piece of text names, by the watch's own rule: a
    too-broad name ("The Eclipse") counts only next to its developer or on its
    own tracker's site."""
    text = text.lower()
    for key, p in nocode.items():
        if not W.has(text, key):
            continue
        if W.too_broad(key) and own_tracker != p["tracker"] and \
                not any(W.has(text, w.lower()) for w in W.developer_words(p)):
            continue
        return p
    return None


def project_links(pages, sites):
    """The developer's own pages found on its front and listing pages, minus
    the company's paperwork: (url, anchor) once each."""
    out, seen = [], set()
    for links in pages:
        for link, anchor in links:
            u = urllib.parse.urlsplit(link)
            if W.site_of(link) not in sites or u.query or FILE_EXT.search(u.path) \
                    or SKIP_PATH.search(u.path) or u.path.strip("/") == "":
                continue
            clean = urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, "", ""))
            key = clean.rstrip("/")
            if key not in seen:
                seen.add(key)
                out.append((clean, anchor))
    return out


# ---------------------------------------------------------------- the run

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", metavar="FILE", help="report only: list what it would find, write nothing")
    ap.add_argument("--only", help="report only: developers whose name contains this (no saved pages)")
    ap.add_argument("--pages", type=int, default=PAGE_MAX)
    ap.add_argument("--pdfs", type=int, default=PDF_MAX)
    ap.add_argument("--budget", type=int, default=BUDGET)
    args = ap.parse_args(argv)
    report = bool(args.report)
    today = date.today()
    t0 = today.isoformat()

    projects = W.read(W.PROJECTS)
    known = known_codes(projects)
    nocode = {}
    for p in projects:
        if not (p.get("code") or "").strip():
            nocode.setdefault(W.simple(p["project"]).lower(), p)
    rows_by_key = {(p["tracker"].strip(), p["project"].strip().upper()): p for p in projects
                   if not (p.get("code") or "").strip()}
    finds = W.read(W.FINDS)
    reported = {(f["tracker"], f["project"], c) for f in finds if (f.get("kind") or "").strip() == "permit"
                for c in code_list(PERMIT.sub(lambda m: m.group(1), f.get("permit") or ""))}

    mem = {}
    if os.path.exists(MEMORY) and not report:
        with open(MEMORY, encoding="utf-8") as fh:
            mem = json.load(fh)
    mem.setdefault("pages", {})
    mem.setdefault("pdfs", {})
    mem.setdefault("codes", {})

    fetch = Fetch(args.budget)
    page_budget = args.budget * PAGE_SHARE
    hits = []           # (row or None, permit, where) for every permit read
    pdf_queue = {}      # url -> (rank, anchor, page url, page ident, own tracker, row or None, source label, by)

    def look(text, ident, url, own, row, source, by, pdf=None):
        for pm in permits_in(text):
            r = row or row_for(ident + " " + pm["around"], nocode, own)
            hits.append({"row": r, "permit": pm, "url": url, "source": source, "by": by, "pdf": pdf})

    def queue_pdfs(html, base, ident, own, row, source, by):
        for link, anchor in pdf_links_of(html, base):
            name = urllib.parse.unquote(urllib.parse.urlsplit(link).path.rsplit("/", 1)[-1])
            if SKIP_PDF.search(name + " " + anchor) or link in pdf_queue:
                continue
            if not report and link in mem["pdfs"]:
                continue                            # opened on an earlier day
            pdf_queue[link] = (pdf_rank(link, anchor), anchor, base, ident, own, row, source, by)

    # 1. Saved pages of no-code rows: each one already belongs to its row.
    if not args.only:
        for pg in W.read(W.PAGES):
            url = (pg.get("url") or "").strip()
            row = rows_by_key.get(((pg.get("tracker") or "").strip(), (pg.get("project") or "").strip().upper()))
            if row is None or not url.startswith("http") or any(s in url.lower() for s in NOT_READ):
                continue
            if fetch.left() < args.budget - page_budget:
                break
            html = fetch.get(url, "saved page " + (pg.get("label") or url))
            if html is None:
                continue
            base = fetch.final.get(url, url)
            kind = (pg.get("kind") or "").strip()
            by = "Agent" if kind == "agent" else ("Developer" if kind in ("official", "microsite") else "")
            source = "saved page " + (pg.get("label") or W.site_of(url))
            look(W.text_of(html), "", url, row["tracker"], row, source, by)
            queue_pdfs(html, base, "", row["tracker"], row, source, by)
            mem["pages"][url] = t0

    # 2. Developer sites: front page and listing pages, then project pages.
    candidates = []     # (priority, last read, url, anchor, dev, own)
    for s in W.read(W.SOURCES):
        if s["kind"] != "developer":
            continue
        probe = (s.get("probe") or "").lower()
        if any(w in probe for w in ("blocked", "browser only", "laptop", "untested")):
            continue
        if args.only and args.only.lower() not in s["developer"].lower():
            continue
        if fetch.left() < args.budget - page_budget:
            break
        url, dev, own = s["url"], s["developer"], (s.get("tracker") or "").strip()
        html = fetch.get(url, f"developer {dev}")
        if html is None:
            continue
        base = fetch.final.get(url, url)
        sites = {W.site_of(url), W.site_of(base)}
        front = W.links_of(html, base)
        listings = [(front, html, base)]
        for lp in W.listing_pages(front, sites):
            sub = fetch.get(lp, f"listing {dev}")
            if sub is not None:
                lbase = fetch.final.get(lp, lp)
                listings.append((W.links_of(sub, lbase), sub, lbase))
        for links, page, pbase in listings:
            # A front or listing page shows many projects: only the words
            # around a permit can say whose it is.
            look(W.text_of(page), "", pbase, own, None, f"{dev} website", "Developer")
            queue_pdfs(page, pbase, "", own, None, f"{dev} website", "Developer")
        done = {l.rstrip("/") for _, _, l in listings}
        for link, anchor in project_links([l for l, _, _ in listings], sites):
            if link.rstrip("/") in done:
                continue
            ident = anchor + " " + W.slug_words(link)
            named = row_for(ident, nocode, own) is not None
            last = mem["pages"].get(link, "")
            if not named and last and last > (today - timedelta(days=REVISIT_DAYS)).isoformat():
                continue                            # read this week already
            candidates.append((0 if named else (1 if not last else 2), last, link, anchor, dev, own))

    candidates.sort(key=lambda c: (c[0], c[1]))
    named_pages = sum(1 for c in candidates if c[0] == 0)
    read_pages = 0
    for _, _, link, anchor, dev, own in candidates:
        if read_pages >= args.pages or fetch.left() < args.budget - page_budget:
            break
        html = fetch.get(link, f"page {dev} {urllib.parse.urlsplit(link).path}")
        read_pages += 1
        mem["pages"][link] = t0
        if html is None:
            continue
        base = fetch.final.get(link, link)
        ident = " ".join([anchor, W.slug_words(link), title_of(html)])
        row = row_for(ident, nocode, own)
        look(W.text_of(html), ident, link, own, row, f"{dev} website", "Developer")
        queue_pdfs(html, base, ident, own, row, f"{dev} website", "Developer")

    # 3. PDFs not opened before: permit files first, then brochures.
    opened, why_not = 0, {}
    for link, (rank, anchor, page, ident, own, row, source, by) in sorted(pdf_queue.items(), key=lambda kv: kv[1][0]):
        if opened >= args.pdfs or fetch.left() < PDF_SECONDS:
            break
        name = urllib.parse.unquote(urllib.parse.urlsplit(link).path.rsplit("/", 1)[-1])
        raw, why = fetch.get_pdf(link, f"PDF {name}")
        opened += 1
        txt = None
        if raw is not None:
            txt, why = pdf_text(raw)
        if txt is None:
            why_not[link] = why
            if why != "no time left":
                mem["pdfs"][link] = {"seen": t0, "result": why, "codes": []}
            continue
        before = len(hits)
        pident = " ".join([ident, anchor, W.slug_words(link)])
        look(txt, pident, link, own, row, source + " PDF " + name[:60], by, pdf=(name, page))
        mem["pdfs"][link] = {"seen": t0, "result": "text",
                             "codes": sorted({h["permit"]["code"] for h in hits[before:]})}

    # Judge: a permit whose code is on no tracker, for a no-code row.
    new_rows, unmatched, taken = [], {}, set()
    for h in hits:
        code, row = h["permit"]["code"], h["row"]
        first = code not in mem["codes"]
        mem["codes"].setdefault(code, t0)
        if code in known:
            continue
        if row is None:
            if first or report:
                unmatched.setdefault(code, h)
            continue
        key = (row["tracker"], row["project"], code)
        if key in reported or key in taken:
            continue
        taken.add(key)
        pm = h["permit"]
        where = (f"in {h['pdf'][0]} (linked from {W.clean_url(h['pdf'][1])})" if h["pdf"]
                 else "on " + W.clean_url(h["url"]))
        # Strong on the developer's own pages; an agent or landing page may
        # carry another project's permit, so it is only Possible.
        own_site = h["by"] == "Developer"
        new_rows.append({
            "seen": t0, "tracker": row["tracker"], "project": row["project"],
            "source": h["source"][:120], "kind": "permit", "url": W.clean_url(h["url"]),
            "stage": "", "event_date": "", "ad_since": "",
            "permit": f"APDL {pm['number']}" + (f", valid {pm['valid']}" if pm["valid"] else ""),
            "by": h["by"], "ads": "", "price_from": "",
            "confidence": "strong" if own_site else "possible", "status": "new",
            "note": (f"APDL {pm['number']} shown {where}: TEDUH code {code}, on no tracker yet. "
                     f"Check it is this project before adding the code").replace(";", ",")})

    summary = (f"brochure check: {fetch.asked} requests, {read_pages} project pages ({named_pages} name a no-code row, "
               f"{sum(1 for c in candidates if c[0] == 1)} never read), {opened} PDFs opened, "
               f"{len(hits)} permits read, {len(new_rows)} new finds, {len(unmatched)} codes on no tracker "
               f"and no row; {len(fetch.errors)} failed, {len(fetch.skipped)} skipped")

    if report:
        lines = [f"# Brochure check -- report only ({t0})", "", "Nothing was written. Memory was ignored.", "",
                 summary, "", f"## Would-be finds ({len(new_rows)})", ""]
        for r in new_rows:
            lines += [f"- **{r['project']}** ({r['tracker']}) -- {r['permit']} -- {r['confidence']}  ",
                      f"  {r['note']}  ", f"  {r['url']}"]
        lines += ["", "## Every permit read", ""]
        for h in hits:
            tag = "on a tracker" if h["permit"]["code"] in known else (
                "row: " + h["row"]["project"] if h["row"] else "no row")
            src = h["pdf"][0] if h["pdf"] else h["url"]
            lines.append(f"- {h['permit']['number']} ({tag}) -- {h['source']} -- {src}")
        lines += ["", "## PDFs not read", ""] + [f"- {why}: {u}" for u, why in why_not.items()]
        lines += ["", "## Problems", ""] + [f"- {e}" for e in fetch.errors] + \
                 [f"- skipped (time budget): {s}" for s in fetch.skipped] + [""]
        with open(args.report, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        print(summary + f" -> {args.report}")
        return 0

    with open(MEMORY, "w", encoding="utf-8") as fh:
        json.dump(mem, fh, indent=0, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    if new_rows:
        with open(W.FINDS, "a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=W.FIELDS)
            for r in new_rows:
                w.writerow(r)
    print(summary)
    for r in new_rows:
        print(f"  find: {r['project']} -- {r['permit']}")
    for code, h in unmatched.items():
        print(f"  on no tracker, no row: {h['permit']['number']} -- {h['source']} -- "
              f"{h['pdf'][0] if h['pdf'] else h['url']}")
    for e in fetch.errors + [f"skipped: {s}" for s in fetch.skipped]:
        print("  " + e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
