#!/usr/bin/env python3
"""Turn the developer index into a workbook for cross-checking by hand.

Reads data/developers.csv (from discover_developers.py) and companies.csv, and
writes one sheet listing every developer found plus one candidate sheet per
company. Candidates are matched on company name, email domain and address
separately, and the sheet says which signal fired -- because no single signal
is reliable. Chin Hin registers companies with unrelated names and a Fiamma
email, and is only identifiable by "Menara Chin Hin" in the address; TS Law is
only identifiable by its email; some developers use a personal gmail and match
nothing at all.

  python scripts/build_developer_workbook.py data/TEDUH_Company_Index.xlsx

Writes to data/, not docs/downloads/. Two reasons: the website must not change
while the new trackers are still being designed, and the Friday cleanup globs
docs/downloads for "*Developer*.xlsx" and copies the newest match onto the
Klang Valley tracker -- a file named TEDUH_Developers.xlsx there would quietly
overwrite it.
"""
import csv, os, sys
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT = "Arial"
HEAD = PatternFill("solid", fgColor="2A78D6")
KNOWN = PatternFill("solid", fgColor="FFF2CC")      # a code you already confirmed

COLUMNS = [("kod_pemaju", "DEVELOPER CODE", 15), ("nama_pemaju", "COMPANY NAME", 42),
           ("emel", "EMAIL", 30), ("telefon", "PHONE", 15),
           ("alamat_perniagaan", "BUSINESS ADDRESS", 52),
           ("alamat_daftar", "REGISTERED ADDRESS", 52),
           ("status_pemaju", "STATUS", 12), ("bilangan_projek", "PROJECTS", 10),
           ("negeri", "STATE", 18), ("daerah", "DISTRICT", 18),
           ("projek_nama", "FIRST PROJECT", 34)]


def read(path):
    if not os.path.exists(path):
        sys.exit(f"missing {path} — run discover_developers.py first")
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def parts(value):
    return [p.strip().lower() for p in (value or "").split("|") if p.strip()]


def matches(dev, rule):
    """Which of the three signals identify this developer as the company's."""
    hits = []
    name = (dev.get("nama_pemaju") or "").lower()
    mail = (dev.get("emel") or "").lower()
    addr = ((dev.get("alamat_perniagaan") or "") + " " +
            (dev.get("alamat_daftar") or "")).lower()
    if any(p in name for p in parts(rule.get("match_name"))):
        hits.append("name")
    if any(p in mail for p in parts(rule.get("match_email"))):
        hits.append("email")
    if any(p in addr for p in parts(rule.get("match_address"))):
        hits.append("address")
    return hits


def sheet(wb, title, rows, extra=None, known=()):
    ws = wb.create_sheet(title[:31])
    headers = [h for _, h, _ in COLUMNS] + ([extra] if extra else [])
    for c, h in enumerate(headers, 1):
        cell = ws.cell(1, c, h)
        cell.font = Font(name=FONT, bold=True, color="FFFFFF", size=10)
        cell.fill = HEAD
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for c, (_, _, w) in enumerate(COLUMNS, 1):
        ws.column_dimensions[get_column_letter(c)].width = w
    if extra:
        ws.column_dimensions[get_column_letter(len(COLUMNS) + 1)].width = 18

    for r, row in enumerate(rows, 2):
        for c, (key, _, _) in enumerate(COLUMNS, 1):
            v = row.get(key, "")
            if key in ("kod_pemaju", "bilangan_projek") and str(v).strip().isdigit():
                v = int(v)
            cell = ws.cell(r, c, v)
            cell.font = Font(name=FONT, size=10)
            cell.alignment = Alignment(vertical="top", wrap_text=(c in (5, 6)))
        if extra:
            cell = ws.cell(r, len(COLUMNS) + 1, row.get("_matched", ""))
            cell.font = Font(name=FONT, size=10)
        if str(row.get("kod_pemaju", "")) in known:
            for c in range(1, len(headers) + 1):
                ws.cell(r, c).fill = KNOWN

    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{max(2, len(rows) + 1)}"
    ws.row_dimensions[1].height = 28
    return ws


def legend(wb, devs, companies, found):
    ws = wb.create_sheet("How to use", 0)
    lines = [
        ("TEDUH developer index", True),
        ("", False),
        (f"{found} developers found across {len(devs)} codes probed.", False),
        ("", False),
        ("A TEDUH project code is the developer's code plus a sequence number, so 31332-1", False),
        ("is project 1 of developer 31332. Once a company's developer codes are known, every", False),
        ("project it owns follows automatically — including phases filed under names that do", False),
        ("not match how the project is advertised.", False),
        ("", False),
        ("Each company sheet lists candidates matched on THREE separate signals, and the", False),
        ("last column says which one fired. No single signal is reliable:", False),
        ("", False),
        ("   name      Exsim registers companies called EXSIM SOMETHING — works.", False),
        ("   email     TS Law registers PLAZA SENTOSA PROPERTIES but uses tslawland.com.", False),
        ("   address   Chin Hin registers AFFLUENT CRAFTS with a fiamma.com.my email;", False),
        ("             only 'Menara Chin Hin' in the address gives it away.", False),
        ("", False),
        ("Some developers use a personal gmail and a generic name, and will match nothing.", False),
        ("Those have to be found from a project you already know belongs to the company.", False),
        ("", False),
        ("Shaded rows are codes already confirmed in companies.csv.", False),
        ("", False),
        ("Check the candidates, then put the confirmed codes into companies.csv.", False),
    ]
    for r, (text, bold) in enumerate(lines, 1):
        c = ws.cell(r, 1, text)
        c.font = Font(name=FONT, size=13 if bold else 10, bold=bold)
    ws.column_dimensions["A"].width = 100
    return ws


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        ROOT, "data", "TEDUH_Company_Index.xlsx")
    devs = read(os.path.join(ROOT, "data", "developers.csv"))
    companies = read(os.path.join(ROOT, "companies.csv"))
    found = [d for d in devs if d.get("found") == "yes"]
    found.sort(key=lambda d: int(d["kod_pemaju"]) if str(d["kod_pemaju"]).isdigit() else 0)

    wb = Workbook()
    wb.remove(wb.active)
    legend(wb, devs, companies, len(found))

    summary = []
    for rule in companies:
        known = set(parts(rule.get("known_codes")))
        known = {k.upper() for k in known}
        cands = []
        for d in found:
            hits = matches(d, rule)
            if hits or str(d["kod_pemaju"]) in known:
                row = dict(d)
                row["_matched"] = ", ".join(hits) if hits else "known code"
                cands.append(row)
        cands.sort(key=lambda r: (r["_matched"] != "known code", r["nama_pemaju"]))
        sheet(wb, rule["company"], cands, extra="MATCHED ON", known=known)
        projects = sum(int(c["bilangan_projek"]) for c in cands
                       if str(c.get("bilangan_projek", "")).strip().isdigit())
        summary.append((rule["company"], len(known), len(cands), projects))

    ws = wb.create_sheet("Summary", 1)
    for c, h in enumerate(["COMPANY", "CONFIRMED CODES", "CANDIDATES", "PROJECTS IF ALL CONFIRMED"], 1):
        cell = ws.cell(1, c, h)
        cell.font = Font(name=FONT, bold=True, color="FFFFFF", size=10)
        cell.fill = HEAD
    for r, row in enumerate(summary, 2):
        for c, v in enumerate(row, 1):
            ws.cell(r, c, v).font = Font(name=FONT, size=10)
    for c, w in enumerate([24, 18, 14, 26], 1):
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.freeze_panes = "A2"

    # Every project belonging to a candidate developer, for checking unit
    # counts against what the company advertises.
    projects = []
    ppath = os.path.join(ROOT, "data", "projects_index.csv")
    if os.path.exists(ppath):
        by_dev = {}
        for p in read(ppath):
            by_dev.setdefault(p["kod_pemaju"], []).append(p)
        for rule in companies:
            known = {k.upper() for k in parts(rule.get("known_codes"))}
            for d in found:
                if matches(d, rule) or str(d["kod_pemaju"]) in known:
                    for p in by_dev.get(str(d["kod_pemaju"]), []):
                        row = dict(p)
                        row["_company"] = rule["company"]
                        projects.append(row)
        projects.sort(key=lambda r: (r["_company"], r["kod_pemaju"], r["kod_projek"]))

    ws = wb.create_sheet("Company projects", 2)
    heads = ["COMPANY", "DEVELOPER CODE", "DEVELOPER NAME", "PROJECT CODE",
             "PROJECT NAME ON TEDUH", "TOTAL UNITS", "ADVERTISED UNITS",
             "STATE", "DISTRICT", "STATUS", "PERMIT START", "PERMIT END"]
    keys = ["_company", "kod_pemaju", "nama_pemaju", "kod_projek", "projek_nama",
            "unit", None, "negeri", "daerah", "status", "permit_mula", "permit_tamat"]
    for c, h in enumerate(heads, 1):
        cell = ws.cell(1, c, h)
        cell.font = Font(name=FONT, bold=True, color="FFFFFF", size=10)
        cell.fill = PatternFill("solid", fgColor="EB6834") if h == "ADVERTISED UNITS" else HEAD
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for r, row in enumerate(projects, 2):
        for c, k in enumerate(keys, 1):
            if k is None:                       # left blank for you to fill in
                ws.cell(r, c).fill = PatternFill("solid", fgColor="FFF2CC")
                continue
            v = row.get(k, "")
            if k == "unit" and str(v).strip().isdigit():
                v = int(v)
            ws.cell(r, c, v).font = Font(name=FONT, size=10)
    for c, w in enumerate([18, 15, 40, 14, 38, 12, 16, 16, 16, 14, 14, 14], 1):
        ws.column_dimensions[get_column_letter(c)].width = w
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(heads))}{max(2, len(projects) + 1)}"
    ws.row_dimensions[1].height = 28

    sheet(wb, "All developers", found)

    os.makedirs(os.path.dirname(out), exist_ok=True)
    wb.save(out)
    print(f"{out}: {len(found)} developers, {len(projects)} company projects, "
          f"{len(companies)} company sheets")
    for name, k, c, p in summary:
        print(f"  {name:<20} {k} confirmed, {c} candidates, {p} projects")


if __name__ == "__main__":
    main()
