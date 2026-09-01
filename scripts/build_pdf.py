#!/usr/bin/env python3
"""Build the TEDUH PDF report — one table per portfolio, nothing else.

  python3 scripts/build_pdf.py <projects.csv> <history.csv> <out.pdf> [--daily] [--periods N]

Weekly by default (last 4 recorded weeks, with a % column). With --daily it reads
the daily file, shows the last 5 snapshots and drops the % column, which is what
keeps five days of numbers legible at this page width. Tables only, on purpose:
this is meant to be skimmed and forwarded, not studied.
"""
import csv, os, sys
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (BaseDocTemplate, Frame, PageTemplate, Paragraph,
                                Spacer, Table, TableStyle, PageBreak)

AREA_LABEL = {"seputeh": "Seputeh Hills", "status13": "Klang Valley",
              "johor": "Johor", "ukay": "Ukay"}

# Kept under the old name in case anything else imports it.
LABEL = AREA_LABEL


def sections(projects, only=None):
    """[(tracker key, heading)] -- the four area sheets, then the developers A-Z.

    `only` is "areas" or "developers"; None means both. The two are split across
    separate PDFs because one file carrying four areas plus thirteen competitors
    runs to dozens of pages, and this report exists to be skimmed and forwarded.
    """
    labels, areas, devs = {}, [], []
    for p in projects:
        key = (p.get("tracker") or "").strip()
        if not key or key in labels:
            continue
        if key in AREA_LABEL:
            labels[key] = AREA_LABEL[key]
            areas.append(key)
        else:
            labels[key] = (p.get("tracker_label") or "").strip() or key.title()
            devs.append(key)
    areas.sort(key=lambda k: list(AREA_LABEL).index(k))
    devs.sort(key=lambda k: labels[k].lower())
    keys = {"areas": areas, "developers": devs}.get(only, areas + devs)
    return [(k, labels[k]) for k in keys]

BLUE = colors.HexColor("#2a78d6")
INK = colors.HexColor("#0b0b0b")
INK2 = colors.HexColor("#42413e")
MUTED = colors.HexColor("#6f6e69")
RULE = colors.HexColor("#c3c2b7")
GRID = colors.HexColor("#d8d7cf")
BAND = colors.HexColor("#f4f4f2")
HILITE = colors.HexColor("#e8f0fb")

S_TITLE = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=19, leading=23, textColor=INK)
S_SUB = ParagraphStyle("s", fontName="Helvetica", fontSize=10.5, leading=14, textColor=INK2)
S_H2 = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=INK,
                      spaceBefore=2, spaceAfter=3)
S_NOTE = ParagraphStyle("n", fontName="Helvetica", fontSize=9, leading=12, textColor=MUTED)
S_NAME = ParagraphStyle("c", fontName="Helvetica-Bold", fontSize=8.5, leading=9.8, textColor=INK)
S_DEV = ParagraphStyle("d", fontName="Helvetica", fontSize=8, leading=9.4, textColor=INK2)


def num(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def first_code(p):
    """The key a project's readings are filed under.

    A project spanning several phases stores them comma-joined -- Causewayz is
    "31100-1,31100-2,31100-3,31100-4" -- but the history is keyed by the first
    code alone, which is what build_trackers.py and build_dashboard.py both use.
    This script was looking the whole string up as one key, so every multi-code
    project printed as an empty row: Causewayz, M Grand Minori, Parkland,
    Sierra Hijauan, Nassim Heights.
    """
    return (p.get("code") or "").split(",")[0].strip()


def fdate(s, short=False):
    d = datetime.strptime(s, "%Y-%m-%d")
    return d.strftime("%d %b") if short else d.strftime("%d %b %Y")


def load(pcsv, hcsv, daily_csv=None):
    projects = list(csv.DictReader(open(pcsv, encoding="utf-8")))
    hist = list(csv.DictReader(open(hcsv, encoding="utf-8")))
    series = {}
    for r in hist:
        v = num(r.get("total_sold"))
        if v is not None:
            series.setdefault(r["code"], {})[r["week"]] = v
    dates = sorted({r["week"] for r in hist})

    # A project the scraper has only just started visiting has a daily reading
    # but no Friday record, so it would print as a row of blanks -- which is
    # what made the first competitor report look broken rather than new. Seed it
    # at the newest Friday so the reader gets a number. No NEW figure follows,
    # because there is no earlier week to subtract. Same rule as the website and
    # the Excel trackers.
    if daily_csv and os.path.exists(daily_csv):
        daily = list(csv.DictReader(open(daily_csv, encoding="utf-8")))
        if daily:
            latest_day = max(r["week"] for r in daily)
            dated_at = dates[-1] if dates else latest_day
            for r in daily:
                if r["week"] != latest_day or r["code"] in series:
                    continue
                v = num(r.get("total_sold"))
                if v is not None:
                    series[r["code"]] = {dated_at: v}
            if not dates:
                dates = [dated_at]
    return projects, series, dates


def build(pcsv, hcsv, out, daily=False, periods=4, only=None, seed_from=None):
    # Daily columns drop the percentage: it barely moves day to day, and dropping it
    # is what keeps the numbers from colliding at this width.
    show_pct = not daily
    per_period = 3 if show_pct else 2
    projects, series, all_dates = load(pcsv, hcsv, seed_from)
    if not all_dates:
        raise SystemExit("no data to report on")
    report_date = all_dates[-1]
    kind = "Daily" if daily else "Weekly"
    if only == "developers":
        kind += " developer"
    elif only == "areas":
        kind += " area"
    unit_word = "days" if daily else "weeks"

    page = landscape(A4)
    doc = BaseDocTemplate(out, pagesize=page,
                          leftMargin=14 * mm, rightMargin=14 * mm,
                          topMargin=13 * mm, bottomMargin=15 * mm,
                          title=f"TEDUH Competitor Tracker — {kind.lower()} report",
                          author="TEDUH Tracker")
    fw = page[0] - 28 * mm
    frame = Frame(14 * mm, 15 * mm, fw, page[1] - 28 * mm, id="f")

    def furniture(canvas, _doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(14 * mm, 9 * mm,
                          f"TEDUH Competitor Tracker  ·  {kind.lower()} report  ·  source: teduh.kpkt.gov.my")
        canvas.drawRightString(page[0] - 14 * mm, 9 * mm, "Page %d" % canvas.getPageNumber())
        canvas.setStrokeColor(GRID)
        canvas.setLineWidth(0.6)
        canvas.line(14 * mm, 12 * mm, page[0] - 14 * mm, 12 * mm)
        canvas.restoreState()

    doc.addPageTemplates([PageTemplate(id="all", frames=[frame], onPage=furniture)])

    story = [Paragraph(f"TEDUH Competitor Tracker — {kind.lower()} report", S_TITLE),
             Paragraph(f"{'Day' if daily else 'Week'} ending <b>{fdate(report_date)}</b>. "
                       f"Last {periods} recorded {unit_word} only, so this stays short enough to read.", S_SUB),
             Spacer(1, 9)]

    todo = sections(projects, only)
    for ti, (key, label) in enumerate(todo):
        mine = sorted((p for p in projects if p["tracker"] == key),
                      key=lambda x: (x.get("pin", "").strip().lower() not in ("yes", "y", "1", "true")))
        if not mine:
            continue
        codes = [c for c in (first_code(p) for p in mine) if c]
        have = sorted({d for c in codes for d in series.get(c, {})})
        if not have:
            continue
        cols = have[-periods:]
        prior = have[-(periods + 1)] if len(have) > periods else None
        latest = cols[-1]

        sold = units = moved = 0
        for p in mine:
            u = num(p.get("total_units")) or 0
            units += u
            cur = series.get(first_code(p), {}).get(latest)
            first = series.get(first_code(p), {}).get(cols[0])
            if cur is not None:
                sold += cur
                if first is not None:
                    moved += cur - first

        story += [Paragraph(label, S_H2),
                  Paragraph(f"{len(mine)} projects · {sold:,} of {units:,} units sold "
                            f"({sold / units * 100:.1f}%) · {moved:+,} over these {len(cols)} {unit_word}", S_NOTE),
                  Spacer(1, 5)]

        r1 = ["", "", "", "", ""]
        for d in cols:
            r1 += [fdate(d, True)] + [""] * (per_period - 1)
        heads = ["NEW", "SOLD", "%"] if show_pct else ["NEW", "SOLD"]
        r2 = ["#", "PROJECT", "DEVELOPER", "APDL", "UNITS"] + heads * len(cols)
        data = [r1, r2]
        section = None
        group_rows = set()
        for p in mine:
            if p.get("group") and p["group"] != section:
                section = p["group"]
                group_rows.add(len(data))
                data.append([section] + [""] * (4 + len(cols) * per_period))
            s = series.get(first_code(p), {})
            u = num(p.get("total_units")) or 0
            # "apdl", with "launched" only as a fallback. projects.csv renamed
            # this column on 01 Sep 2026 and this script was still reading the
            # old name, so every row in the PDF was printing an em dash.
            apdl = (p.get("apdl") or p.get("launched") or "").strip()
            row = [p["no"],
                   Paragraph(p["project"].replace("\n", " ").strip(), S_NAME),
                   Paragraph(p["developer"].replace("\n", " ").strip(), S_DEV),
                   datetime.strptime(apdl, "%Y-%m-%d").strftime("%b %Y") if apdl else "–",
                   f"{u:,}"]
            prev = s.get(prior) if prior else None
            for d in cols:
                cur = s.get(d)
                delta = (cur - prev) if (cur is not None and prev is not None) else None
                row += ["" if delta is None else f"{delta:+d}",
                        "" if cur is None else f"{cur:,}"]
                if show_pct:
                    row.append("" if (cur is None or not u) else f"{cur / u * 100:.1f}%")
                if cur is not None:
                    prev = cur
            data.append(row)

        fixed = [16, 116, 114, 54, 38]
        per = (fw - sum(fixed)) / (len(cols) * per_period)
        t = Table(data, colWidths=fixed + [per] * (len(cols) * per_period), repeatRows=2, hAlign="LEFT")
        style = [
            ("FONT", (0, 0), (-1, 1), "Helvetica-Bold", 7.5),
            ("FONT", (3, 2), (-1, -1), "Helvetica", 8),
            ("TEXTCOLOR", (0, 0), (-1, 1), INK2),
            ("BACKGROUND", (0, 0), (-1, 1), BAND),
            ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.5, GRID),
            ("BOX", (0, 0), (-1, -1), 0.9, RULE),
            ("LINEBELOW", (0, 1), (-1, 1), 0.9, RULE),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ]
        for i in range(len(cols)):
            c0 = 5 + i * per_period
            style += [("SPAN", (c0, 0), (c0 + per_period - 1, 0)),
                      ("ALIGN", (c0, 0), (c0 + per_period - 1, 0), "CENTER"),
                      ("LINEBEFORE", (c0, 0), (c0, -1), 0.9, RULE)]
        last0 = 5 + (len(cols) - 1) * per_period
        style.append(("BACKGROUND", (last0, 0), (last0 + per_period - 1, -1), HILITE))
        for r in range(2, len(data)):
            # Recorded as the group rows were written, rather than matched
            # against a hardcoded ("Permas Jaya", "JBCC") -- any other group
            # name silently lost its heading styling.
            if r in group_rows:
                style += [("SPAN", (0, r), (-1, r)),
                          ("BACKGROUND", (0, r), (-1, r), BAND),
                          ("FONT", (0, r), (-1, r), "Helvetica-Bold", 8.5),
                          ("ALIGN", (0, r), (-1, r), "LEFT")]
            elif r % 2 == 1:
                style.append(("BACKGROUND", (0, r), (4, r), BAND))
        t.setStyle(TableStyle(style))
        story += [t, Spacer(1, 12)]

        if ti < len(todo) - 1:
            story.append(PageBreak())

    doc.build(story)
    print(f"{out}  ({kind.lower()}, last {periods})")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    daily = "--daily" in flags
    periods = next((int(f.split("=")[1]) for f in flags if f.startswith("--periods=")),
                   5 if daily else 4)
    only = next((f.split("=")[1] for f in flags if f.startswith("--only=")), None)
    seed_from = next((f.split("=", 1)[1] for f in flags if f.startswith("--seed-from=")), None)
    if only not in (None, "areas", "developers"):
        raise SystemExit("--only= takes 'areas' or 'developers'")
    build(args[0], args[1], args[2], daily=daily, periods=periods, only=only,
          seed_from=seed_from)
