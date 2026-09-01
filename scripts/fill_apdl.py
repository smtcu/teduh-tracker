#!/usr/bin/env python3
"""Fill the blank apdl dates in projects.csv from TEDUH.

  python3 scripts/fill_apdl.py [projects.csv] [--all] [--dry-run]

The advertising-permit start date is `permitMula` on the project detail endpoint.
Verified against two projects whose APDL was already recorded by hand: 31100-1
(Causewayz) returns 2025-11-05 and 31332-1 (Binastra Cochrane) returns
2026-07-02, both exactly matching projects.csv.

Only blank cells are filled, so this is cheap to re-run -- once every project has
a date it makes no requests at all. --all refetches every project instead, which
is only worth doing if you suspect a wrong date; an APDL does not change once
issued. --dry-run prints what it would write and touches nothing.

A project with several codes takes the earliest date across them, which is what
"earliest advertising-permit start" means for a project sold in phases.
"""
import csv, json, os, shutil, sys, time, urllib.error, urllib.request

API = "https://teduh.kpkt.gov.my/api/projek-swasta/{}"
PAUSE = 1.0          # same opening pace as scrape_teduh.py
MAX_PAUSE = 20.0
ATTEMPTS = 6
UA = "Mozilla/5.0 (compatible; teduh-tracker/1.0)"


def retry_after(err, fallback):
    """Honour Retry-After when TEDUH sends one, else back off geometrically."""
    try:
        v = err.headers.get("Retry-After")
        if v and v.strip().isdigit():
            return min(float(v.strip()), 120.0)
    except Exception:
        pass
    return fallback


def fetch(code, state):
    """Project detail as a dict, or None. Slows down when TEDUH pushes back."""
    wait = 2.0
    for attempt in range(ATTEMPTS):
        time.sleep(state["pause"])
        try:
            req = urllib.request.Request(API.format(code), headers={
                "User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=45) as r:
                body = json.loads(r.read().decode("utf-8"))
            # A clean run earns a little speed back, but never below the opening pace.
            state["pause"] = max(PAUSE, state["pause"] * 0.9)
            return body
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (429, 503):
                state["pause"] = min(MAX_PAUSE, state["pause"] * 1.8)
                nap = retry_after(e, wait)
                print(f"    {e.code} on {code} — waiting {nap:.0f}s "
                      f"(pace now {state['pause']:.1f}s)", flush=True)
                time.sleep(nap)
                wait = min(wait * 2, 60)
                continue
            print(f"    HTTP {e.code} on {code}", flush=True)
            return None
        except Exception as e:
            print(f"    {type(e).__name__} on {code} — retrying", flush=True)
            time.sleep(wait)
            wait = min(wait * 2, 60)
    return None


def permit_start(detail):
    """`permitMula` is the APDL start. Fall back to tarikh_mula if it is absent."""
    if not isinstance(detail, dict):
        return ""
    for key in ("permitMula", "tarikh_mula"):
        v = str(detail.get(key) or "").strip()
        if len(v) == 10 and v[4] == "-" and v[7] == "-":
            return v
    return ""


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    pcsv = args[0] if args else "projects.csv"
    refetch_all, dry = "--all" in flags, "--dry-run" in flags

    with open(pcsv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        cols = list(reader.fieldnames or [])
        rows = list(reader)
    if "apdl" not in cols:
        cols.append("apdl")
        for r in rows:
            r.setdefault("apdl", "")

    todo = [r for r in rows
            if (r.get("code") or "").strip()
            and (refetch_all or not (r.get("apdl") or "").strip())]
    if not todo:
        print("Every project with a code already has an APDL date. Nothing to fetch.")
        return

    codes = sorted({c.strip() for r in todo for c in r["code"].split(",") if c.strip()})
    print(f"{len(todo)} projects need a date, {len(codes)} codes to fetch.\n")

    state, found = {"pause": PAUSE}, {}
    # If TEDUH is down, every code burns its full retry ladder and the job runs
    # for hours to accomplish nothing. Twelve dead codes in a row is not bad
    # luck, so stop and keep whatever was collected before that point.
    STREAK = 12
    misses = 0
    for i, code in enumerate(codes, 1):
        d = permit_start(fetch(code, state))
        if d:
            found[code] = d
            misses = 0
        else:
            misses += 1
        print(f"  [{i}/{len(codes)}] {code:12} {d or '— no permit date'}", flush=True)
        if misses >= STREAK:
            print(f"\nStopping: {STREAK} codes in a row returned nothing, so TEDUH is "
                  f"probably unreachable rather than missing the dates. "
                  f"{len(found)} dates collected so far are still written; "
                  f"re-run later to pick up the rest.", flush=True)
            break

    filled, missing = 0, []
    for r in todo:
        dates = sorted(found[c.strip()] for c in r["code"].split(",")
                       if c.strip() in found)
        if dates:
            r["apdl"] = dates[0]       # earliest phase = the project's APDL
            filled += 1
        else:
            missing.append(f"{r.get('tracker_label') or r['tracker']} / {r['project']}")

    print(f"\nfilled {filled} of {len(todo)}")
    if missing:
        print(f"no permit date on TEDUH for {len(missing)}:")
        for m in missing[:20]:
            print("  " + m)

    if dry:
        print("\n--dry-run: projects.csv not written.")
        return
    if filled:
        shutil.copyfile(pcsv, pcsv + ".bak")
        with open(pcsv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {pcsv} (backup at {pcsv}.bak)")


if __name__ == "__main__":
    main()
