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
import csv, json, os, re, sys

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
             "fill_apdl", "watch_developers", "survey_area", "apply_resolutions",
             "watch_prelaunch", "prelaunch_images", "watch_brochures"]:
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
for fn in ["block_of", "regroup", "note_for", "classify", "tally", "block_groups", "config",
           "per_code", "is_floor_set", "suppressed", "strip_block_prefix", "glued_block"]:
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
                    ("D1-12-01", "D1"), ("A- 01-02", "A"),
                    # The Seed: house number in front, block inside the bracket
                    ("957 (35-01-01)", "35"), ("1009 (36-02-03)", "36"),
                    # Sime Darby: bracket is part of the block name
                    ("HT6T1A(I)/1-05-02", "HT6T1A(I)/1")]:
        ck(UT.block_of(u) == want, f"{u!r} -> {want!r}")

# Desa Timur's "B39-13" lost its first hyphen; it is still block B. Floor-unit
# numbers must never be read this way.
if not have["glued_block"]:
    ck(False, "glued_block() missing - skipping its checks")
else:
    ck(UT.glued_block("B39-13") == "B", "'B39-13' -> 'B' (Desa Timur typo)")
    ck(UT.glued_block("B23A-05") == "B", "'B23A-05' -> 'B'")
    for u in ["9-1", "10-3A", "G-01", "A-08-03", "B-39-12"]:
        ck(UT.glued_block(u) is None, f"{u!r} is not a glued block -> None")

# --------------------------------------------------------------------------
section("is_floor_set(): floors dressed up as blocks get no note")
# --------------------------------------------------------------------------
# EcoWorld numbers single towers FLOOR-UNIT-TYPE (GF-01-Ab), which block_of()
# reads as one "block" per storey. The guard blanks those; every genuine
# tower set on the trackers must pass through untouched.
if not have["is_floor_set"]:
    ck(False, "is_floor_set() missing - skipping its checks")
else:
    ck(UT.is_floor_set({"GF": 10, "01": 3, "02": 3}), "GF among prefixes -> floors")
    ck(UT.is_floor_set({"UG": 9} | {f"{i:02d}": 21 for i in range(1, 25)}),
       "UG plus a storey run -> floors")
    ck(UT.is_floor_set({f"{i:02d}": 8 for i in range(1, 33)}),
       "32 numeric prefixes -> floors")
    ck(not UT.is_floor_set({"M": 387, "U": 616}), "Astrum towers M/U are blocks, not mezzanine")
    ck(not UT.is_floor_set({"1A": 327, "1B": 340, "2A": 215, "2B": 176}),
       "Parkland 1A/1B/2A/2B are blocks")
    ck(not UT.is_floor_set({"B1": 231, "B2": 285, "D1": 168, "D2": 288}),
       "Causewayz B1/B2/D1/D2 are blocks")
    ck(not UT.is_floor_set({"1": 63, "2": 124, "3": 22, "5": 32, "A": 112}),
       "Templer's townhouse blocks 1/2/3/5 + tower A are blocks")
    ck(not UT.is_floor_set({}), "empty set is not floors")

if not have["strip_block_prefix"]:
    ck(False, "strip_block_prefix() missing - skipping its checks")
else:
    g = UT.strip_block_prefix({"HT5T4(I)/A": 16, "HT5T4(I)/B": 30, "HT5T4(I)/C": 32})
    ck(set(g) == {"A", "B", "C"} and g["A"] == 16, f"The Glades phase prefix dropped -> {sorted(g)}")
    g = UT.strip_block_prefix({"RA/N": 63, "RA/S": 41})
    ck(set(g) == {"N", "S"}, f"Pavilion RA/ prefix dropped -> {sorted(g)}")
    g = UT.strip_block_prefix({"PT 26/A": 5, "PT 26/B": 6})
    ck(set(g) == {"A", "B"}, "space inside the prefix still strips at the last '/'")
    ck(UT.strip_block_prefix({"A1": 3, "A2": 4}) == {"A1": 3, "A2": 4},
       "A1/A2 share 'A' but no separator - untouched")
    ck(UT.strip_block_prefix({"M": 387, "U": 616}) == {"M": 387, "U": 616},
       "Astrum towers untouched")
    ck(UT.strip_block_prefix({"1A": 1, "1B": 2, "2A": 3, "2B": 4})
       == {"1A": 1, "1B": 2, "2A": 3, "2B": 4}, "Parkland blocks untouched")
    ck(UT.strip_block_prefix({"HT5T4(I)/A": 1}) == {"HT5T4(I)/A": 1},
       "a lone block keeps its full name")
    g = UT.strip_block_prefix({"X/A": 1, "X/B": 2, UT.OTHER: 3})
    ck(g.get(UT.OTHER) == 3 and set(g) == {"A", "B", UT.OTHER},
       "Other passes through a strip unrenamed")

if not have["suppressed"]:
    ck(False, "suppressed() missing - skipping its checks")
else:
    ck(UT.suppressed("14331-7"), "Setia Eco Templer 1B note is hand-suppressed")
    ck(not UT.suppressed("30635-1"), "Parkland is not suppressed")
    ck(not UT.suppressed(""), "blank code is not suppressed")

# --------------------------------------------------------------------------
section("new-SPV sweep: family patterns resolve to the right tracker")
# --------------------------------------------------------------------------
# The sweep flags a fresh SPV whose name carries a tracked developer's family
# name. Longest pattern wins, so SETIA AWAN never lands on S P Setia.
try:
    import watch_developers as WD
    fams = WD.family_patterns()
    ck(len(fams) >= 20, f"developer_families.csv loads ({len(fams)} patterns)")
    for pemaju, want in [("EXSIM MX4 SDN. BHD.", "exsim"),
                         ("SETIA AWAN HOLDINGS SDN. BHD.", "setiaawan"),
                         ("S P SETIA BERHAD", "spsetia"),
                         ("SCIENTEX QUATARI SDN. BHD.", "scientex"),
                         ("KHOO SOON LEE REALTY SDN. BHD.", "ksl"),
                         ("JXL KARANGAN DEVELOPMENT SDN. BHD.", "")]:
        got = WD.family_match(pemaju, fams)
        ck(got == want, f"{pemaju[:34]!r} -> {got or 'no match'!r}")
    ck(not WD.family_match("ECOLOGY SDN. BHD.", fams),
       "ECO matches whole words only, not ECOLOGY")
    # TS Law's SPVs never carry its name; their @tslawland.com email does.
    devs = {r["kod_pemaju"]: r.get("emel") or "" for r in WD.read(WD.DEVELOPERS)
            if r.get("found") == "yes"}
    doms = WD.domain_trackers(WD.read(os.path.join(ROOT, "projects.csv")), devs)
    ck(doms.get("tslawland.com") == "tslaw", "@tslawland.com -> tslaw")
    ck("sunway.com.my" not in doms, "a joint venture's partner domain (@sunway.com.my) is not borrowed")
    ck("gmail.com" not in doms and WD.email_domain("x@gmail.com") == "",
       "webmail domains never match a developer")
    # A name-watch hit whose SPV carries another tracker's name is dropped,
    # unless its email is the searching tracker's own (M Mira, 31 Oct 2026).
    ck(doms.get("mahsing.com.my") == "mahsing", "@mahsing.com.my -> mahsing")
    labels = {"maxim": "MAXIM", "exsim": "EXSIM", "mahsing": "MAH SING", "brdb": "BRDB"}
    ck(not WD.belongs_elsewhere("MAXIM HEIGHTS SDN. BHD.", "MMira@mahsing.com.my",
                                "mahsing", labels, doms),
       "MAXIM HEIGHTS with a @mahsing.com.my email is kept for Mah Sing")
    ck(WD.belongs_elsewhere("EXSIM MX4 SDN. BHD.", "syazana.sahimi@exsim.my",
                            "brdb", labels, doms),
       "EXSIM MX4 is still dropped from BRDB's name watch")
    ck(WD.name_tokens("Hanya Wahyu @ Taman Wahyu") == ["hanya", "wahyu"],
       f"every distinctive word is searched -> {WD.name_tokens('Hanya Wahyu @ Taman Wahyu')}")
    ck("hanya" in WD.words_of("RESIDENSI HAN-YA WAHYU"), "HAN-YA reads as hanya")
except Exception as e:                                     # noqa: BLE001
    ck(False, f"family-pattern checks failed to run ({e})")

# --------------------------------------------------------------------------
section("Check-notice answers: accept fills the right row, dismiss adds nothing")
# --------------------------------------------------------------------------
# An accepted name match must fill the code-less row it was matched to, never
# append a second one -- the duplicate Hanya Wahyu nearly got on 12 Oct 2026.
try:
    import apply_resolutions as AR
    cols = ["tracker", "tracker_label", "no", "project", "code", "developer",
            "apdl", "total_units", "remarks"]
    rows = [dict(zip(cols, ["tslaw", "TS Law", "6", "Hanya Wahyu @ Taman Wahyu",
                            "", "", "", "1816", "Not launched yet."]))]
    base = {"kod_pemaju": "", "pemaju": "X SDN. BHD.", "units": "900",
            "permit_mula": "", "trackers": "tslaw"}
    watch = [dict(base, kod_projek="31436-1", kind="name-match", nama="RESIDENSI HAN-YA WAHYU",
                  label="Hanya Wahyu @ Taman Wahyu"),
             dict(base, kod_projek="31999-1", kind="new-spv", nama="NEW ONE", label="@tslawland.com"),
             dict(base, kod_projek="31998-1", kind="new-spv", nama="NOT THEIRS", label="@tslawland.com")]
    AR.apply({"31436-1": "accept", "31999-1": "accept", "31998-1": "dismiss"}, watch, rows, cols)
    ck(len(rows) == 2, f"one row appended, for the new SPV only ({len(rows) - 1})")
    ck(rows[0]["code"] == "31436-1" and rows[0]["total_units"] == "1816",
       "name match filled row 6's code and kept her 1,816 units")
    ck(rows[1]["code"] == "31999-1" and rows[1]["no"] == "7", "new SPV became row 7")
    ck([w["kind"] for w in watch] == ["accepted", "accepted", "dismissed"],
       f"watch kinds -> {[w['kind'] for w in watch]}")
    AR.apply({"31436-1": "accept", "31999-1": "accept"}, watch, rows, cols)
    ck(len(rows) == 2, "applying the same answers again changes nothing")
    # A developer code she named for a code-less row (The Shang Residence =
    # 31361, Majestic PD Township* = 31510) is a guess for her to confirm:
    # its phases become name-match notices on that row, never auto-added
    # (her call, 03 Nov 2026). Accept fills her row; nothing else does.
    rows = [dict(zip(cols, ["status13", "", "13", "THE SHANG RESIDENCE", "",
                            "SHANG HEIGHT REALTY SDN. BHD.", "", "449", ""]))]
    extra = [{"value": "31361", "label": "The Shang Residence", "trackers": "status13"},
             {"value": "8763-2", "label": "Ukay Spring (Malton)", "trackers": "ukay"}]
    claims = WD.claimed_rows(extra, rows)
    ck(claims == {"31361": ("status13", "THE SHANG RESIDENCE")},
       f"31361 claims the code-less Shang row, by her row's own name -> {claims}")
    ck("add_rows" in dir(WD) and "claims" not in WD.add_rows.__code__.co_varnames,
       "add_rows() has no claim path left -- nothing named by her is auto-filled")
    find = dict(base, kod_projek="31361-1", kod_pemaju="31361", nama="RESIDENSI SHANG",
                units="450", permit_mula="2026-11-01", trackers="status13")
    ck(WD.add_rows(rows, cols, [find]) == [] and rows[0]["code"] == "",
       "a licensed 31361-1 is not written into projects.csv by the watch")
    watch = [dict(find, kind="name-match", label=claims["31361"][1])]
    AR.apply({"31361-1": "accept"}, watch, rows, cols)
    ck(len(rows) == 1 and rows[0]["code"] == "31361-1" and rows[0]["total_units"] == "449",
       "her accept fills the Shang row and keeps her 449 units")
    ck(WD.claimed_rows(extra, rows) == {}, "the claim lapses once the row has a code")
except Exception as e:                                     # noqa: BLE001
    ck(False, f"resolution checks failed to run ({e})")

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
        # The same rule on note_prefix: a placeholder whose code was filled in.
        ({"note_prefix": "Not launched yet.", "code": "1-1"}, 5, ""),
        ({"note_prefix": "Not launched yet.", "code": "1-1"}, 0, "Not launched yet."),
        ({"note_prefix": "Block C is not opened yet.", "code": "1-1"}, 5,
         "Block C is not opened yet."),
    ]
    for proj, sold, want in cases:
        a, b = BD.remark_for(proj, "", sold), BT.remark_for(proj, "", sold)
        ck(a == want and b == want,
           f"stale remark: {proj.get('remarks') or proj.get('note_prefix')!r} sold={sold} code={'yes' if proj['code'] else 'no'} -> {want!r}")
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
        # A per_code entry replaces block parsing with one figure per phase
        # (Ferringhi). Its inner keys must be that same project's codes, or a
        # phase would silently drop out of the note.
        spec = UT.block_groups().get(code)
        pc = spec.get("per_code") if isinstance(spec, dict) else None
        if pc:
            own = next(([c.strip() for c in (p.get("code") or "").split(",")]
                        for p in projects
                        if (p.get("code") or "").split(",")[0].strip() == code), [])
            stray = [k for k in pc if k not in own]
            ck(not stray, f"per_code keys for {code} are that project's own codes"
                          f"{'' if not stray else f' (stray: {stray})'}")

# unit_types keys named in projects.csv must exist in unit_types.json
if projects and have["config"]:
    known = set(UT.config())
    for p in projects:
        for k in (p.get("unit_types") or "").split(","):
            k = k.strip()
            if k:
                ck(k in known, f"unit_types {k!r} ({p['project']}) is defined in unit_types.json")

# --------------------------------------------------------------------------
section("pre-launch files point at real rows")
# --------------------------------------------------------------------------
# A find or page whose tracker + project matches no projects.csv row is
# silently dropped from the Pre-launch view -- a typo would hide it -- so
# every one must resolve. Rows that have since got a code still count: their
# finds stay as the record.
BD = mods.get("build_dashboard")
if projects and BD:
    rows = {((p.get("tracker") or "").strip(),
             (p.get("project") or "").replace("\n", " ").strip().upper()) for p in projects}
    tracking = re.compile(r"[?&](utm_\w+|gclid|gbraid|wbraid|gad_source|fbclid)=")
    for f in ("data/prelaunch_finds.csv", "data/prelaunch_pages.csv", "data/prelaunch_places.csv",
              "data/prelaunch_teduh.csv"):
        path = os.path.join(ROOT, f)
        if not os.path.exists(path):
            continue
        with open(path, newline="", encoding="utf-8") as fh:
            for i, r in enumerate(csv.DictReader(fh), 2):
                proj = (r.get("project") or "").strip()
                if proj:          # blank = new in an area, not on a tracker yet
                    ck(((r.get("tracker") or "").strip(), proj.upper()) in rows,
                       f"{f} line {i}: {r.get('tracker')} / {proj} is a projects.csv row")
                url = (r.get("url") or "").strip()
                if url:
                    ck(url.startswith(("http://", "https://")), f"{f} line {i}: url is a web address")
                    ck(not tracking.search(url), f"{f} line {i}: url carries no tracking code")
                stage = (r.get("stage") or "").strip()
                if stage:
                    ck(stage in BD.STAGES, f"{f} line {i}: stage {stage!r} is one of {BD.STAGES}")
                if f.endswith("finds.csv"):
                    ck((r.get("confidence") or "").strip() in ("", "strong", "possible", "weak"),
                       f"{f} line {i}: confidence is strong, possible or weak")
                    ck((r.get("status") or "").strip() in ("new", "accepted", "dismissed"),
                       f"{f} line {i}: status is new, accepted or dismissed")

# data/prelaunch_teduh.csv values are a full code (14159-1) or a bare
# developer code (14159); anything else would be silently skipped.
tp = os.path.join(ROOT, "data", "prelaunch_teduh.csv")
if os.path.exists(tp):
    with open(tp, newline="", encoding="utf-8") as fh:
        for i, r in enumerate(csv.DictReader(fh), 2):
            v = (r.get("value") or "").strip()
            ck(re.fullmatch(r"\d+(-\d+)?", v) is not None,
               f"data/prelaunch_teduh.csv line {i}: {v!r} is a code or a developer code")

# The TEDUH status watch against a fake TEDUH: first reading is a find, a
# quiet day is not, a changed permit or a new phase is. No network.
WPm = mods.get("watch_prelaunch")
if WPm:
    from datetime import date as _d
    _world = {}
    def _pl(name, frm, to, n, sold):
        return ({"projek": {"nama": name, "permitMula": frm, "permitTamat": to},
                 "pemaju": {"nama": "SPV SDN. BHD."}, "unitSummary": {"unit": n}},
                {"unitGroups": [{"units": [{"status": "sold"}] * sold + [{"status": "avail"}] * (n - sold)}]})
    class _F(WPm.Fetcher):
        def teduh(self, url, label):
            code = url.rsplit("/", 1)[1]
            if code not in _world:
                return None, True
            return _world[code][1 if "unit-projek" in url else 0], True
    _pause, WPm.TEDUH_PAUSE = WPm.TEDUH_PAUSE, 0
    _read, WPm.read = WPm.read, lambda path: ([{"tracker": "t", "project": "P", "value": "900-1", "label": "A"},
                                                {"tracker": "t", "project": "P", "value": "900", "label": ""}]
                                               if path == WPm.TEDUH_WATCH else _read(path))
    try:
        _seen, _k = {}, {("t", "P")}
        _world["900-1"] = _pl("OLD", "2024-01-06", "2025-01-05", 10, 4)
        r1 = WPm.teduh_watch(_F(99), _seen, _d(2026, 11, 4), _k)
        r2 = WPm.teduh_watch(_F(99), _seen, _d(2026, 11, 5), _k)
        _world["900-1"] = _pl("NEW NAME", "2027-01-10", "2028-01-09", 10, 5)
        _world["900-2"] = _pl("PHASE 2", "", "", 6, 0)
        r3 = WPm.teduh_watch(_F(99), _seen, _d(2026, 11, 6), _k)
        ck(len(r1) == 1 and "4 of 10 sold" in r1[0]["note"] and "(expired)" in r1[0]["permit"],
           "TEDUH watch: first reading reports name, sold and an expired permit")
        ck(r2 == [], "TEDUH watch: an unchanged day makes no find")
        ck(len(r3) == 2 and "OLD -> NEW NAME" in r3[0]["note"] and "(current)" in r3[0]["permit"]
           and "900-2" in r3[1]["note"], "TEDUH watch: a rename, a new permit and a new phase are each reported")
        ck(_seen["teduh_next"] == {"900": 2}, "TEDUH watch: the phase probe remembers 900-2")
    finally:
        WPm.TEDUH_PAUSE, WPm.read = _pause, _read

# Developer sites one level down (3 Nov 2026): the listing pages it follows,
# and a picture-only project tile matched by its address alone.
if WPm:
    _front = [("https://www.brdb.com.my/property", "Property"),
              ("https://www.brdb.com.my/portfolio/eden", "Eden"),
              ("https://chinhinproperty.com/properties", "x"),
              ("https://chinhinproperty.com/properties?category=Nature", "Nature"),
              ("https://www.brdb.com.my/property/", "again"),
              ("https://other.example/projects", "agent")]
    ck(WPm.listing_pages(_front, "www.brdb.com.my") == ["https://www.brdb.com.my/property"],
       "pre-launch: listing pages are same-site, unfiltered, listed once")
    # www or not is the same site (myra.com.my -> www.myra.com.my, 20 Nov 2026)
    ck(WPm.site_of("https://www.Myra.com.my:443/myra-homes/") == WPm.site_of("https://myra.com.my/") == "myra.com.my",
       "pre-launch: www. and a port don't make another site")
    ck(WPm.listing_pages([("https://www.myra.com.my/projects/", "x")], {"myra.com.my"})
       == ["https://www.myra.com.my/projects/"],
       "pre-launch: a www link counts as the same site as the address without www")
    _slug = WPm.slug_words("https://www.brdb.com.my/portfolio/damansara-heights-coming-soon")
    ck(_slug == "damansara-heights-coming-soon".replace("-", " "),
       "pre-launch: a link's address reads as words")
    ck(WPm.has(_slug, "damansara heights"),
       "pre-launch: a text-less tile still matches its no-code row by its address")

# The pre-launch watch must never write projects.csv: adding a project is
# always her Accept. A cheap guard against a future edit that forgets.
wp = os.path.join(ROOT, "scripts", "watch_prelaunch.py")
if os.path.exists(wp):
    src = open(wp, encoding="utf-8").read()
    ck(not re.search(r"open\(\s*PROJECTS[^)]*['\"][wa]", src) and "write_projects" not in src,
       "watch_prelaunch.py never writes projects.csv")

# The brochure / APDL check (21 Nov 2026): permit numbers in page and PDF
# text, PDF links with spaces or in iframes, and a fake developer site whose
# APDL PDF names a no-code row -- one find, Strong, permit in its column.
# No network: the fetcher and the PDF reader are stand-ins.
WB = mods.get("watch_brochures")
if WB:
    _t = ("No. Permit Iklan & Jualan: 20164-3/06-2028/0447(N)-(S) Tempoh Sah: 06/06/2025 - 05/06/2028. "
          "Lesen 5534-32 / 08 - 2027 / 0754 (A)-(S); tel 03-1234/5678, fax 2024/1234")
    _p = WB.permits_in(_t)
    ck([x["code"] for x in _p] == ["20164-3", "5534-32"], "brochures: permit numbers give their TEDUH codes")
    ck(_p[0]["valid"] == "06/06/2025 - 05/06/2028" and _p[1]["valid"] == "",
       "brochures: a permit keeps its own validity, never its neighbour's")
    _h = ('<a href="Halaman 1-AP-19.08.2025.pdf">APDL</a><iframe src="/files/e-brochure.pdf"></iframe>'
          '<a href="/terms.pdf">Terms</a>')
    _l = WB.pdf_links_of(_h, "https://www.dev.my/projek/")
    ck(("https://www.dev.my/projek/Halaman 1-AP-19.08.2025.pdf", "APDL") in _l
       and any(u == "https://www.dev.my/files/e-brochure.pdf" for u, _ in _l),
       "brochures: PDF links are found in links and iframes")
    ck(WB.quote_url("https://www.dev.my/a b.pdf") == "https://www.dev.my/a%20b.pdf"
       and WB.quote_url("https://www.dev.my/a%20b.pdf") == "https://www.dev.my/a%20b.pdf",
       "brochures: spaces are encoded once, never twice")
    ck(WB.code_list("30962-1,30962-2\n19355-6") == {"30962-1", "30962-2", "19355-6"},
       "brochures: a multi-code cell gives every code")

    _site = {"https://www.dev.my/": '<a href="/our-projects/the-hilltop/">The Hilltop</a>'
                                    '<a href="/careers/">Jobs</a>',
             "https://www.dev.my/our-projects/the-hilltop/": '<title>The Hilltop</title>'
                                                            '<a href="APDL_Hilltop.pdf">APDL</a>'}
    _tables = {WPm.PROJECTS: [{"tracker": "dev", "project": "The Hilltop @ Somewhere", "code": "",
                               "developer": "DEV SDN BHD", "tracker_label": "Dev"},
                              {"tracker": "dev", "project": "Old One", "code": "900-1",
                               "developer": "DEV SDN BHD", "tracker_label": "Dev"}],
               WPm.SOURCES: [{"kind": "developer", "url": "https://www.dev.my/", "developer": "Dev",
                              "tracker": "dev", "probe": "ok"}],
               WPm.PAGES: [], WPm.FINDS: [], WPm.TEDUH_WATCH: []}
    class _BF(WB.Fetch):
        def get(self, url, label):
            self.asked += 1
            self.final[url] = url
            return _site.get(url)
        def get_pdf(self, url, label):
            self.asked += 1
            return b"%PDF fake", ""
    _wread, _fetch, _ptext = WPm.read, WB.Fetch, WB.pdf_text
    WPm.read = lambda path: _tables.get(path, [])
    WB.Fetch = _BF
    WB.pdf_text = lambda raw: ("Projek: Hilltop. Permit 31999-1/03-2028/0101(N)-(S) sah 01/03/2026 - 28/02/2028. "
                               "Phase 1 permit 900-1/01-2027/0001(N)-(S)", "")
    import tempfile
    _out = os.path.join(tempfile.mkdtemp(), "bro.md")
    try:
        WB.main(["--report", _out])
        _rep = open(_out, encoding="utf-8").read()
        ck("Would-be finds (1)" in _rep and "**The Hilltop @ Somewhere** (dev) -- APDL 31999-1/03-2028/0101(N)-(S), "
           "valid 01/03/2026 - 28/02/2028 -- strong" in _rep,
           "brochures: an APDL PDF on the developer's page for a no-code row is one Strong find")
        ck("900-1/01-2027/0001(N)-(S) (on a tracker)" in _rep, "brochures: a code already on a tracker is no find")
        ck("/careers/" not in _rep, "brochures: the company's own pages are not read as projects")
    finally:
        WPm.read, WB.Fetch, WB.pdf_text = _wread, _fetch, _ptext

wb = os.path.join(ROOT, "scripts", "watch_brochures.py")
if os.path.exists(wb):
    src = open(wb, encoding="utf-8").read()
    ck("PROJECTS" in src and not re.search(r"open\(\s*W\.PROJECTS[^)]*['\"][wa]", src),
       "watch_brochures.py never writes projects.csv")

# Her pre-launch answers: each file in data/prelaunch_resolved/ is named by
# a find id and says accept or dismiss. A file whose find has gone (a note
# edited after she answered) would silently do nothing, so it is flagged.
rdir = os.path.join(ROOT, "data", "prelaunch_resolved")
if os.path.isdir(rdir) and projects:
    import apply_prelaunch_resolutions as APR
    with open(os.path.join(ROOT, "data", "prelaunch_finds.csv"), newline="", encoding="utf-8") as fh:
        ids = {APR.find_id(r) for r in csv.DictReader(fh)}
    answers = APR.read_answers(rdir)
    for name in sorted(os.listdir(rdir)):
        if name.startswith("."):
            continue
        fid = os.path.splitext(name)[0].lower()
        ck(fid in answers, f"data/prelaunch_resolved/{name}: says accept or dismiss")
        ck(fid in ids, f"data/prelaunch_resolved/{name}: matches a line in prelaunch_finds.csv")

# Accepting a "new in your area" check makes a projects.csv row from the
# find's note. On 23 Nov 2026 a note whose name ended at a colon put the
# whole sentence in as the name, with 8 Conlay's 1,062 units (named in the
# note for comparison) instead of the project's 1,072.
import apply_prelaunch_resolutions as APR
for note, want in [
    ("LUNAR Seputeh (MRCB Land) -- 483 units, 683-1,646 sf; Unveiled 2 Oct", ("LUNAR Seputeh", "MRCB Land", "483")),
    ("The ATAS, Taman Desa (Maxim Global) -- 624 units; Check", ("The ATAS", "Maxim Global", "624")),
    ("Armani Hallson Bukit Bintang: Armani Group's own post 21 Nov on 'today's official launch'; "
     "may or may not be 8 Conlay (8 Conlay is on Jalan Conlay with 1,062 units; this one is near "
     "Jalan Alor with 1,072 units)", ("Armani Hallson Bukit Bintang", "", "")),
    ("The Reya @ KL East (Sime Darby): 'Your Greatest Move' event Sat 14 Nov", ("The Reya @ KL East", "Sime Darby", "")),
    ("'W Project Cochrane' (Chinese agent ad, Adrian Property): freehold", ("W Project Cochrane", "", "")),
    ("TR Prestige (MKH Property page) -- 'in the heart of Kuala Lumpur'", ("TR Prestige", "", "")),
    ("Unnamed Melawati freehold semi-D condo -- 200 units, 4-5 bed", ("", "", "200")),
    ("Posted 7 Nov: 'KSL Mutiara Bestari 4', gated double-storey", ("", "", "")),
    ("EdgeProp 21 Nov: Armani Group launched Armani Hallson Bukit Bintang", ("", "", "")),
    ("'The only affordable freehold, 5 minutes to Mid Valley' (agent HomeCity, Seputeh search)", ("", "", "")),
]:
    got = APR.name_from_note(note)
    ck(got == want, f"pre-launch accept: {note[:45]!r}... -> {want} (got {got})")

print()
if FAILS:
    print(f"{len(FAILS)} check(s) FAILED")
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("all checks passed")
