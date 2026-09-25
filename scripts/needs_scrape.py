#!/usr/bin/env python3
"""Decide whether a projects.csv change needs a TEDUH scrape or just a rebuild.

  python3 scripts/needs_scrape.py OLD.csv NEW.csv

Prints one word on the first line -- "scrape" or "build" -- followed by the
reason, and always exits 0 so the workflow step can never fail on it.

A push that only touches text (project name, remarks, note_prefix, tracker
label, pin, row order, APDL) changes nothing the scraper produces, so the
site can be rebuilt from this morning's data in a couple of minutes instead
of spending 40 minutes re-fetching every code. Anything the scraper reads is
what decides: the code itself, which tracker the row files under (the daily
rows carry it), total_units (the unit-count flag is computed at scrape time)
and unit_types (the block-note and unit-type classification). Removing a row
is fine -- stale daily rows for a code nobody lists are ignored. Adding a
row with a blank code is fine too: the scraper skips those.
"""
import csv, sys

WATCHED = ("tracker", "code", "total_units", "unit_types")


def signature(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        if not (r.get("code") or "").strip():
            continue
        out.append(tuple((r.get(k) or "").strip() for k in WATCHED))
    return out


def main():
    old, new = sys.argv[1], sys.argv[2]
    try:
        before = signature(old)
    except Exception as e:                       # no old file -> play safe
        print("scrape"); print(f"no previous projects.csv to compare ({e})")
        return
    after = signature(new)
    remaining = list(before)
    added = []
    for sig in after:
        if sig in remaining:
            remaining.remove(sig)
        else:
            added.append(sig)
    if added:
        print("scrape")
        for t, c, u, k in added[:10]:
            print(f"new or changed scraper input: {t} {c} units={u!r} unit_types={k!r}")
        return
    print("build")
    print(f"{len(remaining)} coded row(s) removed, none added or changed; "
          "rebuilding from the existing data")


if __name__ == "__main__":
    main()
