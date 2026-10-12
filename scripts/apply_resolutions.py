#!/usr/bin/env python3
"""Apply her answers to the purple "Check:" notices on the website.

  python3 scripts/apply_resolutions.py [--dry-run]

A name-match or new-SPV find is a guess, so the watch never adds it; it stays
on the site, purple, until she answers it. The "Resolve…" link on the notice
opens GitHub's new-file page with one file filled in:

    data/teduh_watch_resolved/<code>      containing  accept   or   dismiss

Committing it is the answer -- GitHub only lets someone with write access to
the repo do that, which is the guard against a stray tap. The push starts the
refresh workflow, which runs this before deciding whether to scrape, so an
accepted code is scraped in the same run.

  accept, name-match  the code is filled into the code-less row the notice
                      named (Hanya Wahyu's row 6, not a new row 7). Her name
                      and total units stay; a blank developer or total is
                      filled from TEDUH.
  accept, new-spv     a row is appended to that developer tracker under the
                      registered TEDUH name and unit count, as the watch's
                      own auto-add does.
  dismiss             the notice comes down; nothing else changes.

The files are left in place as the record of what she decided, and applying
them again changes nothing. Never fails the run: a bad file is reported and
skipped.
"""
import csv, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import watch_developers as WD

ROOT = WD.ROOT
RESOLVED = os.path.join(ROOT, "data", "teduh_watch_resolved")
ANSWERS = {"accept": "accept", "yes": "accept", "add": "accept",
           "dismiss": "dismiss", "no": "dismiss", "reject": "dismiss"}


def read_answers(folder=RESOLVED):
    """{code: 'accept' | 'dismiss'} from the files in the folder."""
    out = {}
    if not os.path.isdir(folder):
        return out
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        code = os.path.splitext(name)[0].strip()
        if not os.path.isfile(path) or name.startswith(".") or not WD.split_code(code):
            continue
        with open(path, encoding="utf-8") as f:
            words = f.read().strip().lower().split()
        answer = ANSWERS.get(words[0] if words else "")
        if answer:
            out[code] = answer
        else:
            print(f"WARN {name}: expected 'accept' or 'dismiss', skipped")
    return out


def apply(answers, watch, rows, cols):
    """Apply answers in memory. Returns (watch changed, projects changed)."""
    by_code = {r.get("kod_projek"): r for r in watch}
    watch_changed = projects_changed = False
    for code, answer in answers.items():
        find = by_code.get(code)
        if find is None:
            print(f"WARN {code}: not in data/teduh_watch.csv, nothing to resolve")
            continue
        if find.get("kind") not in WD.GUESS_KINDS:
            continue                            # already answered, or never a guess
        if answer == "dismiss":
            find["kind"] = "dismissed"
            watch_changed = True
            print(f"DISMISSED {code} {find.get('nama', '')}")
            continue
        if find["kind"] == "name-match":
            tracker = (find.get("trackers") or "").split(";")[0].strip()
            label = (find.get("label") or "").strip()
            row = next((r for r in rows
                        if (r.get("tracker") or "").strip() == tracker
                        and (r.get("project") or "").strip() == label
                        and not (r.get("code") or "").strip()), None)
            if row is None:
                print(f"WARN {code}: no code-less '{label}' row in the '{tracker}' "
                      "tracker any more -- left for her to place by hand")
                continue
            row["code"] = code
            if not (row.get("developer") or "").strip():
                row["developer"] = find.get("pemaju", "")
            if not (row.get("total_units") or "").strip() and str(find.get("units") or "").strip():
                row["total_units"] = str(find["units"])
            print(f"ACCEPTED {code} into '{label}' ({tracker})")
        else:
            added = WD.add_rows(rows, cols, [find])
            if not added:
                print(f"WARN {code}: already in projects.csv or no developer tracker to add it to")
                find["kind"] = "accepted"
                watch_changed = True
                continue
            print(f"ACCEPTED {code} as a new row in '{added[0][1]}'")
        find["kind"] = "accepted"
        watch_changed = projects_changed = True
    return watch_changed, projects_changed


def main():
    dry = "--dry-run" in sys.argv
    answers = read_answers()
    if not answers:
        print("no resolutions")
        return
    watch = WD.read(WD.WATCH)
    pcsv = os.path.join(ROOT, "projects.csv")
    cols, rows = WD.read_projects(pcsv)
    watch_changed, projects_changed = apply(answers, watch, rows, cols)
    if dry:
        print("--dry-run: nothing written")
        return
    if projects_changed:
        WD.write_projects(pcsv, cols, rows)
    if watch_changed:
        with open(WD.WATCH, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=WD.FIELDS, lineterminator="\n")
            w.writeheader()
            for r in watch:
                w.writerow({k: r.get(k, "") for k in WD.FIELDS})


if __name__ == "__main__":
    try:
        main()
    except Exception as e:                            # noqa: BLE001
        # Her answer can wait a day; the day's sales figures cannot.
        print(f"apply_resolutions: giving up quietly ({e})")
