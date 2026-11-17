"""Why does TEDUH answer 500 for big projects' unit lists?  (test only)

From 15 Nov 2026 /api/unit-projek-swasta/{code} answered HTTP 500 for the
same 45 codes every run -- all 926+ units -- while every smaller code
answered normally. This script asks TEDUH a few ways and writes what came
back, so the fix can be built from evidence rather than guessed. It writes
nothing to the repository.

  Part A  the JSON addresses directly, slowly: the project detail, the unit
          list, the unit list with paging-style parameters, and the error
          body TEDUH sends with its 500.
  Part B  TEDUH's own website in a real browser: which /api/ addresses its
          JavaScript knows about, and which ones a project page actually
          loads, with status and size -- i.e. how the site itself gets the
          units of a big project now.

Usage:  python scripts/probe_teduh_units.py report.md
"""
import json
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = "https://teduh.kpkt.gov.my"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
FAILING = ["31100-1", "31074-1", "9832-11"]   # Causewayz A, The Address, PV 22
CONTROL = ["31451-1"]                          # Residensi Tiara, 330 units, answers fine
VARIANTS = ["", "?page=1", "?page=1&per_page=50", "?limit=100", "?blok=A"]
PAUSE = 5        # seconds between requests -- slower than the scrape's 1.1s
SLOW = 30        # one request per failing code after a long quiet gap

out = []


def say(line=""):
    print(line, flush=True)
    out.append(line)


def get(path):
    """Return (status, headers, body text) without raising."""
    req = Request(BASE + path, headers={"User-Agent": UA, "Accept": "application/json"})
    t = time.time()
    try:
        with urlopen(req, timeout=60) as r:
            body = r.read().decode("utf-8", "replace")
            return r.status, dict(r.headers), body, time.time() - t
    except HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        return e.code, dict(e.headers or {}), body, time.time() - t
    except (URLError, TimeoutError, OSError) as e:
        return None, {}, f"{type(e).__name__}: {e}", time.time() - t


def shape(body):
    """A short description of a JSON reply: keys, unit counts, paging hints."""
    try:
        j = json.loads(body)
    except Exception:
        return "not JSON: " + body[:300].replace("\n", " ")
    if isinstance(j, list):
        return f"JSON list of {len(j)}"
    bits = ["keys: " + ", ".join(list(j)[:25])]
    groups = j.get("unitGroups")
    if isinstance(groups, list):
        n = sum(len(g.get("units", [])) for g in groups)
        bits.append(f"unitGroups {len(groups)}, units {n}")
    for k in ("total", "per_page", "last_page", "current_page", "next_page_url", "links", "meta"):
        if k in j:
            bits.append(f"{k}={json.dumps(j[k])[:120]}")
    return "; ".join(bits)


def part_a():
    say("## Part A -- the JSON addresses, asked directly")
    say(f"One request every {PAUSE}s (the scrape uses 1.1s).")
    say()
    for code in FAILING + CONTROL:
        tag = "control, answers in the scrape" if code in CONTROL else "fails in the scrape"
        say(f"### {code} ({tag})")
        for path in [f"/api/projek-swasta/{code}"] + \
                    [f"/api/unit-projek-swasta/{code}{v}" for v in VARIANTS]:
            st, hd, body, secs = get(path)
            say(f"- `{path}` -> **{st}**, {len(body):,} chars, {secs:.1f}s, "
                f"type {hd.get('Content-Type', '?')}")
            say(f"  - {shape(body) if st == 200 else body[:400].replace(chr(10), ' ')}")
            time.sleep(PAUSE)
        say()
    say(f"### Slow retry: each failing code once more after {SLOW}s of quiet")
    for code in FAILING:
        time.sleep(SLOW)
        st, _, body, secs = get(f"/api/unit-projek-swasta/{code}")
        say(f"- `{code}` -> **{st}**, {len(body):,} chars, {secs:.1f}s")
    say()


def part_b():
    say("## Part B -- TEDUH's own website in a browser")
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        say(f"Playwright not available: {e}")
        return
    seen = []

    def on_response(r):
        if "/api/" in r.url:
            try:
                size = len(r.body())
            except Exception:
                size = -1
            seen.append((r.request.method, r.url, r.status, size))

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(user_agent=UA)
        pg.on("response", on_response)
        try:
            pg.goto(BASE + "/", wait_until="networkidle", timeout=60000)
            say(f"Home page: {pg.url} -- title {pg.title()!r}")
        except Exception as e:
            say(f"Home page failed: {e}")

        # Every /api/ string in the site's own JavaScript: tells us which
        # addresses (and parameters) the website itself uses for units.
        scripts = pg.eval_on_selector_all("script[src]", "els => els.map(e => e.src)")
        found = set()
        for src in scripts:
            try:
                js = pg.request.get(src, timeout=60000).text()
            except Exception as e:
                say(f"- could not read {src}: {e}")
                continue
            for m in re.finditer(r"""["'`]([^"'`\s]{0,40}/api/[^"'`\s]{1,120})["'`]""", js):
                found.add(m.group(1))
            for m in re.finditer(r".{0,80}unit-projek.{0,160}", js):
                found.add("CONTEXT: " + m.group(0))
        say(f"Scripts read: {len(scripts)}")
        say("API strings in the site's JavaScript:")
        for s in sorted(found)[:80]:
            say(f"- `{s[:260]}`")
        say()

        # Try the likely project-page addresses for one failing code and one
        # control, and record every /api/ call each page makes.
        for code in FAILING[:1] + CONTROL:
            for path in (f"/projek-swasta/{code}", f"/projek/{code}",
                         f"/#/projek-swasta/{code}", f"/maklumat-projek/{code}"):
                del seen[:]
                try:
                    pg.goto(BASE + path, wait_until="networkidle", timeout=60000)
                    pg.wait_for_timeout(4000)
                    text = pg.inner_text("body")[:300].replace("\n", " | ")
                    say(f"### page `{path}` -> {pg.url}")
                    say(f"- page text starts: {text}")
                except Exception as e:
                    say(f"### page `{path}` failed: {e}")
                for method, url, st, size in seen:
                    say(f"- {method} `{url}` -> **{st}**, {size:,} bytes")
                say()
        b.close()


def main():
    report = sys.argv[1] if len(sys.argv) > 1 else "report.md"
    say("# TEDUH unit-list probe")
    say(time.strftime("Run at %Y-%m-%d %H:%M UTC", time.gmtime()))
    say()
    for part in (part_a, part_b):
        try:
            part()
        except Exception as e:
            say(f"**{part.__name__} stopped:** {type(e).__name__}: {e}")
    open(report, "w", encoding="utf-8").write("\n".join(out) + "\n")


if __name__ == "__main__":
    main()
