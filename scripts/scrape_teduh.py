#!/usr/bin/env python3
"""Weekly TEDUH sales scraper.

Reads projects.csv, calls the TEDUH unit API for each project code, counts how
many units have status == "sold", and appends one snapshot row per project to
data/teduh_history.csv (plus a per-unit-type breakdown in data/teduh_by_type.csv).

Runs on GitHub Actions — no browser and no local machine required.
"""
import csv, json, os, sys, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
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


# One shared pace for the whole scrape: PAUSE is the gap between the START of
# one request and the start of the next, whichever worker sends it.
#
# The scrape used to ask for one code, wait for the reply, pause a second and
# move on -- ~2.4s a code, ~33 minutes for 816 codes, most of it waiting on
# TEDUH's reply. Several workers now overlap that waiting, but TEDUH still
# sees one request every PAUSE seconds, never a burst.
#
# 1.1s (~0.9 requests a second) is deliberate. The 8 Oct 2026 test let four
# workers each pause one second on their own -- about 1.7 requests a second
# -- and TEDUH answered 429 within 45 seconds. The old pace (one every ~2.4s)
# has never been refused. 1.1s sits under the limit that test found and
# brings the scrape to ~16 minutes.
PAUSE = 1.1
MAX_PAUSE = 15.0
WORKERS = 4          # requests that may be waiting on TEDUH at once

_pace = threading.Lock()
_next_slot = 0.0     # monotonic time the next request may start
_hold_until = 0.0    # end of the current wait after a 429, shared by all


def wait_turn():
    """Block until this worker may send its request, keeping the shared pace."""
    global _next_slot
    with _pace:
        now = time.monotonic()
        start = max(now, _next_slot)
        _next_slot = start + PAUSE
    time.sleep(max(0.0, start - time.monotonic()))


def push_back(wait):
    """TEDUH refused: every worker waits, and the pace slows once per refusal.

    Requests already in flight when TEDUH starts refusing come back as 429
    together -- four of them on 8 Oct -- and each one used to raise the pace
    again, 1.5 x 1.5 x 1.5 x 1.5, leaving the rest of the run five times
    slower. Only the first refusal of a hold slows the pace now.
    """
    global PAUSE, _next_slot, _hold_until
    with _pace:
        now = time.monotonic()
        if now >= _hold_until:
            PAUSE = min(MAX_PAUSE, PAUSE * 1.5)
        _hold_until = max(_hold_until, now + wait)
        _next_slot = max(_next_slot, _hold_until)


def retry_after(e, fallback):
    """Seconds the server asked us to wait, if it said so."""
    try:
        v = e.headers.get("Retry-After")
        if v and str(v).strip().isdigit():
            return min(300, max(1, int(v)))
    except Exception:
        pass
    return fallback


def fetch(code, attempts=3):
    """GET the unit list for one project code, with retries and backoff.

    Every attempt takes its turn through wait_turn(), so retries keep the
    shared pace too. 429 means TEDUH is refusing because we are asking too
    fast -- usually because something else is also hitting the portal.
    Retrying at the same pace just gets refused again, so a refusal holds
    every worker for the wait TEDUH asked for and slows the rest of the run.

    A healthy TEDUH answers in under a second, so 30s is already generous.
    The old 7 attempts x 90s meant one dead code cost twelve minutes, and the
    16:00 run on 22 Sep 2026 spent an hour and a half timing out through the
    list before it was cancelled. Three attempts at 30s cap a dead code at
    about two minutes, and main() stops the whole scrape after three dead
    codes in a row.
    """
    last = None
    for i in range(attempts):
        wait_turn()
        try:
            req = Request(API.format(code=code), headers={"User-Agent": UA, "Accept": "application/json"})
            with urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except HTTPError as e:
            last = e
            if e.code in (429, 503):
                wait = retry_after(e, min(180, 20 * (i + 1)))
                push_back(wait)
                print(f"  {code}: {e.code}, all workers waiting {wait}s "
                      f"(pace now {PAUSE:.1f}s between requests)", file=sys.stderr, flush=True)
                continue
            time.sleep(5 * (i + 1))
        except (URLError, json.JSONDecodeError, TimeoutError, ValueError) as e:
            last = e
            time.sleep(5 * (i + 1))
    raise RuntimeError(f"{code}: failed after {attempts} attempts -> {last}")


def prefetch(codes):
    """Fetch and tally every code, WORKERS at a time.

    Returns (results, errors): code -> tally tuple, and code -> exception.
    fetch() keeps every worker on the one shared pace (wait_turn), and a
    429 holds and slows all of them together (push_back). The circuit breaker
    is kept: three codes in a row (in the order they finish) failing every
    retry means TEDUH itself is down, so the remaining codes are not asked
    for and the run exits without writing anything.
    """
    results, errors = {}, {}
    stop = threading.Event()

    def one(code):
        if stop.is_set():
            return code, None, None
        try:
            return code, tally(fetch(code)), None
        except Exception as e:
            return code, None, e

    dead_streak = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(one, c) for c in codes]
        for f in as_completed(futures):
            if f.cancelled():
                continue                    # never started: the breaker tripped
            code, res, err = f.result()
            if res is None and err is None:
                continue                    # skipped after the breaker tripped
            if err is not None:
                errors[code] = err
                print(f"FAIL  {code}: {err}", file=sys.stderr)
                dead_streak += 1
                if dead_streak >= 3 and not stop.is_set():
                    stop.set()
                    for other in futures:
                        other.cancel()
                    print("\nTEDUH looks down: three codes in a row failed "
                          "every attempt. Stopping the scrape here rather "
                          "than timing out through the rest of the list.\n"
                          "FAILURES so far:\n  "
                          + "\n  ".join(f"{c}: {e}" for c, e in errors.items()),
                          file=sys.stderr)
            else:
                results[code] = res
                dead_streak = 0
    if stop.is_set():
        sys.exit(3)   # nothing written; today's data left as it was
    return results, errors


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
    # Every code is fetched up front, WORKERS at a time (see prefetch()), so
    # the loop below only reads results. Each code is fetched once even when a
    # project is listed in two trackers (Johor + its developer tracker), so
    # both listings show identical figures. The circuit breaker -- three dead
    # codes in a row means TEDUH is down -- lives in prefetch(): it exits
    # before anything is written, because writing the handful of rows scraped
    # before an outage would REPLACE the morning snapshot with a rump. The
    # workflow's !cancelled() steps still rebuild the site and workbooks from
    # the existing CSVs, so nothing goes blank.
    wanted = []
    for p in projects:
        for c in (p.get("code") or "").split(","):
            if c.strip() and c.strip() not in wanted:
                wanted.append(c.strip())
    print(f"Fetching {len(wanted)} codes, one request every {PAUSE:.1f}s "
          f"across {WORKERS} workers.", flush=True)
    started = time.time()
    fetched, errors = prefetch(wanted)
    print(f"Fetched in {(time.time() - started) / 60:.1f} minutes "
          f"(pace at the end: {PAUSE:.1f}s between requests).\n", flush=True)

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
            if code not in fetched:
                failures.append(f"{code} ({p['project']}): {errors.get(code)}")
                failed = True
                continue
            nm, t, s_, g, units = fetched[code]
            name = name or nm
            total += t
            sold += s_
            groups += g
            all_units.append((code, units))
        if failed and not all_units:
            continue

        expected = int(p["total_units"]) if str(p.get("total_units", "")).strip().isdigit() else None
        flag = "" if expected in (None, total) else f"unit count on TEDUH is {total}, tracker says {expected}"

        # Block breakdown for the Remarks column, read straight off the unit
        # numbers -- unless block_groups.json says to report per phase instead.
        # Ferringhi's landed lots parse into twenty pseudo-blocks, so its note
        # is one figure per code: phase 1 and phase 2, named as she reports them.
        pc = UT.per_code(codes[0])
        if UT.suppressed(codes[0]):
            grouped, note = {}, ""
        elif pc:
            grouped = {}
            for code, units in all_units:
                nm_ = pc["names"].get(code, code)
                grouped[nm_] = grouped.get(nm_, 0) + sum(1 for _, s in units if s)
            note = UT.note_for(grouped, label=pc["label"])
        else:
            by_block = {}
            glued = []
            for _, units in all_units:
                for u, is_sold in units:
                    if not is_sold:
                        continue
                    b = UT.block_of(u)
                    if b:
                        by_block[b] = by_block.get(b, 0) + 1
                    elif UT.glued_block(u):
                        glued.append(UT.glued_block(u))
            # A typo like Desa Timur's "B39-13" counts only under a block the
            # project already has, so a single tower never gains one from it.
            for b in glued:
                if b in by_block:
                    by_block[b] += 1
            # PHASE/BLOCK prefixes (The Glades: HT5T4(I)/A) come off first so
            # a prefixed floor set is still recognisable as floors below.
            by_block = UT.strip_block_prefix(by_block)
            # FLOOR-UNIT-TYPE numbering (EcoWorld: GF-01-Ab) parses every
            # storey into a "block"; a floor-shaped set means a single tower,
            # which gets no note.
            if UT.is_floor_set(by_block):
                by_block = {}
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
