#!/usr/bin/env python3
"""Print a plain-text summary of the latest weekly record, for the Friday email."""
import csv, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LABEL = {"seputeh": "Seputeh Hills", "status13": "Klang Valley"}


def read(path):
    p = os.path.join(ROOT, path)
    if not os.path.exists(p) or os.path.getsize(p) == 0:
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def num(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def main():
    short = "--short" in sys.argv          # compact one-screen version for WhatsApp
    projects = read("projects.csv")
    hist = read("data/teduh_history.csv")
    if not hist:
        print("No weekly data recorded yet.")
        return

    series = {}
    for r in hist:
        v = num(r.get("total_sold"))
        if v is not None:
            series.setdefault(r["code"], {})[r["week"]] = v
    weeks = sorted({r["week"] for r in hist})
    latest, prev = weeks[-1], (weeks[-2] if len(weeks) > 1 else None)

    if short:
        print(f"*TEDUH weekly update* - week of {latest}")
    else:
        print(f"TEDUH weekly update — week of {latest}")
        print()

    for key, label in LABEL.items():
        mine = [p for p in projects if p["tracker"] == key and (p.get("code") or "").strip()]
        if not mine:
            continue
        sold = units = new = 0
        movers = []
        for p in mine:
            s = series.get(p["code"], {})
            cur = s.get(latest)
            was = s.get(prev) if prev else None
            u = num(p.get("total_units")) or 0
            units += u
            if cur is not None:
                sold += cur
                if was is not None and cur - was:
                    new += cur - was
                    movers.append((cur - was, p["project"].replace("\n", " ").strip()))
        pct = f"{sold / units * 100:.1f}%" if units else "n/a"
        if short:
            top = ""
            if movers:
                movers.sort(reverse=True)
                top = "; top: " + ", ".join(f"{name.split('(')[0].strip()} {n:+d}"
                                            for n, name in movers[:2] if n)
            print(f"{label}: {new:+d} this week, {sold:,}/{units:,} sold ({pct}){top}")
            continue
        print(f"{label}")
        print(f"  {new:+d} units sold this week")
        print(f"  {sold:,} of {units:,} units sold to date ({pct})")
        if movers:
            movers.sort(reverse=True)
            top = ", ".join(f"{n} {name}" for n, name in movers[:5] if n)
            print(f"  Movers: {top}")
        else:
            print("  No movement this week")
        print()

    if short:
        print("Full report and spreadsheets sent by email.")
    else:
        print("Attached: the weekly PDF, the daily PDF, both weekly trackers and the day-by-day workbook.")
        print("The full dashboard is on the website.")


if __name__ == "__main__":
    main()
