#!/usr/bin/env python3
"""Apply her Accept / Dismiss answers to pre-launch finds (phase 4).

  python3 scripts/apply_prelaunch_resolutions.py [--dry-run]

The Pre-launch page shows two links on each "Check: new in ..." notice, and a
"Wrong project? Dismiss" link on each source in a project's pop-up. Like the
developer watch's "Resolve..." links, each opens GitHub's new-file page with
one file filled in:

    data/prelaunch_resolved/<find id>     containing  accept   or   dismiss

Committing it is the answer -- only someone with write access can, which is
the guard against a stray tap. The push starts the refresh, which runs this
right after apply_resolutions.py.

  dismiss                 the find is marked dismissed and leaves the page.
                          The watch skips the same link from then on; news
                          with a new stage or date comes back as a new find.
  accept, on a "new in    a row with no code is added to that area tracker
  your area" check        in projects.csv -- name, developer and total units
                          taken from the notice -- and the find moves onto
                          it. "accept Some Other Name" uses that name instead.
                          If the tracker already has a row of that name, the
                          find simply joins it.
  accept, on a project's  the find is marked accepted (it already sits on her
  own find                row); nothing else changes.

This is the only pre-launch script that writes projects.csv, and only because
she committed the answer. The files stay as the record; applying them again
changes nothing. Never fails the run: a bad file is reported and skipped.
"""
import csv, hashlib, os, re, sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESOLVED = os.path.join(ROOT, "data", "prelaunch_resolved")
FINDS = os.path.join(ROOT, "data", "prelaunch_finds.csv")
PROJECTS = os.path.join(ROOT, "projects.csv")
ANSWERS = {"accept": "accept", "yes": "accept", "add": "accept",
           "dismiss": "dismiss", "no": "dismiss", "reject": "dismiss"}


def find_id(f):
    """Stable id for a finds line; build_dashboard.py uses the same recipe.
    Only fields an answer never changes: accepting a new-in-area check fills
    in `project`, and the id must still find the line afterwards."""
    key = "|".join((f.get(k) or "").strip() for k in ("seen", "tracker", "url", "note"))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


def read_answers(folder=RESOLVED):
    """{id: (answer, rest of the first line)}."""
    out = {}
    if not os.path.isdir(folder):
        return out
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        fid = os.path.splitext(name)[0].strip().lower()
        if not os.path.isfile(path) or name.startswith(".") or not re.fullmatch(r"[0-9a-f]{10}", fid):
            continue
        with open(path, encoding="utf-8") as fh:
            line = (fh.read().strip().splitlines() or [""])[0]
        word, _, rest = line.partition(" ")
        answer = ANSWERS.get(word.strip().lower().rstrip(":"))
        if answer:
            out[fid] = (answer, rest.strip())
        else:
            print(f"WARN {name}: expected 'accept' or 'dismiss', skipped")
    return out


def name_from_note(note):
    """'LUNAR Seputeh (MRCB Land) -- 483 units ...' -> ('LUNAR Seputeh', 'MRCB Land', '483')."""
    head = re.split(r"\s+--\s+|;", note, maxsplit=1)[0].strip()
    dev = ""
    m = re.match(r"^(.*?)\s*\(([^()]*)\)\s*$", head)
    if m:
        head, dev = m.group(1).strip(), m.group(2).strip()
    head = head.split(",")[0]          # 'The ATAS, Taman Desa' -> 'The ATAS'; the place is not the name
    units = (re.search(r"\b(\d[\d,]{1,6})\s+units\b", note) or [None, ""])[1].replace(",", "")
    return head.rstrip(" ,"), dev, units


def apply(answers, finds, cols, rows):
    """Apply in memory. Returns (finds changed, projects changed)."""
    by_id = {find_id(f): f for f in finds}
    finds_changed = projects_changed = False
    for fid, (answer, rest) in answers.items():
        f = by_id.get(fid)
        if f is None:
            print(f"WARN {fid}: no such find in data/prelaunch_finds.csv")
            continue
        if (f.get("status") or "").strip() in ("accepted", "dismissed"):
            continue                                  # already answered
        if answer == "dismiss":
            f["status"] = "dismissed"
            finds_changed = True
            print(f"DISMISSED {fid} {f.get('project') or f.get('note', '')[:60]}")
            continue
        if (f.get("project") or "").strip():
            f["status"] = "accepted"
            finds_changed = True
            print(f"ACCEPTED {fid} on {f['tracker']} / {f['project']}")
            continue
        name, dev, units = name_from_note(f.get("note") or "")
        name = rest or name
        tracker = (f.get("tracker") or "").strip()
        if not name or not tracker:
            print(f"WARN {fid}: no project name or tracker to add -- answer 'accept Project Name'")
            continue
        sib = [r for r in rows if (r.get("tracker") or "").strip() == tracker]
        row = next((r for r in sib if (r.get("project") or "").strip().upper() == name.upper()), None)
        if row is None:
            nos = [int(r["no"]) for r in sib if str(r.get("no") or "").strip().isdigit()]
            row = {c: "" for c in cols}
            row.update(tracker=tracker, tracker_label=(sib[0].get("tracker_label") or "").strip() if sib else "",
                       no=str(max(nos, default=0) + 1), project=name, developer=dev, total_units=units,
                       remarks=f"Added from the pre-launch watch on {date.today().isoformat()}")
            rows.append(row)
            projects_changed = True
            print(f"ADDED '{name}' to the '{tracker}' tracker (no code yet)")
        f["project"] = row["project"]
        f["status"] = "accepted"
        finds_changed = True
    return finds_changed, projects_changed


def main():
    dry = "--dry-run" in sys.argv
    answers = read_answers()
    if not answers:
        print("no pre-launch answers")
        return
    with open(FINDS, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        fcols, finds = list(reader.fieldnames or []), list(reader)
    with open(PROJECTS, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        cols, rows = list(reader.fieldnames or []), list(reader)
    finds_changed, projects_changed = apply(answers, finds, cols, rows)
    if dry:
        print("--dry-run: nothing written")
        return
    if projects_changed:
        with open(PROJECTS, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
    if finds_changed:
        with open(FINDS, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fcols)
            w.writeheader()
            w.writerows(finds)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:                            # noqa: BLE001
        # Her answer can wait a day; the day's sales figures cannot.
        print(f"apply_prelaunch_resolutions: giving up quietly ({e})")
