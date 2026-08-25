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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import unit_types as UT
MYT = timezone(timedelta(hours=8))          # Malaysia / Singapore time
NOW = datetime.now(MYT)
TODAY = NOW.strftime("%Y-%m-%d")
IS_FRIDAY = NOW.weekday() == 4              # the weekly Excel snapshot lands on Friday


PAUSE = 1.0          # seconds between projects; raised when TEDUH pushes back


def retry_after(e, fallback):
    """Seconds the server asked us to wait, if it said so."""
    try:
        v = e.headers.get("Retry-After")
        if v and str(v).strip().isdigit():
            return min(300, max(1, int(v)))
    except Exception:
        pass
    return fallback


def fetch(code, attempts=7):
    """GET the unit list for one project code, with retries and backoff.

    429 means TEDUH is refusing because we are asking too fast -- usually
    because something else is also hitting the portal. Retrying at the same
    pace just gets refused again, so a refusal waits properly and slows every
    later request in this run as well.
    """
    global PAUSE
    last = None
    for i in range(attempts):
        try:
            req = Request(API.format(code=code), headers={"User-Agent": UA, "Accept": "application/json"})
            with urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode("utf-8"))
        except HTTPError as e:
            last = e
            if e.code in (429, 503):
                wait = retry_after(e, min(180, 20 * (i + 1)))
                PAUSE = min(15.0, PAUSE * 1.5)
                print(f"  {code}: {e.code}, waiting {wait}s "
                      f"(pace now {PAUSE:.1f}s between projects)", file=sys.stderr, flush=True)
                time.sleep(wait)
                continue
            time.sleep(5 * (i + 1))
        except (URLError, json.JSONDecodeError, TimeoutError, ValueError) as e:
            last = e
            time.sleep(5 * (i + 1))
    raise RuntimeError(f"{code}: failed after {attempts} attempts -> {last}")


def tally(payload):
    """Return (name, total, sold, [(unit_type, total, sold), ...], [(unit_no, is_sold), ...])."""
    total = sold = 0
    groups, units_flat = [], []
    for g in payload.get("unitGroups", []):
        units = g.get("units", [])
        t = len(units)
        s = sum(1 for u in units if u.get("status") == "sold")
        total += t
        sold += s
        groups.append((g.get("jenis", ""), t, s))
        for u in units:
            units_flat.append((u.get("no", ""), u.get("status") == "sold"))
    return payload.get("namaPemajuan", ""), total, sold, groups, units_flat


def main():
    projects = list(csv.DictReader(open(os.path.join(ROOT, "projects.csv"), encoding="utf-8")))
    daily_path = os.path.join(ROOT, "data", "teduh_daily.csv")
    hist_path = os.path.join(ROOT, "data", "teduh_history.csv")
    type_path = os.path.join(ROOT, "data", "teduh_by_type.csv")

    hist_rows, type_rows, failures = [], [], []
    unit_rows, byunit_rows = [], []

    for p in projects:
        codes = [c.strip() for c in (p.get("code") or "").split(",") if c.strip()]
        if not codes:
            print(f"SKIP  {p['project']}: no project code")
            continue

        name = ""
        total = sold = 0
        groups = []
        all_units = []
        failed = False
        for code in codes:
            time.sleep(PAUSE)          # gentle by default, slower if TEDUH pushes back
            try:
                nm, t, s_, g, units = tally(fetch(code))
            except Exception as e:
                failures.append(f"{code} ({p['project']}): {e}")
                print(f"FAIL  {code}: {e}", file=sys.stderr)
                failed = True
                continue
            name = name or nm
            total += t
            sold += s_
            groups += g
            all_units.append((code, units))
        if failed and not all_units:
            continue

        expected = int(p["total_units"]) if str(p.get("total_units", "")).strip().isdigit() else None
        flag = "" if expected in (None, total) else f"unit count on TEDUH is {total}, tracker says {expected}"

        # Block breakdown for the Remarks column, read straight off the unit numbers.
        by_block = {}
        for _, units in all_units:
            for u, is_sold in units:
                if not is_sold:
                    continue
                b = UT.block_of(u)
                if b:
                    by_block[b] = by_block.get(b, 0) + 1
        grouped, label = UT.regroup(by_block, codes[0])
        note = UT.note_for(grouped, label=label)
        if note and sum(grouped.values()) != sold:
            print(f"WARN {p['project']}: block note sums to {sum(grouped.values())}, "
                  f"total sold is {sold}")

        hist_rows.append(dict(tracker=p["tracker"], seq="", week=TODAY, code=codes[0],
                              total_sold=sold, total_units=total, teduh_name=name,
                              note=flag, block_note=note))
        for i, (jenis, t, s_) in enumerate(groups):
            type_rows.append(dict(week=TODAY, tracker=p["tracker"], code=codes[0], group_idx=i,
                                  unit_type=jenis, units=t, sold=s_))

        # Unit-type classification, for the projects that have rules configured.
        keys = [k.strip() for k in (p.get("unit_types") or "").split(",") if k.strip()]
        for key, (code, units) in zip(keys, all_units):
            st, tt, sb, unmatched = UT.tally(key, units)
            for t_key in st:
                unit_rows.append(dict(week=TODAY, project_key=key, tracker=p["tracker"],
                                      project=p["project"], unit_type=t_key,
                                      sold=st[t_key], seen=tt.get(t_key, 0)))
            for u, is_sold in units:
                byunit_rows.append(dict(week=TODAY, project_key=key, unit=u,
                                        block=UT.block_of(u) or "",
                                        unit_type=UT.classify(key, u) or "",
                                        sold=1 if is_sold else 0))
            if unmatched:
                print(f"  {key}: {len(unmatched)} units matched no type rule, e.g. {unmatched[:3]}")

        print(f"OK    {'+'.join(codes):<22} {p['project'][:30]:<30} sold {sold}/{total}"
              + (f"  [{flag}]" if flag else ""))

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

    HIST_FIELDS = ["tracker", "seq", "week", "code", "total_sold", "total_units",
                   "teduh_name", "note", "block_note"]
    TYPE_FIELDS = ["week", "tracker", "code", "group_idx", "unit_type", "units", "sold"]
    UNIT_FIELDS = ["week", "project_key", "tracker", "project", "unit_type", "sold", "seen"]
    BYUNIT_FIELDS = ["week", "project_key", "unit", "block", "unit_type", "sold"]

    # Daily series drives the website; it gets a row every run.
    append(daily_path, hist_rows, HIST_FIELDS)
    append(type_path, type_rows, TYPE_FIELDS)
    if unit_rows:
        append(os.path.join(ROOT, "data", "teduh_unit_types.csv"), unit_rows, UNIT_FIELDS)
        append(os.path.join(ROOT, "data", "teduh_units.csv"), byunit_rows, BYUNIT_FIELDS)

    # Weekly series drives the Excel trackers; only Fridays go in, so the
    # spreadsheet keeps one column per week exactly as it always has.
    if IS_FRIDAY:
        append(hist_path, hist_rows, HIST_FIELDS)
        if unit_rows:
            append(os.path.join(ROOT, "data", "teduh_unit_types_weekly.csv"), unit_rows, UNIT_FIELDS)
        print(f"\nFriday: appended {len(hist_rows)} rows to the weekly tracker history.")
    else:
        print(f"\nNot Friday: daily series updated, weekly tracker history left alone.")
    print(f"Scraped {len(hist_rows)} projects for {TODAY}.")

    if failures:
        print("\nFAILURES:\n  " + "\n  ".join(failures), file=sys.stderr)
        sys.exit(2)   # data still committed; the run is marked failed so you get an email


if __name__ == "__main__":
    main()
