#!/usr/bin/env python3
"""Weekly TEDUH sales scraper.

Reads projects.csv, calls the TEDUH unit API for each project code, counts how
many units have status == "sold", and appends one snapshot row per project to
data/teduh_history.csv (plus a per-unit-type breakdown in data/teduh_by_type.csv).

Runs on GitHub Actions — no browser and no local machine required.
"""
import csv, json, os, sys, time
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

API = "https://teduh.kpkt.gov.my/api/unit-projek-swasta/{code}"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MYT = timezone(timedelta(hours=8))          # Malaysia / Singapore time
NOW = datetime.now(MYT)
TODAY = NOW.strftime("%Y-%m-%d")
IS_FRIDAY = NOW.weekday() == 4              # the weekly Excel snapshot lands on Friday


def fetch(code, attempts=4):
    """GET the unit list for one project code, with retries and backoff."""
    last = None
    for i in range(attempts):
        try:
            req = Request(API.format(code=code), headers={"User-Agent": UA, "Accept": "application/json"})
            with urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode("utf-8"))
        except (URLError, HTTPError, json.JSONDecodeError, TimeoutError) as e:
            last = e
            time.sleep(5 * (i + 1))
    raise RuntimeError(f"{code}: failed after {attempts} attempts -> {last}")


def tally(payload):
    """Return (name, total, sold, [(unit_type, total, sold), ...])."""
    total = sold = 0
    groups = []
    for g in payload.get("unitGroups", []):
        units = g.get("units", [])
        t = len(units)
        s = sum(1 for u in units if u.get("status") == "sold")
        total += t
        sold += s
        groups.append((g.get("jenis", ""), t, s))
    return payload.get("namaPemajuan", ""), total, sold, groups


def main():
    projects = list(csv.DictReader(open(os.path.join(ROOT, "projects.csv"), encoding="utf-8")))
    daily_path = os.path.join(ROOT, "data", "teduh_daily.csv")
    hist_path = os.path.join(ROOT, "data", "teduh_history.csv")
    type_path = os.path.join(ROOT, "data", "teduh_by_type.csv")

    hist_rows, type_rows, failures = [], [], []
    for p in projects:
        code = (p.get("code") or "").strip()
        if not code:                              # project with no TEDUH code yet
            print(f"SKIP  {p['project']}: no project code")
            continue
        try:
            name, total, sold, groups = tally(fetch(code))
        except Exception as e:
            failures.append(f"{code} ({p['project']}): {e}")
            print(f"FAIL  {code}: {e}", file=sys.stderr)
            continue

        expected = int(p["total_units"]) if str(p.get("total_units", "")).strip().isdigit() else None
        flag = "" if expected in (None, total) else f"unit count changed: tracker={expected} teduh={total}"
        hist_rows.append(dict(tracker=p["tracker"], seq="", week=TODAY, code=code,
                              total_sold=sold, total_units=total, teduh_name=name, note=flag))
        for i, (jenis, t, s) in enumerate(groups):
            type_rows.append(dict(week=TODAY, tracker=p["tracker"], code=code, group_idx=i,
                                  unit_type=jenis, units=t, sold=s))
        print(f"OK    {code:<10} {name[:38]:<38} sold {sold}/{total}" + (f"  [{flag}]" if flag else ""))

    if not hist_rows:
        print("No rows scraped — leaving history untouched.", file=sys.stderr)
        sys.exit(1)

    def append(path, rows, fields):
        """Write today's snapshot, replacing anything already recorded for today.

        Re-running the workflow on the same day used to be skipped outright, which
        meant a project added mid-day never got its first reading until tomorrow.
        Rewriting today's rows instead makes a re-run always pick up the current
        project list, while still keeping exactly one snapshot per day.
        """
        existing = []
        if os.path.exists(path) and os.path.getsize(path) > 0:
            with open(path, newline="", encoding="utf-8") as f:
                existing = [r for r in csv.DictReader(f) if r.get("week") != TODAY]
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for r in existing:
                w.writerow({k: r.get(k, "") for k in fields})
            w.writerows(rows)
        print(f"  {os.path.basename(path)}: wrote {len(rows)} rows for {TODAY}")
        return True

    HIST_FIELDS = ["tracker", "seq", "week", "code", "total_sold", "total_units", "teduh_name", "note"]
    TYPE_FIELDS = ["week", "tracker", "code", "group_idx", "unit_type", "units", "sold"]

    # Daily series drives the website; it gets a row every run.
    append(daily_path, hist_rows, HIST_FIELDS)
    append(type_path, type_rows, TYPE_FIELDS)

    # Weekly series drives the Excel trackers; only Fridays go in, so the
    # spreadsheet keeps one column per week exactly as it always has.
    if IS_FRIDAY:
        append(hist_path, hist_rows, HIST_FIELDS)
        print(f"\nFriday: appended {len(hist_rows)} rows to the weekly tracker history.")
    else:
        print(f"\nNot Friday: daily series updated, weekly tracker history left alone.")
    print(f"Scraped {len(hist_rows)} projects for {TODAY}.")

    if failures:
        print("\nFAILURES:\n  " + "\n  ".join(failures), file=sys.stderr)
        sys.exit(2)   # data still committed; the run is marked failed so you get an email


if __name__ == "__main__":
    main()
