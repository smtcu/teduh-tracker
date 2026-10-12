#!/usr/bin/env python3
"""One-off area survey: which untracked TEDUH projects sit in a district, and
are they still selling?

  python scripts/survey_area.py                      # Gombak, permits since 2019
  python scripts/survey_area.py --district Gombak --since 2019-01-01
  python scripts/survey_area.py --list-only          # print the candidates, no network

Built to answer "is there anything else to add to the Ukay tracker?". The
register snapshot in data/projects_index.csv has state and district but no
address and no sales, and from outside GitHub Actions TEDUH cannot be reached,
so this asks TEDUH itself for every candidate:

  - candidates are every project in the district whose permit started or ran
    on or after --since, plus every Selangor project the snapshot has no
    district for (117 of them in Oct 2026 -- one could be in Ukay), plus any
    Hulu Langat / Kuala Lumpur project whose name carries an Ukay-belt word;
  - anything already in projects.csv, on any tracker, is left out;
  - for each code it fetches the project detail (location fields, permit
    history) and the unit list (total / sold / unsold).

"Ongoing" is decided by unsold units, not by the permit date: LEA By The Hills,
Nassim Heights and Nadayu 63 all show an expired permit in the snapshot and are
still selling.

Writes data/area_survey.csv (one row per code, most unsold first) and
data/area_survey_raw.json (every scalar field of each project's detail, so a
field this script does not know about can still be read afterwards without
asking TEDUH again). It never touches projects.csv, the trackers or docs/.

The network manners are scrape_teduh.py's: one request every PAUSE seconds
across all workers, a 429 holds everyone and slows the pace. The earliest
permit date is fill_apdl.permit_start(), the same rule as the APDL column.
"""
import argparse, csv, json, os, re, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scrape_teduh as SD                       # wait_turn / push_back / retry_after / tally
from fill_apdl import permit_start

DETAIL = "https://teduh.kpkt.gov.my/api/projek-swasta/{code}"
UNITS = "https://teduh.kpkt.gov.my/api/unit-projek-swasta/{code}"
INDEX = os.path.join(ROOT, "data", "projects_index.csv")
PROJECTS = os.path.join(ROOT, "projects.csv")
OUT = os.path.join(ROOT, "data", "area_survey.csv")
RAW = os.path.join(ROOT, "data", "area_survey_raw.json")

# Names that place a project in the Ukay belt. Used twice: to pull in the odd
# Hulu Langat / KL project filed under "Ampang" or "Melawati", and to flag rows
# in the output. A flag is a hint for her to check, never a decision.
AREA = re.compile(r"ukay|melawati|kemensah|h?ulu\s*k[e]?lang|antarabangsa|ampang|"
                  r"jelatek|k[e]?lang gate|zoo|lembah jaya|hillview|taman permata|"
                  r"bukit indah|wangsa melawati|enklaf", re.I)

# Detail fields that might say where a project is. TEDUH mixes spellings, so
# keys are matched loosely; whatever matches is joined into one column.
LOCATION_KEY = re.compile(r"alamat|lokasi|mukim|bandar|poskod|postcode|jalan|"
                          r"lot|daerah|negeri|kawasan|tapak|latit|longit|koordinat", re.I)

FIELDS = ["kod_projek", "teduh_name", "developer", "index_district", "location",
          "area_hint", "units", "sold", "unsold", "apdl", "permit_mula", "permit_tamat",
          "reached"]


def candidates(district, since):
    tracked = set()
    with open(PROJECTS, newline="", encoding="utf-8") as f:
        for p in csv.DictReader(f):
            tracked.update(c.strip() for c in (p.get("code") or "").split(",") if c.strip())
    out = []
    with open(INDEX, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["kod_projek"] in tracked:
                continue
            if max(r["permit_mula"] or "", r["permit_tamat"] or "") < since:
                continue
            d, n = r["daerah"].strip(), r["negeri"].strip()
            name = f"{r['projek_nama']} {r['nama_pemaju']}"
            if (d.lower() == district.lower()
                    or (n == "Selangor" and d in ("", "-", "Tiada Maklumat Daerah"))
                    or (d in ("Hulu Langat", "Kuala Lumpur") and AREA.search(name))):
                out.append(r)
    return out


def get(url):
    """One request on the shared pace. None for a clean 404; raises if unreachable."""
    last = None
    for i in range(3):
        SD.wait_turn()
        try:
            req = Request(url, headers={"User-Agent": SD.UA, "Accept": "application/json"})
            with urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except HTTPError as e:
            last = e
            if e.code == 404:
                return None
            if e.code in (429, 503):
                wait = SD.retry_after(e, min(180, 20 * (i + 1)))
                SD.push_back(wait)
                print(f"  {e.code}, all workers waiting {wait}s", file=sys.stderr, flush=True)
                continue
        except (URLError, json.JSONDecodeError, TimeoutError, ValueError) as e:
            last = e
    raise RuntimeError(f"{url}: {last}")


def scalars(d):
    return {k: v for k, v in d.items() if not isinstance(v, (dict, list))} if isinstance(d, dict) else {}


def survey(r):
    code = r["kod_projek"]
    row = {"kod_projek": code, "teduh_name": r["projek_nama"].strip(),
           "developer": r["nama_pemaju"].strip(), "index_district": r["daerah"].strip(),
           "permit_mula": r["permit_mula"], "permit_tamat": r["permit_tamat"]}
    raw = {}
    try:
        detail = get(DETAIL.format(code=code))
        units = get(UNITS.format(code=code))
        row["reached"] = "yes"
    except Exception as e:                       # noqa: BLE001 - recorded, not raised
        row["reached"] = f"no: {e}"[:120]
        return row, raw, False
    if isinstance(detail, dict):
        projek = detail.get("projek") if isinstance(detail.get("projek"), dict) else {}
        raw = {**scalars(detail), **scalars(projek)}
        loc = [f"{k}={v}" for k, v in raw.items()
               if LOCATION_KEY.search(k) and str(v).strip() not in ("", "-", "None")]
        row["location"] = "; ".join(loc)
        row["apdl"] = permit_start(detail)
    if isinstance(units, dict):
        name, total, sold, _, _ = SD.tally(units)
        row.update(units=total, sold=sold, unsold=total - sold)
        if name:
            row["teduh_name"] = name
    hint = AREA.findall(" ".join([row["teduh_name"], row["developer"], row.get("location", "")]))
    row["area_hint"] = ", ".join(sorted({h.lower() for h in hint}))
    return row, raw, True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--district", default="Gombak")
    ap.add_argument("--since", default="2019-01-01")
    ap.add_argument("--list-only", action="store_true")
    a = ap.parse_args()

    todo = candidates(a.district, a.since)
    print(f"{len(todo)} untracked candidates "
          f"({a.district}, no-district Selangor, Ukay-named elsewhere; permits since {a.since})")
    if a.list_only:
        for r in todo:
            print(f"  {r['kod_projek']:>10}  {r['daerah'].strip()[:12]:12}  {r['projek_nama'][:50]}")
        return

    # Fields TEDUH returns are not documented; print the first project's keys so
    # the run log shows what is there even if LOCATION_KEY misses a spelling.
    rows, raws, shown_keys = [], {}, False
    dead = 0
    with ThreadPoolExecutor(max_workers=SD.WORKERS) as pool:
        futures = [pool.submit(survey, r) for r in todo]
        for n, f in enumerate(as_completed(futures), 1):
            row, raw, ok = f.result()
            rows.append(row)
            if raw:
                raws[row["kod_projek"]] = raw
                if not shown_keys:
                    shown_keys = True
                    print("detail fields TEDUH returns:", ", ".join(sorted(raw)))
            dead = 0 if ok else dead + 1
            print(f"[{n}/{len(todo)}] {row['kod_projek']:>10}  "
                  f"unsold {str(row.get('unsold', '?')):>5}  {row.get('location', '')[:70]}",
                  flush=True)
            if dead >= 3:
                print("TEDUH looks down: three codes in a row unreachable. "
                      "Writing what was gathered and stopping.", file=sys.stderr)
                for other in futures:
                    other.cancel()
                break

    rows.sort(key=lambda r: (-(r.get("unsold") or 0), r["kod_projek"]))
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    with open(RAW, "w", encoding="utf-8") as f:
        json.dump(raws, f, ensure_ascii=False, indent=1, sort_keys=True)

    reached = sum(1 for r in rows if r.get("reached") == "yes")
    selling = sum(1 for r in rows if (r.get("unsold") or 0) > 0)
    print(f"\n{reached}/{len(todo)} reached, {selling} with unsold units. Wrote {OUT}")
    if dead >= 3:
        sys.exit(3)


if __name__ == "__main__":
    main()
