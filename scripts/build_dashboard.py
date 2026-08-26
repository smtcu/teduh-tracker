#!/usr/bin/env python3
"""Build a self-contained TEDUH competitor dashboard (docs/index.html).

Reads projects.csv + data/*.csv and inlines everything as JSON, so the output is
one HTML file with no network calls, no CDN, and no build step.

Usage: python3 scripts/build_dashboard.py
"""
import csv, json, os, html
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
MYT = timezone(timedelta(hours=8))

TRACKER_LABEL = {"seputeh": "Seputeh Hills", "status13": "Klang Valley", "johor": "Johor", "ukay": "Ukay"}


def read(path):
    p = os.path.join(ROOT, path)
    if not os.path.exists(p) or os.path.getsize(p) == 0:
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def remark_for(project, generated):
    """Remarks text: either a fixed override, or a standing caveat plus live numbers.

    `remarks` still wins outright, which is what Seputeh's unit-size notes and
    HillView's sale-scope note rely on. `note_prefix` is the other shape: a
    caveat that has to survive every rebuild while the block numbers after it
    keep updating -- Causewayz's unreleased Block C is the case that matters,
    because without it 1,421 of 3,692 reads as weak sales when 833 of those
    units are simply not on the market.
    """
    override = (project.get("remarks") or "").strip()
    if override:
        return override
    caveat = (project.get("note_prefix") or "").strip()
    return " ".join(part for part in (caveat, generated) if part)


def build_payload():
    projects = read("projects.csv")
    weekly = read("data/teduh_history.csv")
    utypes = read("data/teduh_unit_types_weekly.csv")
    daily = read("data/teduh_daily.csv") or weekly
    bytype = read("data/teduh_by_type.csv")

    def series_of(rows):
        out = {}
        for r in rows:
            v = to_int(r.get("total_sold"))
            if v is None:
                continue
            out.setdefault(r["code"] or "", {})[r["week"]] = v
        return out

    # Newest block note per project code, for the pinned Remarks column.
    notes = {}
    for r in sorted(weekly + daily, key=lambda x: x.get("week", "")):
        n = (r.get("block_note") or "").strip()
        if n:
            notes[r.get("code", "")] = n

    wser, dser = series_of(weekly), series_of(daily)

    types, types_date = {}, ""
    if bytype:
        tdates = {r["week"] for r in bytype}
        wlatest = max((d for s_ in wser.values() for d in s_), default="")
        types_date = wlatest if wlatest in tdates else max(tdates)
        for r in bytype:
            if r["week"] != types_date:
                continue
            types.setdefault(r["code"], []).append(
                {"type": r["unit_type"], "units": to_int(r["units"]) or 0, "sold": to_int(r["sold"]) or 0}
            )

    out = []
    for p in projects:
        codes = [c.strip() for c in (p.get("code") or "").split(",") if c.strip()]
        code = codes[0] if codes else ""
        key = code or f"NOCODE-{p.get('project','')}"
        wpts = sorted(wser.get(key, wser.get(code, {})).items())
        dpts = sorted(dser.get(key, dser.get(code, {})).items())
        units = to_int(p.get("total_units")) or 0
        latest = dpts[-1][1] if dpts else None
        prev = dpts[-2][1] if len(dpts) > 1 else None

        merged = {}
        for g in types.get(code, []):
            m = merged.setdefault(g["type"], {"type": g["type"], "units": 0, "sold": 0})
            m["units"] += g["units"]
            m["sold"] += g["sold"]

        wLast = wpts[-1][1] if wpts else None
        wPrev = wpts[-2][1] if len(wpts) > 1 else None
        out.append({
            "tracker": p["tracker"],
            "trackerLabel": TRACKER_LABEL.get(p["tracker"], p["tracker"]),
            "no": to_int(p.get("no")),
            "name": (p.get("project") or "").replace("\n", " ").strip(),
            "code": code,
            "developer": (p.get("developer") or "").strip(),
            "launched": p.get("launched") or "",
            "units": units,
            "group": (p.get("group") or "").strip(),
            "codes": codes,
            "unitKeys": [k.strip() for k in (p.get("unit_types") or "").split(",") if k.strip()],
            # `key`, not `code`: a project with no TEDUH code is filed under
            # "NOCODE-<project>" in the history, so looking it up by the blank
            # code silently lost its note (The Eclipse). build_trackers.py has
            # always used the NOCODE key, which is why the Excel kept the note
            # while the website dropped it.
            "remarks": remark_for(p, notes.get(key, "")),
            "pin": (p.get("pin") or "").strip().lower() in ("yes", "y", "1", "true"),
            "weekly": [{"d": d, "v": v} for d, v in wpts],
            "series": [{"d": d, "v": v} for d, v in dpts],
            "sold": latest,
            "newSales": (latest - prev) if (latest is not None and prev is not None) else None,
            "pct": (latest / units) if (latest is not None and units) else None,
            "wSold": wLast,
            "wNew": (wLast - wPrev) if (wLast is not None and wPrev is not None) else None,
            "wPct": (wLast / units) if (wLast is not None and units) else None,
            "todaySold": latest,
            "todayNew": (latest - wLast) if (latest is not None and wLast is not None) else None,
            "types": sorted(merged.values(), key=lambda x: -x["units"]),
        })

    # Unit-type tables, laid out like the Project Sales Insight pages of the report.
    import json as _json
    spec_path = os.path.join(ROOT, "unit_types.json")
    spec = _json.load(open(spec_path, encoding="utf-8")) if os.path.exists(spec_path) else {}
    insight = []
    for pkey, meta in spec.items():
        rows_ = [r for r in utypes if r.get("project_key") == pkey]
        if not rows_:
            continue
        wks = sorted({r["week"] for r in rows_})
        got = {(r["week"], r["unit_type"]): to_int(r["sold"]) for r in rows_}
        insight.append({
            "key": pkey,
            "label": meta.get("label", pkey),
            "types": meta.get("types", []),
            "weeks": wks,
            "sold": [[got.get((w, t["key"])) for t in meta.get("types", [])] for w in wks],
        })

    weeks = sorted({d for s in wser.values() for d in s})
    days = sorted({d for s in dser.values() for d in s})
    return {
        "generated": datetime.now(MYT).strftime("%d %b %Y, %-I:%M %p") + " MYT",
        "latestDate": days[-1] if days else "",
        "prevDate": days[-2] if len(days) > 1 else "",
        "dates": days,
        "weeks": weeks,
        "weekLatest": weeks[-1] if weeks else "",
        "typesDate": types_date,
        "todayDate": days[-1] if days else "",
        "projects": out,
        "insight": insight,
    }


TEMPLATE = r"""<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="robots" content="noindex, nofollow">
<meta name="theme-color" content="#2a78d6">
<title>TEDUH Competitor Tracker</title>
<style>
:root{
  color-scheme:light;
  --plane:#f4f4f2; --surface:#fcfcfb; --sunk:#f0efec;
  --ink:#0b0b0b; --ink-2:#42413e; --muted:#6f6e69;
  --grid:#d8d7cf; --rule:#c3c2b7; --border:rgba(11,11,11,.16);
  --blue:#2a78d6; --orange:#eb6834; --track:#cde2fb;
  --hl:rgba(42,120,214,.09); --pinbg:#eaf2fd;
  --shadow:0 1px 2px rgba(11,11,11,.05),0 6px 20px rgba(11,11,11,.06);
}
html[data-theme="dark"]{
  color-scheme:dark;
  --plane:#0d0d0d; --surface:#1a1a19; --sunk:#232322;
  --ink:#fff; --ink-2:#d4d3c9; --muted:#9d9c94;
  --grid:#35352f; --rule:#45453f; --border:rgba(255,255,255,.18);
  --blue:#3987e5; --orange:#d95926; --track:#184f95;
  --hl:rgba(57,135,229,.16); --pinbg:#16304f;
  --shadow:none;
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{
  margin:0;background:var(--plane);color:var(--ink);
  font:500 15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;
  -webkit-font-smoothing:antialiased;-webkit-text-size-adjust:100%;
}
.wrap{max-width:1280px;margin:0 auto;padding:20px 16px 64px}
header{display:flex;gap:14px;align-items:flex-start;justify-content:space-between;margin-bottom:16px}
h1{font-size:21px;font-weight:750;margin:0;letter-spacing:-.02em;line-height:1.2}
.sub{color:var(--ink-2);font-size:13.5px;margin-top:5px;font-weight:500}
.sub b{color:var(--ink);font-weight:750}
h2{font-size:17px;font-weight:750;margin:0 0 4px;letter-spacing:-.015em}
.note{color:var(--muted);font-size:13px;margin:0 0 16px;font-weight:500}
.card{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:18px;margin-bottom:16px;box-shadow:var(--shadow)}
button,.btn{font:inherit;color:inherit;cursor:pointer}
.ghost{background:var(--surface);border:1.5px solid var(--border);border-radius:10px;padding:9px 15px;font-size:13.5px;font-weight:650;color:var(--ink-2);min-height:40px}
.ghost:hover{background:var(--sunk)}
.ghost[aria-pressed="true"]{background:var(--blue);border-color:var(--blue);color:#fff}

/* project picker */
.chips{display:flex;flex-wrap:wrap;gap:7px;margin:2px 0 16px}
.chip{background:var(--sunk);border:1.5px solid transparent;border-radius:9px;padding:8px 12px;font-size:13px;font-weight:650;color:var(--ink-2);min-height:38px}
.chip[aria-pressed="true"]{background:var(--blue);color:#fff}
.chips .lbl{width:100%;font-size:11.5px;font-weight:750;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin:6px 0 -2px}

.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:12px;margin-bottom:16px}
.kpi{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:15px 16px;box-shadow:var(--shadow)}
.kpi .l{font-size:12.5px;color:var(--ink-2);font-weight:650}
.kpi .v{font-size:30px;font-weight:750;letter-spacing:-.025em;margin-top:4px;line-height:1.12}
.kpi .d{font-size:12.5px;color:var(--muted);margin-top:3px;font-weight:600}
.hero .v{font-size:46px}

svg{display:block;overflow:visible}
.gl{stroke:var(--grid);stroke-width:1}
.ax{stroke:var(--rule);stroke-width:1}
.tk{fill:var(--muted);font-size:11.5px;font-weight:650;font-variant-numeric:tabular-nums}
.vlab{fill:var(--ink);font-size:12.5px;font-weight:750;font-variant-numeric:tabular-nums}
.clab{fill:var(--ink-2);font-size:12.5px;font-weight:600}
.hit{fill:transparent;cursor:pointer}
.mark{transition:opacity .12s}
.mark:hover{opacity:.82}
.lg{display:flex;gap:16px;flex-wrap:wrap;margin:0 0 12px;font-size:12.5px;color:var(--ink-2);font-weight:650}
.lg span{display:inline-flex;align-items:center;gap:7px}
.sw{width:12px;height:12px;border-radius:3px;flex:none}
.swl{width:16px;height:3px;border-radius:2px;flex:none}

/* tables */
.scroll{overflow:auto;border:1.5px solid var(--rule);border-radius:12px;-webkit-overflow-scrolling:touch}
.tall{max-height:70vh}
table{border-collapse:separate;border-spacing:0;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
th,td{padding:9px 11px;text-align:right;border-right:1px solid var(--grid);border-bottom:1px solid var(--grid);white-space:nowrap;font-weight:600}
th{color:var(--ink-2);font-weight:750;font-size:11.5px;letter-spacing:.02em;background:var(--sunk);position:sticky;top:0;z-index:3}
th.r2{top:34px}
th.l,td.l{text-align:left}
td.nm{font-weight:700;color:var(--ink)}
.grpcell{background:var(--sunk);font-weight:800;font-size:11.5px;letter-spacing:.07em;text-transform:uppercase;color:var(--ink-2);border-right:0}
.wk{border-left:2px solid var(--rule)}
.new{background:var(--hl)}
.live{background:rgba(235,104,52,.10)}
html[data-theme="dark"] .live{background:rgba(217,89,38,.18)}
/* The header row is position:sticky, so its background has to be fully opaque --
   a translucent one lets the rows scrolling underneath show straight through it.
   These two columns are tinted, so paint the tint as a gradient layer on top of
   an opaque base instead of as a see-through background colour. Same colour on
   screen, but nothing bleeds through. */
th.new{background-color:var(--sunk);background-image:linear-gradient(var(--hl),var(--hl))}
th.live{background-color:var(--sunk);
  background-image:linear-gradient(rgba(235,104,52,.16),rgba(235,104,52,.16))}
html[data-theme="dark"] th.live{background-color:var(--sunk);
  background-image:linear-gradient(rgba(217,89,38,.26),rgba(217,89,38,.26))}
.live-card{border-left:4px solid var(--orange)}
.livehd{border-left:2px solid var(--orange)!important}
.rem{position:sticky;right:0;z-index:3;background:var(--surface);
  border-left:2px solid var(--rule);max-width:230px;min-width:230px;
  white-space:normal;line-height:1.32;font-weight:600;font-size:11.8px}
th.rem{z-index:5;background:var(--sunk)}
tbody tr:hover td.rem{background:var(--sunk)}
tr.pinned td.rem{background:var(--pinbg)}
tr.noterow{display:none}
tr.pinned+tr.noterow td{background:var(--pinbg)}
.ins{margin-top:6px}
.ins h3{font-size:14.5px;font-weight:750;margin:18px 0 2px;letter-spacing:-.01em}
.ins .sz{font-weight:600;color:var(--muted);font-size:11px;display:block}
.ins table{margin-top:8px}
.ins td.lbl,.ins th.lbl{text-align:left;font-weight:750}
.ins tr.tot td{background:var(--sunk);font-weight:750}
.ins tr.sep td{border-top:2px solid var(--rule)}
.ins tr.newweek td{background:var(--hl)}
.ins tr.newweek td.lbl{font-weight:750}
.ins tr.newweek.sep td{border-top:2px solid var(--blue)}
.ins tr.older td{background:var(--surface)}
td.live-card{border-left:4px solid var(--orange)}
tbody tr:hover td:not(.stick){background:var(--sunk)}
.stick,.stick2,.stick3{position:sticky;background:var(--surface);z-index:2}
tr.pinned td{position:sticky;z-index:3;background:var(--pinbg);
  border-top:2px solid var(--blue);border-bottom:2px solid var(--blue);font-weight:700}
tr.pinned td.stick,tr.pinned td.stick2,tr.pinned td.stick3{z-index:4;background:var(--pinbg)}
tbody tr.pinned:hover td{background:var(--pinbg)}
tr.pinned td.nm::after{content:" \2605";color:var(--blue)}
.stick{left:0;width:38px;min-width:38px}
.stick2{left:38px;width:196px;min-width:196px;max-width:196px;white-space:normal;line-height:1.32}
.stick3{left:234px;width:64px;min-width:64px;max-width:64px;border-right:2px solid var(--rule)}
th.stick3,th.stick2{white-space:normal;line-height:1.25}
th.stick,th.stick2,th.stick3{z-index:4;background:var(--sunk)}
tbody tr:hover .stick,tbody tr:hover .stick2,tbody tr:hover .stick3{background:var(--sunk)}
tr:last-child td{border-bottom:0}

.tip{position:fixed;pointer-events:none;opacity:0;transition:opacity .1s;background:var(--surface);border:1.5px solid var(--border);border-radius:10px;padding:10px 12px;box-shadow:0 8px 28px rgba(0,0,0,.2);font-size:12.5px;z-index:50;max-width:250px;font-weight:600}
.tip .tv{font-size:15.5px;font-weight:750;font-variant-numeric:tabular-nums}
.tip .tn{color:var(--ink-2);margin-top:1px;font-weight:600}
.tip .tr{display:flex;align-items:center;gap:8px;margin-top:5px}
.tip .key{width:14px;height:3px;border-radius:2px;flex:none}

.sm{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:9px}
.smc{padding:12px;border:1px solid var(--border);border-radius:11px;background:var(--surface)}
.smc .t{font-size:12.5px;font-weight:750;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.smc .m{font-size:12px;color:var(--muted);margin-top:2px;font-variant-numeric:tabular-nums;font-weight:650}
.sel{display:none;width:100%;font:inherit;font-weight:650;color:var(--ink);background:var(--surface);
  border:1.5px solid var(--border);border-radius:10px;padding:11px 12px;min-height:44px;margin:2px 0 14px}
.compact .opt{display:none}
.tbar{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.bar{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}
.bar button{flex:1 1 auto;min-width:150px}
#pickedName{margin:2px 0 13px}
#pickedName .pn{display:block;font-size:19px;font-weight:750;letter-spacing:-.015em}
#pickedName .pd{display:block;font-size:13px;font-weight:650;color:var(--muted);margin-top:2px}
.dl{display:flex;gap:10px;flex-wrap:wrap}
.dl a{text-decoration:none;display:inline-flex;align-items:center}
.foot{color:var(--muted);font-size:12.5px;margin-top:22px;line-height:1.7;font-weight:500}
.hide{display:none!important}

@media(max-width:640px){
  .wrap{padding:14px 11px 52px}
  h1{font-size:19px} h2{font-size:16px}
  .card{padding:14px;border-radius:12px}
  .kpis{grid-template-columns:repeat(2,1fr);gap:9px}
  .kpi{padding:12px 13px} .kpi .v{font-size:25px} .hero .v{font-size:32px}
  .sm{grid-template-columns:1fr 1fr;gap:8px}
  table{font-size:12.5px} th,td{padding:8px 9px}
  th,td{padding:7px 7px}
  .stick{width:26px;min-width:26px}
  .stick2{left:26px;max-width:98px;min-width:98px;font-size:11.5px}
  .stick3{left:124px;width:46px;min-width:46px;max-width:46px;font-size:11.5px}
  /* On phones the Remarks column is replaced by a full-width line under each
     project, and the # column is dropped -- together they were leaving 12px of
     338px for the actual figures. */
  .rem{display:none}
  .stick{display:none}
  .stick2{left:0;max-width:112px;min-width:112px}
  .stick3{left:112px}
  tr.noterow{display:table-row}
  tr.noterow td{background:var(--sunk);border-right:0;padding:0}
  tr.noterow .notebox{position:sticky;left:0;width:calc(100vw - 46px);
    white-space:normal;line-height:1.35;font-size:11.5px;font-weight:600;
    color:var(--ink-2);padding:7px 10px;box-sizing:border-box}
  tr.noterow .notebox b{font-weight:750;color:var(--muted);letter-spacing:.04em;font-size:10px}
  th{font-size:10.5px;letter-spacing:.01em}
  .sel{display:block} .chips{display:none}
  .scroll.tall{max-height:64vh}
}
@media print{.ghost,.chips,.tip{display:none!important}.card{break-inside:avoid;box-shadow:none}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <div>
    <h1>TEDUH Competitor Tracker</h1>
    <div class="sub">Data as at <b id="asat"></b> · refreshed daily</div>
  </div>
  <button class="ghost" id="theme">Dark</button>
</header>

<div class="bar" id="ftrack"></div>

<div class="card">
  <h2>Weekly tracker</h2>
  <p class="note" id="tblnote"></p>
  <div class="tbar"><button class="ghost" id="cols">Show all columns</button></div>
  <div class="scroll tall" id="table"></div>
</div>

<div class="card">
  <h2>Weekly sales by project</h2>
  <p class="note">Weekly figures only, exactly as they appear in your Excel sheets — today's live number is not mixed in. Bars are units sold in that week; the line is the project's four-week average pace, so a bar above the line means it beat its recent run rate.</p>
  <select class="sel" id="pickSel" aria-label="Choose a project"></select>
  <div class="chips" id="picker"></div>
  <div id="pickedName"></div>
  <div class="kpis" id="pkpis" style="margin-bottom:14px"></div>
  <div class="lg">
    <span><i class="sw" style="background:var(--blue)"></i>Units sold that week</span>
    <span><i class="swl" style="background:var(--orange)"></i>4-week average pace</span>
  </div>
  <div id="weekly"></div>
  <div style="margin-top:12px" id="weekly-t"></div>
</div>

<div class="card hide" id="inscard">
  <h2>Project sales insight (Permas Jaya)</h2>
  <p class="note">Sold units by type, newest week first. The underlying unit-by-unit working is in the downloadable unit-type workbook.</p>
  <div class="ins" id="insight"></div>
</div>

<div class="card" id="btcard">
  <h2>Sold and unsold</h2>
  <p class="note" id="btnote"></p>
  <div class="lg"><span><i class="sw" style="background:var(--blue)"></i>Sold</span><span><i class="sw" style="background:var(--track)"></i>Unsold</span></div>
  <div id="bytype"></div>
</div>

<h2 style="margin:26px 0 2px">Whole portfolio</h2>
<p class="note" id="kpinote"></p>
<div class="kpis" id="kpis"></div>

<div class="card live-card">
  <h2>Movement since the last weekly record</h2>
  <p class="note" id="mvnote"></p>
  <div id="movers"></div>
  <button class="ghost" data-tbl="movers" style="margin-top:12px">Show as table</button>
  <div id="movers-t" style="display:none;margin-top:12px"></div>
</div>

<div class="card">
  <h2>Sell-through</h2>
  <p class="note" id="stnote"></p>
  <div id="sellthru"></div>
</div>

<div class="card">
  <h2>Cumulative units sold over time</h2>
  <p class="note">One panel per project. A steep line means fast selling, a flat line means nothing is moving. Each panel has its own scale, so read the numbers, not the height. A sharp dip to zero is a gap in the imported history, not a real reversal.</p>
  <div class="sm" id="trends"></div>
</div>

<div class="card">
  <h2>Download</h2>
  <p class="note">The two PDFs are table-only summaries meant for forwarding. The weekly PDF and the two Excel trackers are rebuilt every Friday; the daily PDF and daily workbook are rebuilt every morning.</p>
  <div class="dl">
    <a class="ghost" href="downloads/TEDUH_Weekly_Report.pdf" download>Weekly report, 4 weeks (.pdf)</a>
    <a class="ghost" href="downloads/TEDUH_Daily_Report.pdf" download>Daily report, 5 days (.pdf)</a>
    <a class="ghost" href="downloads/Seputeh_Hills_Teduh_Weekly_Update.xlsx" download>Seputeh Hills tracker (.xlsx)</a>
    <a class="ghost" href="downloads/Tduh_Developer_Project_Sales_Status.xlsx" download>Klang Valley tracker (.xlsx)</a>
    <a class="ghost" href="downloads/Johor_Teduh_Weekly_Update.xlsx" download>Johor tracker (.xlsx)</a>
    <a class="ghost" href="downloads/TEDUH_Unit_Types.xlsx" download>Unit types &amp; unit list (.xlsx)</a>
    <a class="ghost" href="downloads/Teduh_Daily_Tracker.xlsx" download>Daily tracker (.xlsx)</a>
    <a class="ghost" href="data/teduh_daily.csv" download>Raw data (.csv)</a>
  </div>
</div>

<div class="foot" id="foot"></div>
</div>

<div class="tip" id="tip" role="status" aria-live="polite"></div>

<script id="data" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById('data').textContent);
const $ = s => document.querySelector(s);
const nf = n => (n === null || n === undefined) ? '–' : n.toLocaleString('en-US');
const pf = n => (n === null || n === undefined) ? '–' : (n * 100).toFixed(1) + '%';
const sgn = n => (n === null || n === undefined) ? '' : (n > 0 ? '+' + n : String(n));
const el = (t, c, txt) => { const e = document.createElement(t); if (c) e.className = c; if (txt !== undefined) e.textContent = txt; return e; };
const fdate = (s, short) => { if (!s) return ''; const d = new Date(s + 'T00:00:00');
  return d.toLocaleDateString('en-GB', short ? { day: '2-digit', month: 'short' } : { day: '2-digit', month: 'short', year: 'numeric' }); };
const SVGNS = 'http://www.w3.org/2000/svg';
const sv = (t, a) => { const e = document.createElementNS(SVGNS, t); for (const k in a) e.setAttribute(k, a[k]); return e; };
const trunc = (s, n) => s.length > n ? s.slice(0, n - 1) + '…' : s;
const wide = () => Math.min(1240, ($('#movers').clientWidth || 860));

/* ---------- tooltip ---------- */
const tip = $('#tip');
function showTip(ev, rows, title) {
  tip.textContent = '';
  if (title) tip.appendChild(el('div', 'tn', title));
  rows.forEach(r => {
    const line = el('div', 'tr');
    if (r.color) { const k = el('span', 'key'); k.style.background = r.color; line.appendChild(k); }
    line.appendChild(el('span', 'tv', r.value));
    if (r.label) { const l = el('span', 'tn'); l.textContent = r.label; l.style.marginTop = '0'; line.appendChild(l); }
    tip.appendChild(line);
  });
  tip.style.opacity = '1';
  const w = 240;
  let x = ev.clientX + 14, y = ev.clientY + 14;
  if (x + w > innerWidth) x = Math.max(8, ev.clientX - w - 14);
  if (y + 130 > innerHeight) y = Math.max(8, ev.clientY - 130);
  tip.style.left = x + 'px'; tip.style.top = y + 'px';
}
const hideTip = () => { tip.style.opacity = '0'; };
addEventListener('scroll', hideTip, true);

const ALL = DATA.projects;
const TRACKERS = [];
ALL.forEach(p => { if (!TRACKERS.some(t => t.key === p.tracker)) TRACKERS.push({ key: p.tracker, label: p.trackerLabel }); });
let tracker = TRACKERS.length ? TRACKERS[0].key : '';
let picked = 0;
/* Pinned projects lead their tracker and stay visible while the table scrolls. */
const vis = () => ALL.filter(p => p.tracker === tracker)
                     .sort((a, b) => (b.pin === true) - (a.pin === true));

function trackerBar() {
  const host = $('#ftrack'); host.textContent = '';
  TRACKERS.forEach(t => {
    const b = el('button', 'ghost', t.label);
    b.setAttribute('aria-pressed', String(t.key === tracker));
    b.onclick = () => { tracker = t.key; picked = 0; render(); };
    host.appendChild(b);
  });
}

/* ---------- weekly tracker table (mirrors the Excel sheet) ---------- */
function table() {
  const host = $('#table'); host.textContent = '';
  const weeks = DATA.weeks.slice().reverse();      // newest first
  /* Today only earns a column when it is not already the newest Friday. */
  const live = DATA.todayDate && DATA.todayDate !== DATA.weekLatest;
  $('#tblnote').textContent = live
    ? 'The orange column is today, updated every morning. Everything after it is the weekly record that feeds your Excel sheets, newest week first.'
    : 'Newest week first, matching your Excel sheets. Scroll sideways for earlier weeks.';

  const tb = el('table');
  const r1 = el('tr'), r2 = el('tr');
  const fixed = [['#', 'stick'], ['PROJECT', 'stick2'], ['TOTAL UNITS', 'stick3'],
                 ['CODE', 'opt'], ['DEVELOPER', 'opt'], ['LAUNCHED', 'opt']];
  fixed.forEach(([label, cls], i) => {
    const th = el('th', (cls ? cls + ' ' : '') + (i < 5 ? 'l' : ''), label);
    th.rowSpan = 2; r1.appendChild(th);
  });
  if (live) {
    const th = el('th', 'live livehd', 'TODAY · ' + fdate(DATA.todayDate, true));
    th.colSpan = 3; r1.appendChild(th);
  }
  weeks.forEach((w, i) => {
    const th = el('th', 'wk' + (i === 0 ? ' new' : ''), fdate(w, true));
    th.colSpan = 3; r1.appendChild(th);
  });
  /* Remarks is pinned to the right edge, so it stays readable however far you scroll. */
  const thRem = el('th', 'l rem', 'REMARKS'); thRem.rowSpan = 2; r1.appendChild(thRem);
  const showRemarks = vis().some(p => p.remarks);
  if (!showRemarks) thRem.style.display = 'none';
  if (live) {
    r2.appendChild(el('th', 'r2 live livehd', 'NEW'));
    r2.appendChild(el('th', 'r2 live', 'SOLD'));
    r2.appendChild(el('th', 'r2 live', '%'));
  }
  weeks.forEach((w, i) => {
    const n = i === 0 ? ' new' : '';
    r2.appendChild(el('th', 'r2 wk' + n, 'NEW'));
    r2.appendChild(el('th', 'r2' + n, 'SOLD'));
    r2.appendChild(el('th', 'r2' + n, '%'));
  });
  const th = el('thead'); th.appendChild(r1); th.appendChild(r2); tb.appendChild(th);

  const bd = el('tbody');
  let section = null;
  vis().forEach(p => {
    if (p.group && p.group !== section) {
      section = p.group;
      const gr = el('tr');
      const gc = el('td', 'l grpcell', section);
      gc.colSpan = 12 + weeks.length * 3;
      gr.appendChild(gc); bd.appendChild(gr);
    }
    const tr = el('tr', p.pin ? 'pinned' : '');
    tr.appendChild(el('td', 'l stick', String(p.no ?? '')));
    tr.appendChild(el('td', 'l stick2 nm', p.name));
    tr.appendChild(el('td', 'stick3', nf(p.units)));
    tr.appendChild(el('td', 'l opt', p.code || '–'));
    tr.appendChild(el('td', 'l opt', p.developer));
    tr.appendChild(el('td', 'l opt', p.launched ? fdate(p.launched) : '–'));

    const map = {}; p.weekly.forEach(s => map[s.d] = s.v);
    const delta = {}; let prev = null;
    DATA.weeks.forEach(d => {                       // chronological, for correct deltas
      const v = map[d]; if (v === undefined) return;
      if (prev !== null) delta[d] = v - prev;
      prev = v;
    });
    if (live) {
      tr.appendChild(el('td', 'live livehd', p.todayNew === null || p.todayNew === undefined ? '' : sgn(p.todayNew)));
      tr.appendChild(el('td', 'live', p.todaySold === null ? '' : nf(p.todaySold)));
      tr.appendChild(el('td', 'live', (p.todaySold === null || !p.units) ? '' : pf(p.todaySold / p.units)));
    }
    weeks.forEach((d, i) => {
      const n = i === 0 ? ' new' : '';
      const v = map[d] === undefined ? null : map[d];
      tr.appendChild(el('td', 'wk' + n, delta[d] === undefined ? '' : sgn(delta[d])));
      tr.appendChild(el('td', n, v === null ? '' : nf(v)));
      tr.appendChild(el('td', n, (v === null || !p.units) ? '' : pf(v / p.units)));
    });
    const rem = el('td', 'l rem', p.remarks || '');
    if (!showRemarks) rem.style.display = 'none';
    tr.appendChild(rem);
    bd.appendChild(tr);

    /* Phone-only twin of the Remarks cell: a full-width line that stays put
       while the week columns scroll sideways. Hidden on desktop by CSS. */
    const noteText = (p.remarks || '').trim();
    if (noteText && noteText !== '-') {
      const nr = el('tr', 'noterow' + (p.pin ? ' pinnedNote' : ''));
      const nc = el('td', 'l');
      nc.colSpan = 12 + weeks.length * 3;
      const box = el('div', 'notebox');
      box.appendChild(el('b', '', 'Note '));
      box.appendChild(document.createTextNode(noteText));
      nc.appendChild(box);
      nr.appendChild(nc);
      bd.appendChild(nr);
    }
  });
  tb.appendChild(bd); host.appendChild(tb);
  host.classList.toggle('compact', compact);
  /* The header is two rows of variable height, so measure it rather than guess. */
  requestAnimationFrame(() => {
    const head = tb.querySelector('thead');
    const row = tb.querySelector('tr.pinned');
    if (head && row) {
      const top = head.getBoundingClientRect().height;
      row.querySelectorAll('td').forEach(td => { td.style.top = top + 'px'; });
    }
  });
}

/* Narrow screens start compact so the newest week's numbers are visible without scrolling. */
let compact = innerWidth < 640;
$('#cols').textContent = compact ? 'Show all columns' : 'Compact columns';
$('#cols').onclick = () => {
  compact = !compact;
  $('#cols').textContent = compact ? 'Show all columns' : 'Compact columns';
  $('#table').classList.toggle('compact', compact);
};

/* ---------- project picker (chips on desktop, dropdown on phones) ---------- */
function insight() {
  const card = $('#inscard'), host = $('#insight');
  host.textContent = '';
  const blocks = (DATA.insight || []).filter(b => vis().some(p => (p.unitKeys || []).includes(b.key)));
  card.classList.toggle('hide', blocks.length === 0);
  if (!blocks.length) return;

  blocks.forEach(b => {
    const h = el('h3', '', b.label); host.appendChild(h);
    const total = b.types.reduce((a, t) => a + (t.total || 0), 0);
    const tb = el('table');
    const hr = el('tr');
    hr.appendChild(el('th', 'lbl', 'UNIT TYPE'));
    b.types.forEach(t => {
      const th = el('th', '', t.key);
      const sz = el('span', 'sz', t.size); th.appendChild(sz);
      hr.appendChild(th);
    });
    hr.appendChild(el('th', '', 'TOTAL'));
    tb.appendChild(el('thead')).appendChild(hr);

    const bd = el('tbody');
    const totRow = el('tr', 'tot');
    totRow.appendChild(el('td', 'lbl', 'TOTAL UNITS'));
    b.types.forEach(t => totRow.appendChild(el('td', '', nf(t.total))));
    totRow.appendChild(el('td', '', nf(total)));
    bd.appendChild(totRow);

    const order = b.weeks.slice().reverse();       // newest first
    const SHOWN = 4;                               // older weeks stay collapsed
    order.forEach((w, i) => {
      const idx = b.weeks.indexOf(w);
      const prevIdx = idx - 1;
      const row = b.sold[idx] || [];
      const prev = prevIdx >= 0 ? (b.sold[prevIdx] || []) : null;
      const sum = row.reduce((a, v) => a + (v || 0), 0);
      const psum = prev ? prev.reduce((a, v) => a + (v || 0), 0) : null;

      const latest = i === 0;
      const older = i >= SHOWN;
      const mk = (label, vals, tot, cls) => {
        const tr = el('tr', [cls || '', latest ? 'newweek' : '', older ? 'older hide' : ''].join(' ').trim());
        tr.appendChild(el('td', 'lbl', label));
        vals.forEach(v => tr.appendChild(el('td', '', v)));
        tr.appendChild(el('td', '', tot));
        bd.appendChild(tr);
      };
      mk(fdate(w), row.map((v, j) => prev ? sgn((v || 0) - (prev[j] || 0)) : '–'),
         prev ? sgn(sum - psum) : '–', 'sep');
      mk('Total sold', row.map(v => nf(v)), nf(sum));
      mk('Total %', row.map((v, j) => b.types[j].total ? pf((v || 0) / b.types[j].total) : '–'),
         total ? pf(sum / total) : '–');
    });
    tb.appendChild(bd);
    const wrap = el('div', 'scroll'); wrap.appendChild(tb); host.appendChild(wrap);

    const hidden = order.length - SHOWN;
    if (hidden > 0) {
      const btn = el('button', 'ghost', `Show ${hidden} earlier week${hidden > 1 ? 's' : ''}`);
      btn.style.marginTop = '10px';
      let open = false;
      btn.onclick = () => {
        open = !open;
        tb.querySelectorAll('tr.older').forEach(tr => tr.classList.toggle('hide', !open));
        btn.textContent = open ? 'Hide earlier weeks'
                               : `Show ${hidden} earlier week${hidden > 1 ? 's' : ''}`;
      };
      host.appendChild(btn);
    }
  });
}

function picker() {
  const list = vis();
  if (picked >= list.length) picked = 0;
  const host = $('#picker'); host.textContent = '';
  list.forEach((p, i) => {
    const b = el('button', 'chip', trunc(p.name, 26));
    b.title = p.name + ' — ' + p.developer;
    b.setAttribute('aria-pressed', String(i === picked));
    b.onclick = () => { picked = i; picker(); weekly(); };
    host.appendChild(b);
  });
  const sel = $('#pickSel'); sel.textContent = '';
  list.forEach((p, i) => {
    const o = el('option', '', p.name); o.value = String(i);
    if (i === picked) o.selected = true;
    sel.appendChild(o);
  });
  sel.onchange = () => { picked = Number(sel.value); picker(); weekly(); };
}

/* ---------- weekly bars + average-pace line ---------- */
function weeklyPoints(p, n) {
  const pts = p.weekly;
  const out = [];
  for (let i = 1; i < pts.length; i++) out.push({ d: pts[i].d, v: pts[i].v - pts[i - 1].v, total: pts[i].v });
  const tail = out.slice(-n);
  return tail.map((pt, k) => {
    const idx = out.length - tail.length + k;
    const win = out.slice(Math.max(0, idx - 3), idx + 1);
    return { ...pt, avg: win.reduce((a, b) => a + b.v, 0) / win.length };
  });
}

function pkpis(p, pts) {
  const box = $('#pkpis'); box.textContent = '';
  const last = pts.length ? pts[pts.length - 1] : null;
  const add = (l, v, d, hero) => {
    const c = el('div', 'kpi' + (hero ? ' hero' : ''));
    c.appendChild(el('div', 'l', l)); c.appendChild(el('div', 'v', v));
    if (d) c.appendChild(el('div', 'd', d)); box.appendChild(c);
  };
  add('Sold this week', last ? sgn(last.v) : '–', last ? 'week of ' + fdate(last.d) : '', true);
  add('Total sold', nf(p.wSold), 'of ' + nf(p.units) + ' units');
  add('Sell-through', pf(p.wPct), 'this project alone, at ' + fdate(DATA.weekLatest));
  add('Still unsold', p.wSold === null ? '–' : nf(p.units - p.wSold), 'units remaining');
}

function weekly() {
  const list = vis();
  const p = list[picked] || list[0];
  if (!p) return;
  const cap = $('#pickedName');
  cap.textContent = '';
  cap.appendChild(el('span', 'pn', p.name));
  cap.appendChild(el('span', 'pd', p.developer + (p.code ? '  ·  ' + p.code : '')));
  const host = $('#weekly'); host.textContent = '';
  const pts = weeklyPoints(p, 4);
  pkpis(p, pts);
  if (!pts.length) {
    host.appendChild(el('p', 'note', 'Not enough weekly history for this project yet.'));
    $('#weekly-t').textContent = ''; return;
  }
  const W = wide(), H = 240, PL = 44, PR = 16, PT = 22, PB = 40;
  const plotW = W - PL - PR, plotH = H - PT - PB;
  const max = Math.max(1, ...pts.map(d => Math.max(d.v, d.avg)));
  const step = Math.max(1, Math.ceil(max / 4));
  const top = step * 4;
  const Y = v => PT + (1 - v / top) * plotH;
  const band = plotW / pts.length;
  const bw = Math.min(24, band * 0.5);

  const svg = sv('svg', { width: '100%', viewBox: `0 0 ${W} ${H}`, role: 'img' });
  for (let t = 0; t <= top; t += step) {
    svg.appendChild(sv('line', { x1: PL, y1: Y(t), x2: W - PR, y2: Y(t), class: t === 0 ? 'ax' : 'gl' }));
    const tk = sv('text', { x: PL - 9, y: Y(t) + 4, 'text-anchor': 'end', class: 'tk' });
    tk.textContent = nf(t); svg.appendChild(tk);
  }
  pts.forEach((d, i) => {
    const cx = PL + band * (i + 0.5);
    const h = Math.max(d.v > 0 ? 3 : 0, (d.v / top) * plotH);
    if (h > 0) svg.appendChild(sv('rect', { x: cx - bw / 2, y: Y(d.v), width: bw, height: h, rx: 4, fill: 'var(--blue)', class: 'mark' }));
    const cap = sv('text', { x: cx, y: Y(d.v) - 8, 'text-anchor': 'middle', class: 'vlab' });
    cap.textContent = nf(d.v); svg.appendChild(cap);
    const xl = sv('text', { x: cx, y: H - PB + 20, 'text-anchor': 'middle', class: 'tk' });
    xl.textContent = fdate(d.d, true); svg.appendChild(xl);
  });
  const path = pts.map((d, i) => (i ? 'L' : 'M') + (PL + band * (i + 0.5)).toFixed(1) + ' ' + Y(d.avg).toFixed(1)).join(' ');
  svg.appendChild(sv('path', { d: path, fill: 'none', stroke: 'var(--orange)', 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
  pts.forEach((d, i) => svg.appendChild(sv('circle', {
    cx: PL + band * (i + 0.5), cy: Y(d.avg), r: 4.5, fill: 'var(--orange)', stroke: 'var(--surface)', 'stroke-width': 2 })));
  pts.forEach((d, i) => {
    const hit = sv('rect', { x: PL + band * i, y: 0, width: band, height: H - PB + 24, class: 'hit' });
    hit.addEventListener('pointermove', e => showTip(e, [
      { value: nf(d.v) + ' units', label: 'sold this week', color: 'var(--blue)' },
      { value: d.avg.toFixed(1) + ' units', label: '4-week average', color: 'var(--orange)' },
      { value: nf(d.total) + ' total', label: 'sold to date' },
    ], p.name + ' — ' + fdate(d.d)));
    hit.addEventListener('pointerleave', hideTip);
    svg.appendChild(hit);
  });
  host.appendChild(svg);

  const h = $('#weekly-t'); h.textContent = '';
  const tb = el('table');
  const hr = el('tr');
  ['Week', 'Sold that week', '4-week average', 'Total sold', '% sold'].forEach((c, i) => hr.appendChild(el('th', i === 0 ? 'l' : '', c)));
  tb.appendChild(el('thead')).appendChild(hr);
  const bd = el('tbody');
  pts.slice().reverse().forEach(d => {
    const tr = el('tr');
    [[fdate(d.d), 'l'], [sgn(d.v), ''], [d.avg.toFixed(1), ''], [nf(d.total), ''], [p.units ? pf(d.total / p.units) : '–', '']]
      .forEach(([v, c]) => tr.appendChild(el('td', c, v)));
    bd.appendChild(tr);
  });
  tb.appendChild(bd);
  const wrap = el('div', 'scroll'); wrap.appendChild(tb); h.appendChild(wrap);
}

/* ---------- overall KPIs ---------- */
function kpis() {
  const box = $('#kpis'); box.textContent = '';
  const P = vis();
  /* Weekly figures throughout, so nothing here can disagree with the Excel files. */
  const sold = P.reduce((a, p) => a + (p.wSold || 0), 0);
  const units = P.reduce((a, p) => a + (p.units || 0), 0);
  const nw = P.reduce((a, p) => a + (p.wNew || 0), 0);
  const moved = P.filter(p => (p.wNew || 0) > 0).length;
  const top = P.slice().sort((a, b) => (b.wNew || 0) - (a.wNew || 0))[0];
  $('#kpinote').textContent = 'All figures below are the weekly record as at ' + fdate(DATA.weekLatest) + '.';
  const add = (l, v, d, hero) => {
    const c = el('div', 'kpi' + (hero ? ' hero' : ''));
    c.appendChild(el('div', 'l', l)); c.appendChild(el('div', 'v', v));
    if (d) c.appendChild(el('div', 'd', d)); box.appendChild(c);
  };
  add('Sold this week', nf(nw), moved + ' of ' + P.length + ' projects moved', true);
  add('Total units sold', nf(sold), 'of ' + nf(units) + ' units tracked');
  add('All ' + P.length + ' projects combined', units ? pf(sold / units) : '–',
      nf(sold) + ' of ' + nf(units) + ' units sold');
  add('Fastest mover', top && top.wNew ? trunc(top.name, 18) : '–', top && top.wNew ? '+' + top.wNew + ' units' : 'no movement');
}

/* ---------- horizontal bar helper ---------- */
function hbars(host, rows, opts) {
  host.textContent = '';
  if (!rows.length) { host.appendChild(el('p', 'note', opts.empty || 'Nothing to show.')); return; }
  const narrow = innerWidth < 640;
  const LW = narrow ? 130 : 240, RW = opts.rw || 60, BH = 18, GAP = 13;
  const W = wide(), H = rows.length * (BH + GAP) + 6, PW = Math.max(90, W - LW - RW);
  const svg = sv('svg', { width: '100%', viewBox: `0 0 ${W} ${H}`, role: 'img' });
  rows.forEach((r, i) => {
    const y = i * (BH + GAP) + 3;
    const lab = sv('text', { x: LW - 10, y: y + BH / 2 + 4, 'text-anchor': 'end', class: 'clab' });
    lab.textContent = trunc(r.label, narrow ? 16 : 34); svg.appendChild(lab);
    if (opts.track) svg.appendChild(sv('rect', { x: LW, y, width: PW, height: BH, rx: 4, fill: 'var(--track)' }));
    const w = Math.max(2, r.frac * PW);
    svg.appendChild(sv('rect', { x: LW, y, width: opts.track ? Math.max(2, w - 2) : w, height: BH, rx: 4, fill: 'var(--blue)', class: 'mark' }));
    const v = sv('text', { x: LW + (opts.track ? PW : w) + 8, y: y + BH / 2 + 4, class: 'vlab' });
    v.textContent = r.value; svg.appendChild(v);
    const hit = sv('rect', { x: 0, y: y - GAP / 2, width: W, height: BH + GAP, class: 'hit' });
    hit.addEventListener('pointermove', e => showTip(e, r.tip, r.label));
    hit.addEventListener('pointerleave', hideTip);
    svg.appendChild(hit);
  });
  host.appendChild(svg);
}

function movers() {
  /* The only place on the page that uses today's live numbers. */
  const isLive = DATA.todayDate && DATA.todayDate !== DATA.weekLatest;
  $('#mvnote').textContent = isLive
    ? 'Today (' + fdate(DATA.todayDate) + ') against the last weekly record (' + fdate(DATA.weekLatest) +
      '). This is the only section using live daily numbers — everything else on the page is weekly.'
    : 'Today is the latest weekly record, so there is nothing newer to compare against.';
  const rows = isLive ? vis().filter(p => p.todayNew).sort((a, b) => b.todayNew - a.todayNew) : [];
  const max = rows.length ? rows[0].todayNew : 1;
  hbars($('#movers'), rows.map(p => ({
    label: p.name, frac: p.todayNew / max, value: sgn(p.todayNew),
    tip: [{ value: sgn(p.todayNew) + ' units', label: 'since ' + fdate(DATA.weekLatest), color: 'var(--blue)' },
          { value: nf(p.todaySold) + ' / ' + nf(p.units), label: 'sold today (' + pf(p.todaySold / p.units) + ')' }],
  })), { empty: isLive ? 'Nothing has moved since the last weekly record.' : 'No live data to show today.' });

  const h = $('#movers-t'); h.textContent = '';
  const tb = el('table'); const hr = el('tr');
  ['Project', 'Code', 'New', 'Total sold', 'Units', '%'].forEach((c, i) => hr.appendChild(el('th', i < 2 ? 'l' : '', c)));
  tb.appendChild(el('thead')).appendChild(hr);
  const bd = el('tbody');
  vis().slice().sort((a, b) => (b.newSales || 0) - (a.newSales || 0)).forEach(p => {
    const tr = el('tr');
    [[p.name, 'l nm'], [p.code || '–', 'l'], [p.newSales === null ? '–' : sgn(p.newSales), ''],
     [nf(p.sold), ''], [nf(p.units), ''], [pf(p.pct), '']].forEach(([v, c]) => tr.appendChild(el('td', c, v)));
    bd.appendChild(tr);
  });
  tb.appendChild(bd);
  const wrap = el('div', 'scroll'); wrap.appendChild(tb); h.appendChild(wrap);
}

function sellthru() {
  const rows = vis().filter(p => p.wPct !== null && p.wPct !== undefined).sort((a, b) => b.wPct - a.wPct);
  $('#stnote').textContent = 'Share of total units sold as at ' + fdate(DATA.weekLatest) +
    ' — the weekly record. The pale bar is what is still unsold.';
  hbars($('#sellthru'), rows.map(p => ({
    label: p.name, frac: p.wPct, value: pf(p.wPct),
    tip: [{ value: pf(p.wPct), label: 'sold', color: 'var(--blue)' },
          { value: nf(p.wSold) + ' of ' + nf(p.units), label: 'units' },
          { value: nf(p.units - p.wSold), label: 'still unsold' }],
  })), { track: true, rw: 66 });
}

function bytype() {
  /* Unit-type detail is only captured when the scraper runs, so until a Friday run
     exists it can be a day ahead of the weekly record. Mark it live when it is. */
  const btLive = DATA.typesDate && DATA.typesDate !== DATA.weekLatest;
  $('#btcard').classList.toggle('live-card', !!btLive);
  $('#btnote').textContent = (btLive ? 'Live figures for today, ' : 'Weekly record, ')
    + fdate(DATA.typesDate) + ' — split by unit type. Projects listing several blocks of the same type are combined.'
    + (btLive ? ' These will match the weekly numbers again from the next Friday run.' : '');
  const rows = [];
  vis().forEach(p => (p.types || []).forEach(t => rows.push({ p, t })));
  if (!rows.length) { $('#bytype').textContent = ''; $('#bytype').appendChild(el('p', 'note', 'Unit-type data appears after the first scheduled run.')); return; }
  const maxU = Math.max(...rows.map(r => r.t.units));
  hbars($('#bytype'), rows.map(r => ({
    label: r.p.types.length > 1 ? r.p.name + ' · ' + r.t.type : r.p.name,
    frac: r.t.units / maxU, value: nf(r.t.sold) + ' / ' + nf(r.t.units),
    inner: r.t.sold / r.t.units,
    tip: [{ value: nf(r.t.sold) + ' sold', label: 'of ' + nf(r.t.units) + ' units', color: 'var(--blue)' },
          { value: nf(r.t.units - r.t.sold) + ' unsold', label: r.t.type }],
  })), { rw: 96, stacked: true });
  /* repaint the sold portion inside each total-units bar */
  const svg = $('#bytype').querySelector('svg');
  if (!svg) return;
  const bars = svg.querySelectorAll('rect.mark');
  rows.forEach((r, i) => {
    const bar = bars[i]; if (!bar) return;
    const full = parseFloat(bar.getAttribute('width'));
    bar.setAttribute('fill', 'var(--track)');
    const sold = r.t.units ? (r.t.sold / r.t.units) * full : 0;
    if (sold > 2) {
      const s = sv('rect', { x: bar.getAttribute('x'), y: bar.getAttribute('y'), width: Math.max(2, sold - 2),
                             height: bar.getAttribute('height'), rx: 4, fill: 'var(--blue)', class: 'mark' });
      bar.parentNode.insertBefore(s, bar.nextSibling);
    }
  });
}

function trends() {
  const host = $('#trends'); host.textContent = '';
  vis().forEach(p => {
    const pts = p.weekly;
    const card = el('div', 'smc');
    const t = el('div', 't', p.name); t.title = p.name; card.appendChild(t);
    const last = pts.length ? pts[pts.length - 1].v : null;
    const first = pts.length ? pts[0].v : null;
    card.appendChild(el('div', 'm', nf(last) + ' sold' + (last !== null && first !== null ? '  ·  ' + sgn(last - first) : '')));
    const W = 200, H = 52, PL = 2, PR = 8, PT = 8, PB = 6;
    const svg = sv('svg', { width: '100%', viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: 'none', role: 'img' });
    svg.style.marginTop = '7px';
    if (pts.length < 2) { card.appendChild(svg); host.appendChild(card); return; }
    const vs = pts.map(d => d.v), lo = Math.min(...vs), hi = Math.max(...vs), span = (hi - lo) || 1;
    const X = i => PL + (i / (pts.length - 1)) * (W - PL - PR);
    const Y = v => PT + (1 - (v - lo) / span) * (H - PT - PB);
    svg.appendChild(sv('line', { x1: PL, y1: H - PB, x2: W - PR, y2: H - PB, class: 'gl' }));
    const d = pts.map((pt, i) => (i ? 'L' : 'M') + X(i).toFixed(1) + ' ' + Y(pt.v).toFixed(1)).join(' ');
    svg.appendChild(sv('path', { d: d + ` L ${X(pts.length - 1).toFixed(1)} ${H - PB} L ${PL} ${H - PB} Z`, fill: 'var(--blue)', opacity: '.10' }));
    svg.appendChild(sv('path', { d, fill: 'none', stroke: 'var(--blue)', 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
    svg.appendChild(sv('circle', { cx: X(pts.length - 1), cy: Y(last), r: 4, fill: 'var(--blue)', stroke: 'var(--surface)', 'stroke-width': 2 }));
    const band = (W - PL - PR) / pts.length;
    pts.forEach((pt, i) => {
      const hit = sv('rect', { x: X(i) - band / 2, y: 0, width: band, height: H, class: 'hit' });
      hit.addEventListener('pointermove', e => showTip(e, [{ value: nf(pt.v) + ' sold', label: fdate(pt.d), color: 'var(--blue)' }], p.name));
      hit.addEventListener('pointerleave', hideTip);
      svg.appendChild(hit);
    });
    card.appendChild(svg); host.appendChild(card);
  });
}

$('#theme').onclick = e => {
  const dark = document.documentElement.dataset.theme === 'dark';
  document.documentElement.dataset.theme = dark ? 'light' : 'dark';
  e.target.textContent = dark ? 'Dark' : 'Light';
};
document.querySelectorAll('[data-tbl]').forEach(b => {
  b.onclick = () => {
    const t = $('#' + b.dataset.tbl + '-t');
    const open = t.style.display !== 'none';
    t.style.display = open ? 'none' : 'block';
    b.textContent = open ? 'Show as table' : 'Hide table';
  };
});

$('#asat').textContent = fdate(DATA.latestDate);
$('#foot').textContent = 'Generated ' + DATA.generated +
  ' · Source: TEDUH portal, Jabatan Perumahan Negara (teduh.kpkt.gov.my)';
function render() { trackerBar(); table(); insight(); picker(); weekly(); kpis(); movers(); sellthru(); bytype(); trends(); }
render();
let rt; addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(() => { weekly(); movers(); sellthru(); bytype(); }, 160); });
</script>
</body>
</html>
"""


def main():
    os.makedirs(DOCS, exist_ok=True)
    payload = build_payload()
    html_out = TEMPLATE.replace("__DATA__", json.dumps(payload, ensure_ascii=False).replace("</", "<\\/"))
    out = os.path.join(DOCS, "index.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html_out)
    print(f"Wrote {out}  ({len(html_out):,} bytes, {len(payload['projects'])} projects, {len(payload['dates'])} snapshots)")


if __name__ == "__main__":
    main()
