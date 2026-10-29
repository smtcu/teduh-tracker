#!/usr/bin/env python3
"""One-off reachability test: which pre-launch sources answer from GitHub?

  python scripts/probe_sources.py              # second list, plain fetch + real browser
  python scripts/probe_sources.py --set first  # the first run's list
  python scripts/probe_sources.py --no-browser # plain fetch only

Built before designing a daily pre-launch watch, because TEDUH taught us that
what a sandbox can reach and what GitHub Actions can reach are different. Each
source is asked twice, once as a plain HTTP download (what a cheap daily check
would use) and once in headless Chromium (for pages that only fill in with
JavaScript), and the result says which of the two -- if either -- got a real
page rather than an error, a bot challenge or an empty shell.

One request per source per method, a pause between each, nothing retried. It
writes only into probe_out/ (uploaded as a workflow artifact) and the job
summary: never data/, docs/ or projects.csv, and it never commits.
"""
import argparse, json, os, re, sys, time, urllib.error, urllib.request

PAUSE = 2.0
TIMEOUT = 30
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# (key, label, url, words a real page should contain -- any one is enough)
# First run, 29 Oct 2026: portals, Google, forums, Bursa, six developer sites.
FIRST = [
    ("pg_newlaunch", "PropertyGuru new launches",
     "https://www.propertyguru.com.my/new-property-launch", ["launch", "developer"]),
    ("ip_newlaunch", "iProperty new launches",
     "https://www.iproperty.com.my/new-launch/", ["launch", "developer"]),
    ("ep_newlaunch", "EdgeProp new launches",
     "https://www.edgeprop.my/new-launches", ["launch", "developer"]),
    ("ep_news", "EdgeProp news",
     "https://www.edgeprop.my/news", ["property", "launch"]),
    ("gnews_rss", "Google News RSS (new launch Cheras)",
     "https://news.google.com/rss/search?q=%22new+launch%22+Cheras&hl=en-MY&gl=MY&ceid=MY:en",
     ["<item>", "<rss"]),
    ("gads", "Google Ads Transparency Center (MY)",
     "https://adstransparency.google.com/?region=MY", ["advertiser", "ads"]),
    ("lowyat", "Lowyat forum",
     "https://forum.lowyat.net/", ["forum", "topic"]),
    ("bursa", "Bursa company announcements",
     "https://www.bursamalaysia.com/market_information/announcements/company_announcement",
     ["announcement"]),
    ("fb_adlib", "Meta Ad Library (expected to fail)",
     "https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=MY"
     "&q=%22The%20Shang%20Residence%22&search_type=keyword_exact_phrase", ["ad library"]),
    ("dev_mahsing", "Mah Sing website",
     "https://www.mahsing.com.my/", ["mah sing"]),
    ("dev_spsetia", "S P Setia website",
     "https://www.spsetia.com/", ["setia"]),
    ("dev_simedarby", "Sime Darby Property website",
     "https://www.simedarbyproperty.com/", ["sime darby"]),
    ("dev_ecoworld", "Eco World website",
     "https://ecoworld.my/", ["eco world", "ecoworld"]),
    ("dev_uem", "UEM Sunrise website",
     "https://www.uemsunrise.com/", ["uem sunrise"]),
    ("dev_lbs", "LBS website",
     "https://www.lbs.com.my/", ["lbs"]),
]

# Second run: every tracked developer's website, plus the Lowyat property
# section. Addresses come from the SPV email domains in data/developers.csv
# where there is one; the rest are guesses, and a DNS or certificate error
# says only that the guess was wrong, not that the site blocks GitHub.
_DEV = ["developer", "property", "project"]
SECOND = [
    ("lowyat_property", "Lowyat property section", "LOWYAT_PROPERTY", ["topic", "property"]),
    ("gnews_shang", "Google News RSS (The Shang Residence)",
     "https://news.google.com/rss/search?q=%22Shang+Residence%22&hl=en-MY&gl=MY&ceid=MY:en",
     ["<rss"]),
    ("spsetia_a", "S P Setia (spsetia.com)", "https://spsetia.com/", _DEV),
    ("spsetia_b", "S P Setia (www.spsetia.com.my)", "https://www.spsetia.com.my/", _DEV),
    ("spsetia_c", "S P Setia (setia.com.my)", "https://www.setia.com.my/", _DEV),
    ("avaland", "Avaland (guess)", "https://avaland.com.my/", _DEV),
    ("binastra", "Binastra", "https://www.binastra.com.my/", _DEV),
    ("brdb", "BRDB (guess)", "https://www.brdb.com.my/", _DEV),
    ("chinhin", "Chin Hin Property", "https://chinhinproperty.com/", _DEV),
    ("cpiland", "CPI Land (guess)", "https://www.cpiland.com.my/", _DEV),
    ("exsim", "Exsim", "https://exsim.my/", _DEV),
    ("ksl", "KSL", "https://ksl.my/", _DEV),
    ("lagenda", "Lagenda (guess)", "https://lagendaproperties.com/", _DEV),
    ("shangheight", "Shang Height", "https://shangheight.com.my/", _DEV),
    ("magma", "Magma", "https://magma.my/", _DEV),
    ("majesticgen_a", "Majestic Gen (majestic-gen.com)", "https://majestic-gen.com/", _DEV),
    ("majesticgen_b", "Majestic Gen (majesticgen.com.my)", "https://majesticgen.com.my/", _DEV),
    ("malton", "Malton", "https://www.malton.com.my/", _DEV),
    ("maxim", "Maxim Global", "https://maximglobal.com.my/", _DEV),
    ("mbworld", "MB World (guess)", "https://mbworld.com.my/", _DEV),
    ("myra", "Myra", "https://myra.com.my/", _DEV),
    ("paramount", "Paramount Property", "https://paramountproperty.my/", _DEV),
    ("platinumvictory", "Platinum Victory (guess)", "https://platinumvictory.com/", _DEV),
    ("radium", "Radium", "https://radiumdevelopment.com/", _DEV),
    ("scientex", "Scientex", "https://www.scientex.com.my/", _DEV),
    ("setiaawan", "Setia Awan (guess)", "https://setiaawan.com.my/", _DEV),
    ("sks", "SKS (guess)", "https://sks.com.my/", _DEV),
    ("skyworld", "SkyWorld (guess)", "https://skyworld.my/", _DEV),
    ("trinity", "Trinity Group", "https://trinitygroup.com.my/", _DEV),
    ("tslaw", "TS Law", "https://tslawland.com/", _DEV),
    ("armani", "Armani (guess)", "https://www.armanigroup.com.my/", _DEV),
    ("sunway", "Sunway Property (guess)", "https://www.sunwayproperty.com/", _DEV),
    ("osk", "OSK Property (guess)", "https://www.oskproperty.com.my/", _DEV),
    ("titijaya", "Titijaya (guess)", "https://www.titijaya.com.my/", _DEV),
]
SETS = {"first": FIRST, "second": SECOND}

# Words on a developer's page that suggest it announces projects before
# launch -- counted, so the summary shows which sites are worth watching.
PRELAUNCH = ["upcoming", "coming soon", "register your interest", "register interest",
             "new launch", "launching soon", "preview"]

# Text that means "a bot wall answered, not the site".
BLOCK_SIGNS = ["just a moment", "cf-chl", "challenge-platform", "captcha",
               "access denied", "attention required", "are you a robot",
               "enable javascript and cookies", "request unsuccessful",
               "incapsula", "perimeterx", "px-captcha", "log in to facebook",
               "you must log in"]


def title_of(html):
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    return re.sub(r"\s+", " ", m.group(1)).strip()[:80] if m else ""


def visible_text(html):
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def verdict(status, html, words):
    """ok / blocked / empty / error, plus the reason."""
    if status is None:
        return "error", "no response"
    low = html.lower()
    hit = [b for b in BLOCK_SIGNS if b in low]
    if status in (401, 403, 429, 503) or (hit and len(visible_text(html)) < 3000):
        return "blocked", f"HTTP {status}" + (f", '{hit[0]}'" if hit else "")
    if status >= 400:
        return "error", f"HTTP {status}"
    found = [w for w in words if w.lower() in low]
    if not found:
        return "empty", f"HTTP {status}, none of {words} on the page"
    if len(visible_text(html)) < 500 and "<rss" not in low:
        return "empty", f"HTTP {status}, only {len(visible_text(html))} chars of text"
    return "ok", f"HTTP {status}, found '{found[0]}'"


def plain(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept-Language": "en-MY,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read(3_000_000).decode("utf-8", "replace"), ""
    except urllib.error.HTTPError as e:
        try:
            body = e.read(500_000).decode("utf-8", "replace")
        except Exception:                           # noqa: BLE001
            body = ""
        return e.code, body, ""
    except Exception as e:                          # noqa: BLE001 - report, do not raise
        return None, "", f"{type(e).__name__}: {e}"[:120]


def lowyat_property():
    """The property forum's address, read off the Lowyat front page."""
    st, html, _ = plain("https://forum.lowyat.net/")
    for href, text in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>([^<]{2,60})</a>', html):
        if "property" in text.lower():
            return href if href.startswith("http") else "https://forum.lowyat.net" + href
    return "https://forum.lowyat.net/"


def prelaunch_hits(html):
    low = visible_text(html).lower()
    return sum(low.count(w) for w in PRELAUNCH)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--out", default="probe_out")
    ap.add_argument("--set", choices=sorted(SETS), default="second")
    args = ap.parse_args()
    global SOURCES
    SOURCES = [(k, lab, lowyat_property() if url == "LOWYAT_PROPERTY" else url, w)
               for k, lab, url, w in SETS[args.set]]
    os.makedirs(args.out, exist_ok=True)

    results = {k: {"label": lab, "url": url, "hits": 0} for k, lab, url, _ in SOURCES}

    print("== plain HTTP ==")
    for key, lab, url, words in SOURCES:
        st, html, err = plain(url)
        v, why = verdict(st, html, words) if st is not None else ("error", err)
        results[key].update(plain=v, plain_why=why, plain_title=title_of(html),
                            plain_bytes=len(html), url=url, hits=prelaunch_hits(html))
        with open(os.path.join(args.out, f"{key}.plain.html"), "w") as f:
            f.write(html)
        print(f"  {v:8} {lab}: {why}")
        time.sleep(PAUSE)

    if not args.no_browser:
        print("== headless Chromium ==")
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch()
            ctx = b.new_context(user_agent=UA, locale="en-MY",
                                viewport={"width": 1280, "height": 900})
            for key, lab, url, words in SOURCES:
                page = ctx.new_page()
                st, html, why = None, "", ""
                try:
                    resp = page.goto(url, timeout=TIMEOUT * 1000, wait_until="domcontentloaded")
                    page.wait_for_timeout(6000)     # let JavaScript fill the page in
                    st = resp.status if resp else None
                    html = page.content()
                    page.screenshot(path=os.path.join(args.out, f"{key}.png"))
                except Exception as e:              # noqa: BLE001
                    why = f"{type(e).__name__}: {e}"[:120]
                v, why2 = verdict(st, html, words) if st is not None else ("error", why or "no response")
                results[key].update(browser=v, browser_why=why2, browser_title=title_of(html),
                                    browser_bytes=len(html),
                                    hits=max(results[key]["hits"], prelaunch_hits(html)))
                with open(os.path.join(args.out, f"{key}.browser.html"), "w") as f:
                    f.write(html)
                print(f"  {v:8} {lab}: {why2}")
                page.close()
                time.sleep(PAUSE)
            b.close()

    with open(os.path.join(args.out, "results.json"), "w") as f:
        json.dump(results, f, indent=2)

    def why(r, k):
        w = (r.get(k) or "").splitlines()
        return w[0].replace("<", "&lt;").replace("|", "/") if w else ""

    mark = {"ok": "✅ ok", "blocked": "⛔ blocked", "empty": "⚠️ empty", "error": "❌ error"}
    lines = [f"## Pre-launch source reachability from GitHub Actions ({args.set} list)", "",
             "| Source | Plain fetch | Real browser | Pre-launch words | Page title (browser) |",
             "|---|---|---|---|---|"]
    for k, r in results.items():
        lines.append(f"| [{r['label']}]({r['url']}) "
                     f"| {mark.get(r.get('plain'), '–')}<br><sub>{why(r, 'plain_why')}</sub> "
                     f"| {mark.get(r.get('browser'), '–')}<br><sub>{why(r, 'browser_why')}</sub> "
                     f"| {r.get('hits', 0)} "
                     f"| {(r.get('browser_title') or r.get('plain_title') or '').replace('|', '/')} |")
    lines += ["", "Saved pages and screenshots are in the `probe-results` artifact."]
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    sys.exit(main())
