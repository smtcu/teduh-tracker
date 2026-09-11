#!/usr/bin/env python3
"""Notice when a tracked developer registers a new project on TEDUH.

  python3 scripts/watch_developers.py [--dry-run]

Every developer code (the part of a TEDUH code before the dash) found in
projects.csv is watched. Each run probes one code past the developer's highest
known phase -- new registrations always take the next -N under the same
developer code, which is exactly how MAIA arrived as 30141-2 and Binastra
Cochrane as 31332-1. A hit is recorded in data/teduh_watch.csv and shows up on
the website as a +1 badge on that developer's tracker button for a couple of
days (BADGE_DAYS in build_dashboard.py).

A find that already holds a sales permit is APPENDED to projects.csv
automatically -- to the developer tracker only, under its registered TEDUH
name, SPV and unit count -- so the notice on the site reports something that
happened, not homework. The four area trackers are never touched: which
projects belong to Seputeh, Klang Valley, Johor or Ukay stays Samantha's
curation, and the badge tells her a candidate exists. A find with no permit
waits, is re-checked every run, and joins the day its permit is issued.

data/teduh_watch_extra.csv lists things to watch that projects.csv cannot
imply: a dormant code (`8763-2`, Ukay Spring) to watch for a permit, or a bare
developer code to watch for new phases. Columns: value,label,trackers --
trackers is a semicolon list of tracker keys whose button should carry the
badge.

Known phases come from projects.csv, data/projects_index.csv (the full-register
snapshot) and the watch file itself, so nothing is probed twice. The network
manners -- pacing, Retry-After, backoff -- are imported from fill_apdl.py so
the two stay identical. Errors never fail the run: a missed probe is caught on
the next morning's run.
"""
import csv, json, os, re, sys, time, urllib.parse, urllib.request
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fill_apdl import PAUSE, fetch, permit_start

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WATCH = os.path.join(ROOT, "data", "teduh_watch.csv")
EXTRA = os.path.join(ROOT, "data", "teduh_watch_extra.csv")
INDEX = os.path.join(ROOT, "data", "projects_index.csv")
FAMILIES = os.path.join(ROOT, "data", "developer_families.csv")
# TEDUH's register listing is sorted by developer code descending, so the
# first pages are the newest SPVs -- exactly what the phase walk cannot see.
# 5 pages = the 100 newest developer codes, several weeks of registrations.
SWEEP_PAGES = 5
FIELDS = ["first_seen", "kind", "kod_projek", "kod_pemaju", "nama", "pemaju",
          "units", "permit_mula", "trackers", "label"]
MAX_NEW_PER_DEV = 3        # cap the walk upward, in case a developer lands several at once
# Words too generic to search TEDUH by. The name watch below picks the most
# distinctive word of a code-less project's name instead.
GENERIC = {"taman", "residensi", "residence", "residences", "the", "at", "apartment",
           "pangsapuri", "kondominium", "condominium", "bandar", "kota", "baru",
           "hill", "hills", "park", "city", "one", "new", "phase", "fasa"}


def name_token(project):
    """The most distinctive word of a marketing name, for a q= search."""
    words = [w.strip("()@,.'\"-") for w in (project or "").lower().split()]
    words = [w for w in words if len(w) >= 4 and w not in GENERIC and not w.isdigit()]
    return max(words, key=len) if words else ""


def name_search(token):
    """TEDUH's q= search: registered project names containing the token."""
    url = ("https://teduh.kpkt.gov.my/api/projek-swasta?q="
           + urllib.parse.quote(token))
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; teduh-tracker/1.0)",
        "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read().decode("utf-8"))
    return (d.get("projects") or {}).get("data") or []
# The four area sheets are curated by hand and the watch never writes to them.
AREA_TRACKERS = {"seputeh", "status13", "johor", "ukay"}


def newest_registrations(pages=SWEEP_PAGES):
    """The first `pages` of TEDUH's register listing, newest SPVs first.

    Each row carries id (the project code), kod_pemaju, nama and pemaju.nama,
    so matching costs one request per page -- detail is only fetched for hits.
    """
    out = []
    for n in range(1, pages + 1):
        url = "https://teduh.kpkt.gov.my/api/projek-swasta?page=%d" % n
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; teduh-tracker/1.0)",
            "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.loads(r.read().decode("utf-8"))
        out.extend((d.get("projects") or {}).get("data") or [])
        time.sleep(1.0)
    return out


def family_patterns():
    """data/developer_families.csv rows as (tracker, PATTERN) pairs.

    The file is hers to edit: one line per family name an SPV might carry
    (EXSIM, SCIENTEX, KHOO SOON LEE). Patterns under 3 characters are ignored.
    """
    out = []
    for r in read(FAMILIES):
        t = (r.get("tracker") or "").strip()
        pat = (r.get("pattern") or "").strip().upper()
        if t and len(pat) >= 3:
            out.append((t, pat))
    return out


def family_match(pemaju, families):
    """The tracker whose family name appears (whole words) in an SPV name.

    The longest matching pattern wins, so SETIA AWAN HOLDINGS lands on
    setiaawan even though SETIA alone would also match for S P Setia.
    Returns '' when nothing matches.
    """
    hay = " " + re.sub(r"[^A-Z0-9]+", " ", (pemaju or "").upper()) + " "
    best_t, best_p = "", ""
    for t, pat in families:
        needle = " " + re.sub(r"[^A-Z0-9]+", " ", pat) + " "
        if needle in hay and len(pat) > len(best_p):
            best_t, best_p = t, pat
    return best_t


def auto_add(rows_to_add, pcsv):
    """Append permit-holding finds to their developer tracker in projects.csv.

    Same read/write shape as fill_apdl.py, which rewrites this file daily, so
    the formatting stays canonical. Returns the codes actually added.
    """
    if not rows_to_add:
        return []
    import shutil
    with open(pcsv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        cols = list(reader.fieldnames or [])
        rows = list(reader)
    have = {c.strip() for r in rows for c in (r.get("code") or "").split(",") if c.strip()}
    by_tracker = {}
    for r in rows:
        by_tracker.setdefault((r.get("tracker") or "").strip(), []).append(r)
    added = []
    for find in rows_to_add:
        if find["kod_projek"] in have:
            continue
        targets = sorted(t for t in (find.get("trackers") or "").split(";")
                         if t and t not in AREA_TRACKERS and t in by_tracker)
        if not targets:
            continue                    # developer only lives in area trackers
        t = targets[0]
        sib = by_tracker[t]
        nos = [int(r["no"]) for r in sib if str(r.get("no") or "").strip().isdigit()]
        row = {c: "" for c in cols}
        row.update(tracker=t, tracker_label=(sib[0].get("tracker_label") or "").strip(),
                   no=str(max(nos, default=0) + 1), project=find["nama"],
                   code=find["kod_projek"], developer=find["pemaju"],
                   apdl=find["permit_mula"], total_units=str(find["units"]))
        rows.append(row)
        sib.append(row)
        have.add(find["kod_projek"])
        added.append((find["kod_projek"], t))
    if added:
        shutil.copyfile(pcsv, pcsv + ".bak")
        with open(pcsv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        for code, t in added:
            print(f"ADDED {code} to the '{t}' tracker in projects.csv")
    return [c for c, _ in added]


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

    # --- 1b. sweep the newest registrations for family-named new SPVs ---
    # The phase walk only sees developer codes already in the tracker; a
    # brand-new SPV (EXSIM MX4 registering D'Nuri) has a fresh code and is
    # invisible to it. The register listing is newest-code-first, so a few
    # pages cover weeks of new SPVs; one whose name carries a tracked
    # developer's family name raises a new-spv notice -- never auto-added,
    # because a new SPV's tracker assignment is her call. Whatever the sweep
    # sees also tops up projects_index.csv, keeping the snapshot fresh.
    register_codes = {r.get("kod_projek") for r in read(INDEX)}
    families = family_patterns()
    index_new = []
    try:
        sweep = newest_registrations()
    except Exception as e:                             # noqa: BLE001
        print(f"sweep skipped ({e})")
        sweep = []
    for it in sweep:
        hid = (it.get("id") or "").strip()
        pem = it.get("pemaju") or {}
        pem_name = (pem.get("nama") if isinstance(pem, dict) else str(pem or "")).strip()
        if not hid:
            continue
        if hid not in register_codes:
            index_new.append({"kod_projek": hid,
                              "kod_pemaju": (str(it.get("kod_pemaju") or "")).strip(),
                              "nama_pemaju": pem_name,
                              "projek_nama": (it.get("nama") or "").strip()})
        if (hid in tracked_codes or hid in seen_codes or hid in register_codes
                or hid in {f["kod_projek"] for f in finds}):
            continue
        sp = split_code(hid)
        if sp and sp[0] in dev_trackers:
            continue                    # the phase walk owns known developer codes
        t = family_match(pem_name, families)
        if not t or t in AREA_TRACKERS:
            continue
        detail, reached = fetch(hid, net)
        if not reached or detail is None:
            continue
        row = detail_row(hid, detail)
        row.update(first_seen=today, kind="new-spv", trackers=t, label=pem_name)
        finds.append(row)

    # --- 2. a name watch for every project tracked WITHOUT a code ---
    # Aetas Taman Desa, Chin Hin Ulu Kelang: no code, and possibly no known
    # SPV, so the phase walk above cannot see them. Search TEDUH's registered
    # names for each one's most distinctive word; a hit that is not already
    # tracked or known becomes a name-match notice (never auto-added -- the
    # match is a guess for her to confirm).
    # A hit whose SPV visibly carries another tracked developer's name is that
    # developer's launch, not a match for this no-code project. D'NURI @ KWASA
    # DAMANSARA (EXSIM MX4 SDN. BHD.) was offered to BRDB's "Damansara
    # Heights" purely on the word Damansara. The SPV sweep and phase walk are
    # how those developers' launches surface.
    dev_labels = {}
    for pr in projects:
        t = (pr.get("tracker") or "").strip()
        lbl = (pr.get("tracker_label") or "").strip().upper()
        if t and len(lbl) >= 3:
            dev_labels[t] = lbl
    for p in projects:
        if (p.get("code") or "").strip():
            continue
        token = name_token(p.get("project"))
        if not token:
            continue
        try:
            hits = name_search(token)
        except Exception:
            continue
        for h in hits:
            hid = (h.get("id") or "").strip()
            if (not hid or hid in tracked_codes or hid in seen_codes
                    or hid in register_codes
                    or hid in {f["kod_projek"] for f in finds}):
                continue
            detail, reached = fetch(hid, net)
            if not reached or detail is None:
                continue
            row = detail_row(hid, detail)
            pemaju = (row.get("pemaju") or "").upper()
            own = (p.get("tracker") or "").strip()
            if any(lbl in pemaju for t, lbl in dev_labels.items() if t != own):
                continue
            row.update(first_seen=today, kind="name-match",
                       trackers=own,
                       label=(p.get("project") or "").strip())
            finds.append(row)

    # --- 3. re-check anything known but still unlicensed ---
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

    # A find that already holds a permit joins its developer tracker now;
    # everything else waits in the watch file and is re-checked each run.
    # name-match and new-spv are guesses for her to confirm -- never added.
    licensed = [f for f in finds if f.get("permit_mula") and str(f.get("units") or "").strip()
                and f.get("kind") not in ("name-match", "new-spv")]
    licensed += [r for r in state if r.get("kind") == "permit-issued"]
    added = [] if dry else auto_add(licensed, os.path.join(ROOT, "projects.csv"))
    for r in finds + state:
        if r["kod_projek"] in added:
            r["kind"] = "added"

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

    if index_new and os.path.exists(INDEX):
        with open(INDEX, newline="", encoding="utf-8") as f:
            idx_fields = next(csv.reader(f))
        with open(INDEX, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=idx_fields, lineterminator="\n")
            for r in index_new:
                w.writerow({k: r.get(k, "") for k in idx_fields})
        print("index topped up with", len(index_new), "new registrations")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:                            # noqa: BLE001
        # A watch that fails must never take the day's scrape down with it.
        print(f"watch_developers: giving up quietly ({e})")
