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
    """(detail, reached). `reached` is False only when TEDUH could not be talked to.

    The two are kept apart on purpose. "I asked and this project has no permit
    date" and "I could not ask" look identical from the caller otherwise, and
    conflating them is what made the first run stop after twelve codes.
    """
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
            return body, True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None, True          # answered clearly: no such project
            if e.code in (429, 503):
                state["pause"] = min(MAX_PAUSE, state["pause"] * 1.8)
                nap = retry_after(e, wait)
                print(f"    {e.code} on {code} — waiting {nap:.0f}s "
                      f"(pace now {state['pause']:.1f}s)", flush=True)
                time.sleep(nap)
                wait = min(wait * 2, 60)
                continue
            print(f"    HTTP {e.code} on {code}", flush=True)
            return None, True
        except Exception as e:
            print(f"    {type(e).__name__} on {code} — retrying", flush=True)
            time.sleep(wait)
            wait = min(wait * 2, 60)
    return None, False


MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def iso(v):
    """Accept "2023-05-08" or "08 May 2023" (the form lesen_records uses) -> ISO, else ""."""
    v = str(v or "").strip()
    if len(v) == 10 and v[4] == "-" and v[7] == "-":
        return v
    parts = v.split()
    if len(parts) == 3 and parts[0].isdigit() and parts[2].isdigit():
        m = MONTHS.get(parts[1][:3].lower())
        if m:
            return f"{int(parts[2]):04d}-{m:02d}-{int(parts[0]):02d}"
    return ""


def permit_start(detail):
    """The EARLIEST advertising-permit start, or "".

    TEDUH's "Senarai Permit Terdahulu" is the `lesen_records` array, and the
    current permit is root.projek.permitMula. A permit runs about three years
    and is then renewed, and the renewal replaces permitMula -- so on its own
    permitMula gives 2026-05-08 for Vista Adesa, which launched in May 2023.
    The original sits in lesen_records as "08 May 2023". APDL means the first
    permit, so this takes the earliest date across all of them.

    tarikh_mula is deliberately ignored: that is the developer's licence, a
    different thing, and for 30363-1 it is 2023-02-13 -- three months before
    the advertising permit.
    """
    if not isinstance(detail, dict):
        return ""
    found = []
    projek = detail.get("projek") if isinstance(detail.get("projek"), dict) else {}
    for src in (projek, detail):
        found.append(iso(src.get("permitMula")))
    for rec in detail.get("lesen_records") or []:
        if isinstance(rec, dict):
            found.append(iso(rec.get("mula")))
    found = [d for d in found if d]
    return min(found) if found else ""


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
    if refetch_all:
        print("Checking EVERY project's APDL against the earliest permit on TEDUH."
              + ("  (dry run: nothing will be written)" if dry else ""))

    codes = sorted({c.strip() for r in todo for c in r["code"].split(",") if c.strip()})
    print(f"{len(todo)} projects need a date, {len(codes)} codes to fetch.\n")

    state, found = {"pause": PAUSE}, {}
    # If TEDUH is down, every code burns its full retry ladder and the job runs
    # for hours to accomplish nothing. Twelve dead codes in a row is not bad
    # luck, so stop and keep whatever was collected before that point.
    STREAK = 12
    unreachable = 0
    for i, code in enumerate(codes, 1):
        detail, reached = fetch(code, state)
        d = permit_start(detail)
        if d:
            found[code] = d
        # Only a failure to reach TEDUH counts towards stopping. A project that
        # genuinely has no permit date is an answer, not an outage.
        unreachable = 0 if reached else unreachable + 1
        print(f"  [{i}/{len(codes)}] {code:12} {d or '— no permit date'}", flush=True)
        if unreachable >= STREAK:
            print(f"\nStopping: {STREAK} codes in a row could not be reached at all, so "
                  f"TEDUH is down rather than missing the dates. "
                  f"{len(found)} dates collected so far are still written; "
                  f"re-run later to pick up the rest.", flush=True)
            break

    filled, missing, same, differ = 0, [], 0, []
    for r in todo:
        dates = sorted(found[c.strip()] for c in r["code"].split(",")
                       if c.strip() in found)
        label = f"{r.get('tracker_label') or r['tracker']} / {r['project']}"
        if not dates:
            missing.append(label)
            continue
        earliest = dates[0]            # earliest phase = the project's APDL
        current = (r.get("apdl") or "").strip()
        if current and current != earliest:
            differ.append((label, current, earliest))
        elif current:
            same += 1
        if not current or refetch_all:
            if r["apdl"] != earliest:
                filled += 1
            r["apdl"] = earliest

    if refetch_all:
        print(f"\n{same} projects already carry the earliest permit date.")
        if differ:
            print(f"{len(differ)} projects where projects.csv differs from the earliest permit on TEDUH:")
            print(f"  {'project':44} {'in projects.csv':>16} {'earliest on TEDUH':>18}")
            for label, cur, ear in differ:
                tag = "  (yours is EARLIER)" if cur < ear else ""
                print(f"  {label[:44]:44} {cur:>16} {ear:>18}{tag}")
        else:
            print("No differences.")
    else:
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
