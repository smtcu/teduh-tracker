#!/usr/bin/env python3
"""One-off test: can Crawl4AI's stealth modes read the developer sites that
blocked GitHub on 29 Oct 2026?

  python scripts/probe_crawl4ai.py              # all sites, all three modes
  python scripts/probe_crawl4ai.py --modes plain,stealth

The 29 Oct probe (probe_sources.py) already tried every pre-launch source in a
plain headless Chromium. Five developer sites (Armani, UEM Sunrise, Lagenda,
Maxim, Majestic Gen) refused even that, so they were left to the laptop. The
question here is only whether Crawl4AI's anti-bot options change that answer:

  plain       Crawl4AI with no stealth -- the same as 29 Oct, re-run today so
              the comparison is like for like
  stealth     enable_stealth + simulate_user + override_navigator + magic
  undetected  the same, driven through Crawl4AI's UndetectedAdapter (patchright)

Exsim and Sunway ("browser only" on 29 Oct) are controls: every mode should
read them. If a control fails, the run itself is broken, not the site.

One request per site per mode, a pause between each, nothing retried. A page
is judged with probe_sources.verdict() -- the same rules as 29 Oct. Writes
only probe_c4/ (a workflow artifact) and the job summary: never data/, docs/
or projects.csv, and it never commits.
"""
import argparse, asyncio, base64, json, os, re, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from probe_sources import UA, verdict, title_of, visible_text, prelaunch_hits  # noqa: E402

PAUSE = 2.0
_DEV = ["developer", "property", "project"]

# (key, label, url, words a real page should contain -- any one is enough)
SITES = [
    ("armani_dev", "Armani: our developments", "https://armanigroup.com.my/our-developments/", _DEV),
    ("armani_home", "Armani: front page", "https://armanigroup.com.my/", _DEV),
    ("uem", "UEM Sunrise", "https://www.uemsunrise.com/", _DEV),
    ("lagenda", "Lagenda", "https://lagendaproperties.com/", _DEV),
    ("maxim", "Maxim Global", "https://maximglobal.com.my/", _DEV),
    ("majesticgen", "Majestic Gen", "https://majesticgen.com.my/", _DEV),
    ("shangheight", "Shang Height (untested address)", "https://shangheight.com/", _DEV),
    # controls -- "browser only" on 29 Oct, so every mode should read them
    ("exsim_dev", "Exsim: our developments (control)", "https://exsim.com.my/our-developments/", _DEV),
    ("sunway", "Sunway Property (control)", "https://www.sunwayproperty.com/", _DEV),
]
MODES = ["plain", "stealth", "undetected"]
WAS = {"armani_dev": "blocked", "armani_home": "blocked", "uem": "blocked",
       "lagenda": "blocked", "maxim": "blocked", "majesticgen": "blocked",
       "shangheight": "untested", "exsim_dev": "browser only", "sunway": "browser only"}


def make_crawler(mode):
    from crawl4ai import AsyncWebCrawler, BrowserConfig
    if mode == "plain":
        return AsyncWebCrawler(config=BrowserConfig(headless=True, user_agent=UA, verbose=False))
    bc = BrowserConfig(headless=True, enable_stealth=True, verbose=False)
    if mode == "stealth":
        return AsyncWebCrawler(config=bc)
    from crawl4ai import UndetectedAdapter
    from crawl4ai.async_crawler_strategy import AsyncPlaywrightCrawlerStrategy
    strat = AsyncPlaywrightCrawlerStrategy(browser_config=bc, browser_adapter=UndetectedAdapter())
    return AsyncWebCrawler(crawler_strategy=strat, config=bc)


def run_config(mode):
    from crawl4ai import CrawlerRunConfig, CacheMode
    sneaky = mode != "plain"
    return CrawlerRunConfig(cache_mode=CacheMode.BYPASS, wait_until="domcontentloaded",
                            page_timeout=45000, delay_before_return_html=6.0,
                            locale="en-MY", screenshot=True, verbose=False,
                            simulate_user=sneaky, override_navigator=sneaky, magic=sneaky)


def headings(md, n=12):
    """What a daily watch would see: the page's headings, which on a developer
    site are mostly project names."""
    out = []
    for line in md.splitlines():
        m = re.match(r"\s*#{1,4}\s+(.+)", line)
        if m:
            t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", m.group(1)).strip(" *#")
            if 2 < len(t) < 80 and t not in out:
                out.append(t)
        if len(out) >= n:
            break
    return out


async def probe_mode(mode, sites, outdir, results):
    print(f"== {mode} ==", flush=True)
    try:
        crawler = make_crawler(mode)
        await crawler.start()
    except Exception as e:                          # noqa: BLE001 - report, do not raise
        why = f"could not start: {type(e).__name__}: {e}"[:160]
        print("  " + why, flush=True)
        for key, *_ in sites:
            results[key][mode] = {"v": "error", "why": why}
        return
    try:
        for key, lab, url, words in sites:
            t0 = time.time()
            r = {}
            try:
                res = await crawler.arun(url=url, config=run_config(mode))
                html = res.html or ""
                md = str(res.markdown or "")
                st = res.status_code
                if st is None:
                    v, why = "error", (res.error_message or "no response").splitlines()[0][:160]
                else:
                    v, why = verdict(st, html, words)
                r = {"v": v, "why": why, "title": title_of(html),
                     "chars": len(visible_text(html)), "hits": prelaunch_hits(html),
                     "headings": headings(md), "final_url": res.redirected_url or url}
                with open(os.path.join(outdir, f"{key}.{mode}.md"), "w") as f:
                    f.write(md)
                with open(os.path.join(outdir, f"{key}.{mode}.html"), "w") as f:
                    f.write(html)
                if res.screenshot:
                    with open(os.path.join(outdir, f"{key}.{mode}.png"), "wb") as f:
                        f.write(base64.b64decode(res.screenshot))
            except Exception as e:                  # noqa: BLE001
                r = {"v": "error", "why": f"{type(e).__name__}: {e}"[:160]}
            r["secs"] = round(time.time() - t0, 1)
            results[key][mode] = r
            print(f"  {r['v']:8} {lab}: {r['why']} ({r['secs']}s)", flush=True)
            await asyncio.sleep(PAUSE)
    finally:
        try:
            await crawler.close()
        except Exception:                           # noqa: BLE001
            pass


def summary(results, modes, sites):
    mark = {"ok": "✅ read", "blocked": "⛔ blocked", "empty": "⚠️ empty", "error": "❌ error"}

    def cell(r):
        if not r:
            return "–"
        why = (r.get("why") or "").replace("|", "/").replace("<", "&lt;")
        return f"{mark.get(r['v'], r['v'])}<br><sub>{why}</sub>"

    lines = ["## Crawl4AI test: developer sites from GitHub Actions", "",
             "Each site was asked once per mode. **plain** repeats the 29 Oct test today; "
             "**stealth** and **undetected** are Crawl4AI's anti-bot options. "
             "Exsim and Sunway are controls and should read in every mode.", "",
             "| Site | 29 Oct | " + " | ".join(modes) + " |",
             "|---|---|" + "---|" * len(modes)]
    for key, lab, url, _ in sites:
        r = results[key]
        lines.append(f"| [{lab}]({url}) | {WAS.get(key, '')} | "
                     + " | ".join(cell(r.get(m)) for m in modes) + " |")
    lines += ["", "### What each readable site showed", ""]
    any_ok = False
    for key, lab, url, _ in sites:
        best = next((results[key][m] for m in modes
                     if results[key].get(m, {}).get("v") == "ok"), None)
        if not best:
            continue
        any_ok = True
        which = [m for m in modes if results[key].get(m, {}).get("v") == "ok"]
        lines.append(f"- **{lab}** (read by: {', '.join(which)}) -- title "
                     f"\"{best.get('title', '')}\", {best.get('chars', 0):,} characters, "
                     f"{best.get('hits', 0)} pre-launch words")
        if best.get("headings"):
            lines.append("  - headings: " + "; ".join(h.replace("|", "/") for h in best["headings"]))
    if not any_ok:
        lines.append("Nothing was readable in any mode.")
    lines += ["", "Saved text, HTML and screenshots are in the `crawl4ai-results` artifact."]
    return "\n".join(lines)


async def main_async(args):
    modes = [m for m in args.modes.split(",") if m in MODES]
    os.makedirs(args.out, exist_ok=True)
    results = {k: {"label": lab, "url": url} for k, lab, url, _ in SITES}
    for m in modes:
        await probe_mode(m, SITES, args.out, results)
    with open(os.path.join(args.out, "results.json"), "w") as f:
        json.dump(results, f, indent=2)
    text = summary(results, modes, SITES)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(text + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modes", default=",".join(MODES))
    ap.add_argument("--out", default="probe_c4")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
