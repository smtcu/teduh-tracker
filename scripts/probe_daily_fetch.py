#!/usr/bin/env python3
"""One-off test: would the daily pre-launch watch be able to read these
developer sites? Uses watch_prelaunch.py's own Fetcher, links_of() and
listing_pages(), so the answer is exactly what the morning run would get:
the front page, then its project-list pages one level down.

  python scripts/probe_daily_fetch.py

A 200 answer can still be a bot wall, which the daily watch would take as a
page with no projects on it, so each page is also judged with
probe_sources.verdict(). Writes only the job summary; never data/, docs/ or
projects.csv, and it never commits.
"""
import os, sys, urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import watch_prelaunch as W                       # noqa: E402
from probe_sources import verdict, title_of, visible_text  # noqa: E402

_DEV = ["developer", "property", "project"]
SITES = [
    ("Maxim Global", "https://maximglobal.com.my/", "blocked -- laptop"),
    ("Armani: front page", "https://armanigroup.com.my/", "tried daily"),
    ("Mah Sing", "https://www.mahsing.com.my/", "ok (403 daily now)"),
    ("S P Setia", "https://spsetia.com/", "ok (403 daily now)"),
]


def judge(fetch, url, label):
    n = len(fetch.errors)
    page = fetch.get(url, label)
    if page is None:
        return None, "error", (fetch.errors[n:] or ["no response"])[0]
    v, why = verdict(200, page, _DEV)
    return page, v, why


def main():
    fetch = W.Fetcher(W.BUDGET)
    lines = ["## Would the daily watch read these sites?", "",
             "Same download code as the morning run (no browser).", "",
             "| Site | In sources now | Front page | Project-list pages | Project links found |",
             "|---|---|---|---|---|"]
    detail = []
    for label, url, now in SITES:
        page, v, why = judge(fetch, url, label)
        if page is None or v != "ok":
            lines.append(f"| [{label}]({url}) | {now} | ❌ {v}: {why} | – | – |")
            continue
        host = urllib.parse.urlsplit(url).netloc
        front = W.links_of(page, url)
        subs, links = [], [l for l in front if urllib.parse.urlsplit(l[0]).netloc == host]
        for lp in W.listing_pages(front, host):
            sp, sv, swhy = judge(fetch, lp, f"listing {label}")
            subs.append(f"{urllib.parse.urlsplit(lp).path} {'✅' if sv == 'ok' else '❌ ' + swhy}")
            if sp is not None and sv == "ok":
                links += [l for l in W.links_of(sp, lp) if urllib.parse.urlsplit(l[0]).netloc == host]
        seen, names = set(), []
        for link, anchor in links:
            name = (anchor or W.slug_words(link)).strip()
            if name and name.lower() not in seen and len(name) < 70:
                seen.add(name.lower())
                names.append(name)
        lines.append(f"| [{label}]({url}) | {now} | ✅ \"{title_of(page)[:50]}\", "
                     f"{len(visible_text(page)):,} chars | {'<br>'.join(subs) or 'none found'} "
                     f"| {len(links)} |")
        detail.append(f"- **{label}**: " + "; ".join(n.replace("|", "/") for n in names[:40]))
    text = "\n".join(lines + ["", "### Link names the watch would match against", ""] + detail)
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(text + "\n")


if __name__ == "__main__":
    main()
