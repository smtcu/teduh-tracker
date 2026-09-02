#!/usr/bin/env python3
"""Fast pre-flight check for the TEDUH pipeline. No network, no writes.

Why this exists: on 25 Aug 2026 unit_types.py was replaced by a hand-pasted copy
that no longer had regroup(). Nothing complained until the scraper reached its
first project and died with AttributeError, so the failure surfaced a whole run
later than the edit that caused it. Importing a module is not enough to catch
that -- the missing name is only touched deep inside main() -- so this asserts
the cross-module contract directly and checks a handful of behaviours the repo
has regressed on before.

Run it locally the same way CI does:

    python scripts/selftest.py
"""
import csv, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

FAILS = []


def ck(ok, msg):
    print(("  ok   " if ok else "  FAIL ") + msg)
    if not ok:
        FAILS.append(msg)


def section(t):
    print("\n" + t)


# --------------------------------------------------------------------------
section("modules import cleanly")
# --------------------------------------------------------------------------
mods = {}
for name in ["unit_types", "scrape_teduh", "build_dashboard", "build_trackers",
             "build_daily_xlsx", "build_pdf", "build_unit_workbook", "weekly_summary",
             "fill_apdl", "watch_developers"]:
    try:
        mods[name] = __import__(name)
        ck(True, name)
    except Exception as e:                      # noqa: BLE001 - report, do not raise
        ck(False, f"{name}: {type(e).__name__}: {e}")

UT = mods.get("unit_types")
if UT is None:
    print("\nunit_types failed to import; nothing further can be checked.")
    sys.exit(1)

# --------------------------------------------------------------------------
section("cross-module API: names one script calls on another")
# --------------------------------------------------------------------------
# scrape_teduh.py calls all of these. A hand-pasted unit_types.py that drops any
# of them fails here in seconds instead of part-way through a live scrape.
have = {}
for fn in ["block_of", "regroup", "note_for", "classify", "tally", "block_groups", "config"]:
    have[fn] = callable(getattr(UT, fn, None))
    ck(have[fn], f"unit_types.{fn}() exists")

if have["note_for"]:
    import inspect
    params = inspect.signature(UT.note_for).parameters
    ck("label" in params, "note_for() takes label= (Parkland needs '' to read 'Phase 1')")
    ck("unit_word" in params, "note_for() takes unit_word= (her report says '187 units')")

# --------------------------------------------------------------------------
section("block_of(): three segments required, integers not required")
# --------------------------------------------------------------------------
# Both halves of this have caused real bugs. Requiring integers silently dropped
# 11 sold units from Binastra's note; not requiring three segments would give
# single-tower projects a bogus note built from floor numbers.
if not have["block_of"]:
    ck(False, "block_of() missing - skipping its checks")
else:
    for u in ["9-1", "10-3A", "12-01", "7-12"]:
        ck(UT.block_of(u) is None, f"{u!r} is FLOOR-UNIT -> None")
    for u, want in [("A-08-03", "A"), ("A-08-03A", "A"), ("1A-07-01", "1A"),
                    ("D1-12-01", "D1"), ("A- 01-02", "A")]:
        ck(UT.block_of(u) == want, f"{u!r} -> {want!r}")

# --------------------------------------------------------------------------
section("regroup(): roll-ups never change the arithmetic")
# --------------------------------------------------------------------------
# Guarded rather than assumed: when regroup() went missing the point was to get a
# readable list of what broke, not a traceback that hides every later check.
if not (have["regroup"] and have["note_for"]):
    ck(False, "regroup()/note_for() missing - skipping their checks")
else:
    park = {"1A": 327, "1B": 340, "2A": 215, "2B": 176}
    g, lab = UT.regroup(park, "30635-1")
    ck(sum(g.values()) == sum(park.values()), f"Parkland sum preserved ({sum(g.values())})")
    ck(set(g) == {"Phase 1", "Phase 2"}, f"Parkland grouped into phases -> {sorted(g)}")
    ck(lab == "", "Parkland label is '' so it reads 'Phase 1', not 'Block Phase 1'")

    cw = {"A": 449, "B1": 231, "B2": 285, "D1": 168, "D2": 288}
    g2, _ = UT.regroup(cw, "31100-1")
    ck(sum(g2.values()) == sum(cw.values()), f"Causewayz sum preserved ({sum(g2.values())})")
    ck(set(g2) == {"A", "B", "D"}, f"Causewayz grouped -> {sorted(g2)}")

    g3, lab3 = UT.regroup({"A": 5, "B": 6}, "835-14")
    ck(g3 == {"A": 5, "B": 6} and lab3 == "Block ", "ungrouped project passes through untouched")

    g4, _ = UT.regroup({"1A": 10, "9Z": 5}, "30635-1")
    ck(g4.get("9Z") == 5, "a block missing from the map keeps its own name")

    ck(UT.note_for({"A": 2}) == "Latest sales - Block A: 2 units",
       f"note wording -> {UT.note_for({'A': 2})!r}")
    ck(UT.note_for({}) == "" and UT.note_for({UT.OTHER: 3}) == "",
       "no blocks -> empty note (correct for a single tower)")

# --------------------------------------------------------------------------
section("config files parse and agree with each other")
# --------------------------------------------------------------------------
try:
    with open(os.path.join(ROOT, "projects.csv"), encoding="utf-8") as f:
        projects = list(csv.DictReader(f))
    ck(bool(projects), f"projects.csv parses ({len(projects)} rows)")
except Exception as e:                          # noqa: BLE001
    ck(False, f"projects.csv: {e}")
    projects = []

expected_cols = {"tracker", "project", "code", "total_units", "remarks", "note_prefix",
                 "unit_types", "apdl"}
if projects:
    missing = expected_cols - set(projects[0])
    ck(not missing, f"projects.csv has the columns the scripts read{'' if not missing else f' (missing {missing})'}")
    bad = [p["project"] for p in projects
           if str(p.get("total_units", "")).strip() and not str(p["total_units"]).strip().isdigit()]
    ck(not bad, f"total_units is numeric everywhere{'' if not bad else f' (bad: {bad})'}")

# The stale-remark rule: a remark the data has outgrown stops printing, and the
# two copies of the rule (website, Excel) must answer identically. Whole-remark
# match only -- a longer remark merely containing the phrase is left alone.
BD, BT = mods.get("build_dashboard"), mods.get("build_trackers")
if BD and BT and hasattr(BD, "stale_remark") and hasattr(BT, "stale_remark"):
    cases = [
        ({"remarks": "Not yet launched", "code": "1-1"}, 5, ""),
        ({"remarks": "Not yet launched", "code": "1-1"}, 0, "Not yet launched"),
        ({"remarks": "Not yet launched", "code": ""}, 5, "Not yet launched"),
        ({"remarks": "No TEDUH code", "code": "1-1"}, None, ""),
        ({"remarks": "No TEDUH code", "code": ""}, None, "No TEDUH code"),
        ({"remarks": "Big unit (not yet launched wing)", "code": "1-1"}, 5,
         "Big unit (not yet launched wing)"),
    ]
    for proj, sold, want in cases:
        a, b = BD.remark_for(proj, "", sold), BT.remark_for(proj, "", sold)
        ck(a == want and b == want,
           f"stale remark: {proj['remarks']!r} sold={sold} code={'yes' if proj['code'] else 'no'} -> {want!r}")
else:
    ck(False, "stale_remark exists in both build_dashboard and build_trackers")

for fname in ["unit_types.json", "block_groups.json"]:
    path = os.path.join(ROOT, fname)
    if not os.path.exists(path):
        ck(False, f"{fname} is missing")
        continue
    try:
        json.load(open(path, encoding="utf-8"))
        ck(True, f"{fname} is valid JSON")
    except Exception as e:                      # noqa: BLE001
        ck(False, f"{fname}: {e}")

# every code named in block_groups.json should be a code we actually track,
# otherwise a roll-up silently does nothing
if projects and have["block_groups"]:
    tracked = set()
    for p in projects:
        for c in (p.get("code") or "").split(","):
            if c.strip():
                tracked.add(c.strip())
    for code in UT.block_groups():
        if code.startswith("_"):                # documentation keys
            continue
        ck(code in tracked, f"block_groups.json key {code!r} matches a tracked project code")

# unit_types keys named in projects.csv must exist in unit_types.json
if projects and have["config"]:
    known = set(UT.config())
    for p in projects:
        for k in (p.get("unit_types") or "").split(","):
            k = k.strip()
            if k:
                ck(k in known, f"unit_types {k!r} ({p['project']}) is defined in unit_types.json")

print()
if FAILS:
    print(f"{len(FAILS)} check(s) FAILED")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("all checks passed")
