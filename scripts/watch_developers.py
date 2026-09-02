#!/usr/bin/env python3
"""Notice when a tracked developer registers a new project on TEDUH.

  python3 scripts/watch_developers.py [--dry-run]

Every developer code (the part of a TEDUH code before the dash) found in
projects.csv is watched. Each run probes one code past the developer's highest
known phase -- new registrations always take the next -N under the same
developer code, which is exactly how MAIA arrived as 30141-2 and Binastra
Cochrane as 31332-1. A hit is recorded in data/teduh_watch.csv and shows up on
the website as a +1 badge on that developer's tracker button for a few days
(BADGE_DAYS in build_dashboard.py). Nothing is emailed and no tracker changes:
adding the project to projects.csv stays a decision, not an automation.

Two further cases ride along:

- A find with no permit yet (registered but not licensed -- Ukay Spring sat
  like this for months as 8763-2) is re-checked every run, and badges again
  the day its permit is issued.
- data/teduh_watch_extra.csv lists things to watch that projects.csv cannot
  imply: a dormant code (`8763-2`) to watch for a permit, or a bare developer
  code to watch for new phases. Columns: value,label,trackers -- trackers is a
  semicolon list of tracker keys whose button should carry the badge.

Known phases come from projects.csv, data/projects_index.csv (the full-register
snapshot) and the watch file itself, so nothing is probed twice. The network
manners -- pacing, Retry-After, backoff -- are imported from fill_apdl.py so
the two stay identical. Errors never fail the run: a missed probe is caught on
the next morning's run.
"""
import csv, os, sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fill_apdl import PAUSE, fetch, permit_start

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WATCH = os.path.join(ROOT, "data", "teduh_watch.csv")
EXTRA = os.path.join(ROOT, "data", "teduh_watch_extra.csv")
INDEX = os.path.join(ROOT, "data", "projects_index.csv")
FIELDS = ["first_seen", "kind", "kod_projek", "kod_pemaju", "nama", "pemaju",
          "units", "permit_mula", "trackers", "label"]
MAX_NEW_PER_DEV = 3        # cap the walk upward, in case a developer lands several at once


def read(path):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def split_code(code):
    """'8763-2' -> ('8763', 2); None for anything shaped differently."""
    code = (code or "").strip()
    if "-" not in code:
        return None
    kod, _, phase = code.rpartition("-")
    if kod.isdigit() and phase.isdigit():
        return kod, int(phase)
    return None


def detail_row(code, detail):
    kod, _, _ = code.rpartition("-")
    p = detail.get("projek") or {}
    pm = detail.get("pemaju") or {}
    return {
        "kod_projek": code,
        "kod_pemaju": kod,
        "nama": (detail.get("nama") or "").strip(),
        "pemaju": (pm.get("nama") or "").strip(),
        "units": (detail.get("unitSummary") or {}).get("unit") or "",
        "permit_mula": permit_start(detail) or "",
    }


def main():
    dry = "--dry-run" in sys.argv
    today = date.today().isoformat()
    projects = read(os.path.join(ROOT, "projects.csv"))
    state = read(WATCH)
    extra = read(EXTRA)

    # --- who is watched, and which tracker buttons carry their badge ---
    dev_trackers, dev_label = {}, {}
    tracked_codes = set()
    for p in projects:
        for c in (p.get("code") or "").split(","):
            sp = split_code(c)
            if not sp:
                continue
            tracked_codes.add(c.strip())
            kod = sp[0]
            dev_trackers.setdefault(kod, set()).add((p.get("tracker") or "").strip())
            dev_label.setdefault(kod, (p.get("developer") or "").strip())
    for x in extra:
        v = (x.get("value") or "").strip()
        trackers = {t.strip() for t in (x.get("trackers") or "").split(";") if t.strip()}
        kod = v.split("-")[0] if "-" in v else v
        if kod.isdigit():
            dev_trackers.setdefault(kod, set()).update(trackers)
            dev_label.setdefault(kod, (x.get("label") or "").strip())

    # --- highest phase already known per developer code ---
    known = {}
    def learn(code):
        sp = split_code(code)
        if sp and sp[0] in dev_trackers:
            known[sp[0]] = max(known.get(sp[0], 0), sp[1])
    for c in tracked_codes:
        learn(c)
    for r in read(INDEX):
        learn(r.get("kod_projek"))
    seen_codes = {r["kod_projek"] for r in state}
    for r in state:
        learn(r["kod_projek"])
    for x in extra:
        learn(x.get("value"))

    net = {"pause": PAUSE}
    finds, updated, unreachable = [], 0, 0

    # --- 1. walk one past each developer's highest known phase ---
    for kod in sorted(dev_trackers, key=int):
        phase = known.get(kod, 0)
        for _ in range(MAX_NEW_PER_DEV):
            code = f"{kod}-{phase + 1}"
            detail, reached = fetch(code, net)
            if not reached:
                unreachable += 1
                break                      # do not mistake an outage for "no more phases"
            if detail is None:
                break
            row = detail_row(code, detail)
            row.update(first_seen=today,
                       kind="new-phase" if row["permit_mula"] else "registered",
                       trackers=";".join(sorted(t for t in dev_trackers[kod] if t)),
                       label=dev_label.get(kod, ""))
            finds.append(row)
            phase += 1

    # --- 2. re-check anything known but still unlicensed ---
    pending = [x for x in extra if split_code(x.get("value"))
               and (x.get("value") or "").strip() not in seen_codes]
    for x in pending:
        v = x["value"].strip()
        detail, reached = fetch(v, net)
        if not reached or detail is None:
            continue
        row = detail_row(v, detail)
        row.update(first_seen=today if row["permit_mula"] else "",
                   kind="permit-issued" if row["permit_mula"] else "permit-pending",
                   trackers=(x.get("trackers") or "").replace(",", ";"),
                   label=(x.get("label") or "").strip())
        finds.append(row)
    for r in state:
        if r.get("permit_mula") or r["kod_projek"] in {f["kod_projek"] for f in finds}:
            continue
        detail, reached = fetch(r["kod_projek"], net)
        if not reached or detail is None:
            continue
        fresh = detail_row(r["kod_projek"], detail)
        if fresh["permit_mula"]:
            r.update(permit_mula=fresh["permit_mula"], units=fresh["units"] or r.get("units", ""),
                     first_seen=today, kind="permit-issued")
            updated += 1

    rows = state + [f for f in finds if f["kod_projek"] not in seen_codes]
    rows.sort(key=lambda r: (r.get("first_seen") or "", r["kod_projek"]), reverse=True)

    for f in finds:
        print("FOUND %-10s %-36s | %-30s | units=%-6s permit=%s"
              % (f["kod_projek"], f["nama"][:36], f["pemaju"][:30],
                 f["units"], f["permit_mula"] or "-"))
    print("watched %d developer codes | %d new, %d permit updates, %d unreachable"
          % (len(dev_trackers), len([f for f in finds if f["kod_projek"] not in seen_codes]),
             updated, unreachable))

    if dry:
        print("--dry-run: nothing written")
        return
    os.makedirs(os.path.dirname(WATCH), exist_ok=True)
    with open(WATCH, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})
    print("wrote", os.path.relpath(WATCH, ROOT), f"({len(rows)} rows)")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:                            # noqa: BLE001
        # A watch that fails must never take the day's scrape down with it.
        print(f"watch_developers: giving up quietly ({e})")
