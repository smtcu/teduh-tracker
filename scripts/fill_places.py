#!/usr/bin/env python3
"""Keep data/project_places.csv: one state per tracked TEDUH code.

  python3 scripts/fill_places.py [--dry-run]

The site's state filter reads it. A code already in data/projects_index.csv (the
register snapshot) takes its state from there without a request. Any other code
is asked once on TEDUH (`projek.negeri`). A code TEDUH could not answer for is
left out of the file, so the next run asks again; "-" is never stored as a state.

This is where the PROJECT is, not where its developer's office is.
"""
import csv, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from fill_apdl import PAUSE, fetch

OUT = os.path.join(ROOT, "data", "project_places.csv")
COLS = ["code", "state", "source"]
BUDGET = 60     # requests per run: a catch-up is spread over days, never a long run

# TEDUH's spelling -> the one shown on the site.
SHOWN = {"wp kuala lumpur": "Kuala Lumpur", "wp putrajaya": "Putrajaya",
         "wp labuan": "Labuan", "pulau pinang": "Penang"}
STATES = ("Johor", "Kedah", "Kelantan", "Melaka", "Negeri Sembilan", "Pahang", "Perak",
          "Perlis", "Penang", "Selangor", "Terengganu", "Kuala Lumpur", "Putrajaya", "Labuan")


def clean_state(v):
    """TEDUH's state -> the site's spelling, or "" for anything that is not a state."""
    v = " ".join(str(v or "").split())
    v = SHOWN.get(v.lower(), v.title())
    return v if v in STATES else ""


def read(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    dry = "--dry-run" in sys.argv
    codes = sorted({c.strip() for p in read(os.path.join(ROOT, "projects.csv"))
                    for c in (p.get("code") or "").split(",") if c.strip()})
    have = {r["code"]: r for r in read(OUT) if clean_state(r.get("state"))}
    index = {r["kod_projek"]: clean_state(r.get("negeri"))
             for r in read(os.path.join(ROOT, "data", "projects_index.csv"))}

    before = dict(have)
    for c in codes:
        if c not in have and index.get(c):
            have[c] = {"code": c, "state": index[c], "source": "register"}
    ask = [c for c in codes if c not in have]
    print(f"{len(codes)} tracked codes, {len(have)} with a state, {len(ask)} to ask TEDUH.")
    state, misses = {"pause": PAUSE}, 0
    for c in ask[:BUDGET]:
        detail, reached = fetch(c, state)
        if not reached:
            misses += 1
            if misses >= 3:
                print("  TEDUH is not answering; the rest wait for the next run.")
                break
            continue
        misses = 0
        proj = detail.get("projek") if isinstance(detail, dict) else None
        got = clean_state((proj or {}).get("negeri"))
        print(f"  {c}: {got or 'no state given'}", flush=True)
        if got:
            have[c] = {"code": c, "state": got, "source": "teduh"}

    if dry or have == before:
        print("Nothing written.")
        return
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS, lineterminator="\n")
        w.writeheader()
        for c in sorted(have):
            w.writerow({k: have[c].get(k, "") for k in COLS})
    print(f"Wrote {len(have)} codes.")


if __name__ == "__main__":
    main()
