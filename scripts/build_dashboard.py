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

TRACKER_LABEL = {"seputeh": "Seputeh Hills", "status13": "Developer Sales Status"}


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


def build_payload():
    projects = read("projects.csv")
    daily = read("data/teduh_daily.csv") or read("data/teduh_history.csv")
    bytype = read("data/teduh_by_type.csv")

    series = {}
    for r in daily:
        v = to_int(r.get("total_sold"))
        if v is None:
            continue
        series.setdefault(r["code"] or "", {})[r["week"]] = v

    types = {}
    if bytype:
        latest_t = max(r["week"] for r in bytype)
        for r in bytype:
            if r["week"] != latest_t:
                continue
            types.setdefault(r["code"], []).append(
                {"type": r["unit_type"], "units": to_int(r["units"]) or 0, "sold": to_int(r["sold"]) or 0}
            )

    out = []
    for p in projects:
        code = (p.get("code") or "").strip()
        pts = sorted(series.get(code, {}).items())
        units = to_int(p.get("total_units")) or 0
        latest = pts[-1][1] if pts else None
        prev = pts[-2][1] if len(pts) > 1 else None
        groups = types.get(code, [])
        # merge same-named unit types (a project often lists one group per block)
        merged = {}
        for g in groups:
            m = merged.setdefault(g["type"], {"type": g["type"], "units": 0, "sold": 0})
            m["units"] += g["units"]
            m["sold"] += g["sold"]
        out.append({
            "tracker": p["tracker"],
            "trackerLabel": TRACKER_LABEL.get(p["tracker"], p["tracker"]),
            "no": to_int(p.get("no")),
            "name": (p.get("project") or "").replace("\n", " ").strip(),
            "code": code,
            "developer": (p.get("developer") or "").strip(),
            "launched": p.get("launched") or "",
            "units": units,
            "remarks": (p.get("remarks") or "").strip(),
            "series": [{"d": d, "v": v} for d, v in pts],
            "sold": latest,
            "newSales": (latest - prev) if (latest is not None and prev is not None) else None,
            "pct": (latest / units) if (latest is not None and units) else None,
            "types": sorted(merged.values(), key=lambda x: -x["units"]),
        })

    all_dates = sorted({d for s in series.values() for d in s})
    return {
        "generated": datetime.now(MYT).strftime("%d %b %Y, %-I:%M %p") + " MYT",
        "latestDate": all_dates[-1] if all_dates else "",
        "prevDate": all_dates[-2] if len(all_dates) > 1 else "",
        "dates": all_dates,
        "projects": out,
    }


TEMPLATE = r"""<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>TEDUH Competitor Tracker</title>
<style>
:root{
  color-scheme:light;
  --plane:#f9f9f7; --surface:#fcfcfb;
  --ink:#0b0b0b; --ink-2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --border:rgba(11,11,11,.10);
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a;
  --track:#cde2fb; --good:#006300; --flat:#898781;
  --shadow:0 1px 2px rgba(11,11,11,.04),0 4px 16px rgba(11,11,11,.05);
}
html[data-theme="dark"]{
  color-scheme:dark;
  --plane:#0d0d0d; --surface:#1a1a19;
  --ink:#fff; --ink-2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,.10);
  --s1:#3987e5; --s2:#d95926; --s3:#199e70;
  --track:#184f95; --good:#0ca30c; --flat:#898781;
  --shadow:none;
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--plane); color:var(--ink);
  font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;
  -webkit-font-smoothing:antialiased;
}
.wrap{max-width:1240px;margin:0 auto;padding:28px 20px 72px}
header{display:flex;flex-wrap:wrap;gap:16px;align-items:flex-start;justify-content:space-between;margin-bottom:8px}
h1{font-size:22px;font-weight:650;margin:0;letter-spacing:-.01em}
.sub{color:var(--ink-2);font-size:13px;margin-top:5px}
.sub b{color:var(--ink);font-weight:600}
h2{font-size:15px;font-weight:640;margin:0 0 3px;letter-spacing:-.005em}
.note{color:var(--muted);font-size:12.5px;margin:0 0 16px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px;margin-bottom:18px;box-shadow:var(--shadow)}
button{font:inherit;color:inherit;cursor:pointer}
.ghost{background:none;border:1px solid var(--border);border-radius:8px;padding:6px 12px;font-size:12.5px;color:var(--ink-2)}
.ghost:hover{background:var(--plane)}
.ghost[aria-pressed="true"]{background:var(--s1);border-color:var(--s1);color:#fff}
.bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:18px}
.bar .lab{font-size:12px;color:var(--muted);margin-right:2px}
.seg{display:inline-flex;border:1px solid var(--border);border-radius:8px;overflow:hidden}
.seg button{background:var(--surface);border:0;padding:6px 13px;font-size:12.5px;color:var(--ink-2)}
.seg button+button{border-left:1px solid var(--border)}
.seg button[aria-pressed="true"]{background:var(--s1);color:#fff}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin-bottom:18px}
.kpi{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:16px 18px;box-shadow:var(--shadow)}
.kpi .l{font-size:12.5px;color:var(--ink-2)}
.kpi .v{font-size:30px;font-weight:640;letter-spacing:-.02em;margin-top:5px;line-height:1.1}
.kpi .d{font-size:12.5px;color:var(--muted);margin-top:3px}
.kpi .d.up{color:var(--good);font-weight:600}
.hero .v{font-size:52px}
svg{display:block;overflow:visible}
.gl{stroke:var(--grid);stroke-width:1}
.ax{stroke:var(--axis);stroke-width:1}
.tk{fill:var(--muted);font-size:11px;font-variant-numeric:tabular-nums}
.vlab{fill:var(--ink);font-size:11.5px;font-weight:600;font-variant-numeric:tabular-nums}
.clab{fill:var(--ink-2);font-size:12px}
.hit{fill:transparent;cursor:pointer}
.mark{transition:opacity .12s}
.mark:hover{opacity:.82}
.sm{display:grid;grid-template-columns:repeat(auto-fill,minmax(196px,1fr));gap:8px}
.smc{padding:11px 12px 9px;border:1px solid var(--border);border-radius:10px;background:var(--surface)}
.smc .t{font-size:12px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.smc .m{font-size:11.5px;color:var(--muted);margin-top:1px;font-variant-numeric:tabular-nums}
table{border-collapse:collapse;width:100%;font-size:12.5px;font-variant-numeric:tabular-nums}
th,td{padding:7px 9px;text-align:right;border-bottom:1px solid var(--grid);white-space:nowrap}
th{color:var(--ink-2);font-weight:600;font-size:11.5px;position:sticky;top:0;background:var(--surface);z-index:1}
th.l,td.l{text-align:left}
th.g{border-left:1px solid var(--grid)}
td.g{border-left:1px solid var(--grid)}
tbody tr:hover td{background:var(--plane)}
.new{background:rgba(42,120,214,.07)}
tr.grp td{background:var(--plane);font-weight:640;font-size:11.5px;color:var(--ink-2);letter-spacing:.03em;text-transform:uppercase;position:sticky;left:0}
html[data-theme="dark"] .new{background:rgba(57,135,229,.13)}
.scroll{overflow:auto;max-height:520px;border:1px solid var(--border);border-radius:10px}
.tip{position:fixed;pointer-events:none;opacity:0;transition:opacity .1s;background:var(--surface);border:1px solid var(--border);border-radius:9px;padding:9px 11px;box-shadow:0 6px 24px rgba(0,0,0,.16);font-size:12px;z-index:50;max-width:260px}
.tip .tv{font-size:15px;font-weight:650;font-variant-numeric:tabular-nums}
.tip .tn{color:var(--ink-2);margin-top:1px}
.tip .tr{display:flex;align-items:center;gap:7px;margin-top:5px}
.tip .key{width:14px;height:2px;border-radius:1px;flex:none}
.lg{display:flex;gap:16px;flex-wrap:wrap;margin:2px 0 14px;font-size:12px;color:var(--ink-2)}
.lg span{display:inline-flex;align-items:center;gap:6px}
.sw{width:11px;height:11px;border-radius:3px;flex:none}
.foot{color:var(--muted);font-size:12px;margin-top:26px;line-height:1.7}
.foot a{color:var(--s1)}
.hide{display:none}
@media(max-width:560px){.wrap{padding:18px 13px 56px}.kpi .v{font-size:26px}.hero .v{font-size:40px}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <div>
    <h1>TEDUH Competitor Tracker</h1>
    <div class="sub">Sales data as at <b id="asat"></b> · refreshed daily from the TEDUH portal</div>
  </div>
  <div style="display:flex;gap:8px">
    <button class="ghost" id="theme">Dark</button>
    <button class="ghost" id="print">Print</button>
  </div>
</header>

<div class="bar">
  <span class="lab">Portfolio</span>
  <span class="seg" id="ftrack"></span>
  <span class="lab" style="margin-left:10px">Trend range</span>
  <span class="seg" id="frange">
    <button data-r="30">30d</button><button data-r="90">90d</button><button data-r="0" aria-pressed="true">All</button>
  </span>
</div>

<div class="kpis" id="kpis"></div>

<div class="card">
  <h2>New sales since previous snapshot</h2>
  <p class="note" id="mvnote"></p>
  <div id="movers"></div>
  <button class="ghost" data-tbl="movers" style="margin-top:12px">Show as table</button>
  <div id="movers-t" class="hide" style="margin-top:12px"></div>
</div>

<div class="card">
  <h2>Sell-through</h2>
  <p class="note">Share of total units sold to date. The lighter track is the unsold remainder.</p>
  <div id="sellthru"></div>
</div>

<div class="card">
  <h2>Cumulative units sold over time</h2>
  <p class="note">One panel per project, each on its own scale — the shape is the story, the numbers are on the panel. A sharp dip to zero is a gap in the imported history, not a real reversal.</p>
  <div class="sm" id="trends"></div>
</div>

<div class="card">
  <h2>Sold and unsold by unit type</h2>
  <p class="note">Latest snapshot. Projects listing several blocks of the same type are combined.</p>
  <div class="lg"><span><i class="sw" style="background:var(--s1)"></i>Sold</span><span><i class="sw" style="background:var(--track)"></i>Unsold</span></div>
  <div id="bytype"></div>
</div>

<div class="card">
  <h2>Weekly tracker</h2>
  <p class="note" id="tblnote"></p>
  <div class="scroll" id="table"></div>
</div>

<div class="card" style="margin-top:4px">
  <h2>Download</h2>
  <p class="note">The same numbers as the Excel trackers you already use, regenerated on every refresh.</p>
  <div style="display:flex;gap:10px;flex-wrap:wrap">
    <a class="ghost" style="text-decoration:none" href="downloads/Seputeh_Hills_Teduh_Weekly_Update.xlsx" download>Seputeh Hills tracker (.xlsx)</a>
    <a class="ghost" style="text-decoration:none" href="downloads/Tduh_Developer_Project_Sales_Status.xlsx" download>Developer sales status (.xlsx)</a>
    <a class="ghost" style="text-decoration:none" href="data/teduh_daily.csv" download>Raw daily data (.csv)</a>
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
const el = (t, c, txt) => { const e = document.createElement(t); if (c) e.className = c; if (txt !== undefined) e.textContent = txt; return e; };
const fdate = s => { if (!s) return ''; const d = new Date(s + 'T00:00:00');
  return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }); };
const SVGNS = 'http://www.w3.org/2000/svg';
function sv(t, a) { const e = document.createElementNS(SVGNS, t); for (const k in a) e.setAttribute(k, a[k]); return e; }

let state = { tracker: 'all', range: 0 };

/* ---------- tooltip ---------- */
const tip = $('#tip');
function showTip(ev, rows, title) {
  tip.textContent = '';
  if (title) tip.appendChild(el('div', 'tn', title));
  rows.forEach(r => {
    const line = el('div', 'tr');
    if (r.color) { const k = el('span', 'key'); k.style.background = r.color; k.style.height = '2px'; line.appendChild(k); }
    const v = el('span', 'tv', r.value); line.appendChild(v);
    if (r.label) { const l = el('span', 'tn'); l.textContent = r.label; l.style.marginTop = '0'; line.appendChild(l); }
    tip.appendChild(line);
  });
  tip.style.opacity = '1';
  const pad = 14, w = 250;
  let x = ev.clientX + pad, y = ev.clientY + pad;
  if (x + w > innerWidth) x = ev.clientX - w - pad;
  if (y + 120 > innerHeight) y = ev.clientY - 120;
  tip.style.left = x + 'px'; tip.style.top = y + 'px';
}
const hideTip = () => { tip.style.opacity = '0'; };
addEventListener('scroll', hideTip, true);

/* ---------- data helpers ---------- */
const visible = () => DATA.projects.filter(p => state.tracker === 'all' || p.tracker === state.tracker);
function clipped(p) {
  if (!state.range) return p.series;
  const cut = new Date(DATA.latestDate + 'T00:00:00');
  cut.setDate(cut.getDate() - state.range);
  const k = cut.toISOString().slice(0, 10);
  const s = p.series.filter(d => d.d >= k);
  return s.length > 1 ? s : p.series.slice(-2);
}

/* ---------- KPIs ---------- */
function kpis() {
  const box = $('#kpis'); box.textContent = '';
  const ps = visible();
  const sold = ps.reduce((a, p) => a + (p.sold || 0), 0);
  const units = ps.reduce((a, p) => a + (p.units || 0), 0);
  const nw = ps.reduce((a, p) => a + (p.newSales || 0), 0);
  const movers = ps.filter(p => (p.newSales || 0) > 0).length;
  const top = ps.slice().sort((a, b) => (b.newSales || 0) - (a.newSales || 0))[0];
  const add = (label, value, delta, hero) => {
    const c = el('div', 'kpi' + (hero ? ' hero' : ''));
    c.appendChild(el('div', 'l', label));
    c.appendChild(el('div', 'v', value));
    if (delta) { const d = el('div', 'd' + (delta.up ? ' up' : ''), delta.text); c.appendChild(d); }
    box.appendChild(c);
  };
  add('New sales this period', nf(nw), { text: movers + ' of ' + ps.length + ' projects moved', up: nw > 0 }, true);
  add('Total units sold', nf(sold), { text: 'across ' + nf(units) + ' units tracked' });
  add('Portfolio sell-through', units ? pf(sold / units) : '–', { text: 'weighted by unit count' });
  add('Fastest mover', top && top.newSales ? top.name : '–',
      { text: top && top.newSales ? '+' + top.newSales + ' units' : 'no movement', up: !!(top && top.newSales) });
}

/* ---------- movers: horizontal bars, one series ---------- */
function movers() {
  const host = $('#movers'); host.textContent = '';
  $('#mvnote').textContent = DATA.prevDate
    ? fdate(DATA.prevDate) + ' → ' + fdate(DATA.latestDate) + '. Projects with no movement are omitted from the chart but kept in the table.'
    : 'Not enough history yet — a second snapshot is needed to show change.';
  const ps = visible().filter(p => p.newSales !== null && p.newSales !== 0)
                      .sort((a, b) => b.newSales - a.newSales);
  if (!ps.length) { host.appendChild(el('p', 'note', 'No sales movement in this period.')); mtable(); return; }
  const LW = 230, RW = 56, BH = 20, GAP = 12, H = ps.length * (BH + GAP) + 8;
  const W = Math.min(1180, host.clientWidth || 900), PW = Math.max(160, W - LW - RW);
  const max = Math.max(...ps.map(p => p.newSales));
  const svg = sv('svg', { width: '100%', viewBox: `0 0 ${W} ${H}`, role: 'img' });
  ps.forEach((p, i) => {
    const y = i * (BH + GAP) + 4;
    const w = Math.max(2, (p.newSales / max) * PW);
    const t = sv('text', { x: LW - 10, y: y + BH / 2 + 4, 'text-anchor': 'end', class: 'clab' });
    t.textContent = p.name.length > 34 ? p.name.slice(0, 33) + '…' : p.name;
    svg.appendChild(t);
    const r = sv('rect', { x: LW, y, width: w, height: BH, rx: 4, fill: 'var(--s1)', class: 'mark' });
    svg.appendChild(r);
    const v = sv('text', { x: LW + w + 8, y: y + BH / 2 + 4, class: 'vlab' });
    v.textContent = '+' + p.newSales;
    svg.appendChild(v);
    const hit = sv('rect', { x: 0, y: y - GAP / 2, width: W, height: BH + GAP, class: 'hit' });
    hit.addEventListener('pointermove', e => showTip(e,
      [{ value: '+' + p.newSales + ' units', label: 'this period', color: 'var(--s1)' },
       { value: nf(p.sold) + ' / ' + nf(p.units), label: 'sold to date (' + pf(p.pct) + ')' }], p.name));
    hit.addEventListener('pointerleave', hideTip);
    svg.appendChild(hit);
  });
  host.appendChild(svg);
  mtable();
}
function mtable() {
  const h = $('#movers-t'); h.textContent = '';
  const tb = el('table');
  const hd = el('tr');
  ['Project', 'Code', 'New sales', 'Total sold', 'Units', '%'].forEach((c, i) => {
    const th = el('th', i === 0 || i === 1 ? 'l' : '', c); hd.appendChild(th);
  });
  tb.appendChild(el('thead')).appendChild(hd);
  const bd = el('tbody');
  visible().sort((a, b) => (b.newSales || 0) - (a.newSales || 0)).forEach(p => {
    const tr = el('tr');
    [[p.name, 'l'], [p.code, 'l'], [p.newSales === null ? '–' : (p.newSales > 0 ? '+' : '') + p.newSales, ''],
     [nf(p.sold), ''], [nf(p.units), ''], [pf(p.pct), '']].forEach(([v, c]) => tr.appendChild(el('td', c, v)));
    bd.appendChild(tr);
  });
  tb.appendChild(bd);
  const wrap = el('div', 'scroll'); wrap.appendChild(tb); h.appendChild(wrap);
}

/* ---------- sell-through meters ---------- */
function sellthru() {
  const host = $('#sellthru'); host.textContent = '';
  const ps = visible().filter(p => p.pct !== null).sort((a, b) => b.pct - a.pct);
  if (!ps.length) return;
  const LW = 230, RW = 66, BH = 16, GAP = 13, H = ps.length * (BH + GAP) + 6;
  const W = Math.min(1180, host.clientWidth || 900), PW = Math.max(160, W - LW - RW);
  const svg = sv('svg', { width: '100%', viewBox: `0 0 ${W} ${H}`, role: 'img' });
  ps.forEach((p, i) => {
    const y = i * (BH + GAP) + 3;
    const t = sv('text', { x: LW - 10, y: y + BH / 2 + 4, 'text-anchor': 'end', class: 'clab' });
    t.textContent = p.name.length > 34 ? p.name.slice(0, 33) + '…' : p.name;
    svg.appendChild(t);
    svg.appendChild(sv('rect', { x: LW, y, width: PW, height: BH, rx: 4, fill: 'var(--track)' }));
    const w = Math.max(2, p.pct * PW);
    svg.appendChild(sv('rect', { x: LW, y, width: w, height: BH, rx: 4, fill: 'var(--s1)', class: 'mark' }));
    const v = sv('text', { x: LW + PW + 8, y: y + BH / 2 + 4, class: 'vlab' });
    v.textContent = pf(p.pct);
    svg.appendChild(v);
    const hit = sv('rect', { x: 0, y: y - GAP / 2, width: W, height: BH + GAP, class: 'hit' });
    hit.addEventListener('pointermove', e => showTip(e,
      [{ value: pf(p.pct), label: 'sold', color: 'var(--s1)' },
       { value: nf(p.sold) + ' of ' + nf(p.units), label: 'units' },
       { value: nf(p.units - p.sold), label: 'still unsold' }], p.name));
    hit.addEventListener('pointerleave', hideTip);
    svg.appendChild(hit);
  });
  host.appendChild(svg);
}

/* ---------- small-multiple trend panels ---------- */
function trends() {
  const host = $('#trends'); host.textContent = '';
  visible().forEach(p => {
    const pts = clipped(p);
    const card = el('div', 'smc');
    card.appendChild(el('div', 't', p.name)).title = p.name;
    const last = pts.length ? pts[pts.length - 1].v : null;
    const first = pts.length ? pts[0].v : null;
    const chg = (last !== null && first !== null) ? last - first : null;
    card.appendChild(el('div', 'm', nf(last) + ' sold' + (chg !== null ? '  ·  ' + (chg >= 0 ? '+' : '') + chg + ' in range' : '')));
    const W = 200, H = 54, PL = 2, PR = 8, PT = 8, PB = 6;
    const svg = sv('svg', { width: '100%', viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: 'none', role: 'img' });
    svg.style.marginTop = '6px';
    if (pts.length < 2) { card.appendChild(svg); host.appendChild(card); return; }
    const vs = pts.map(d => d.v), lo = Math.min(...vs), hi = Math.max(...vs);
    const span = (hi - lo) || 1;
    const X = i => PL + (i / (pts.length - 1)) * (W - PL - PR);
    const Y = v => PT + (1 - (v - lo) / span) * (H - PT - PB);
    svg.appendChild(sv('line', { x1: PL, y1: H - PB, x2: W - PR, y2: H - PB, class: 'gl' }));
    const d = pts.map((pt, i) => (i ? 'L' : 'M') + X(i).toFixed(1) + ' ' + Y(pt.v).toFixed(1)).join(' ');
    svg.appendChild(sv('path', { d: d + ` L ${X(pts.length - 1).toFixed(1)} ${H - PB} L ${PL} ${H - PB} Z`,
                                 fill: 'var(--s1)', opacity: '.10' }));
    svg.appendChild(sv('path', { d, fill: 'none', stroke: 'var(--s1)', 'stroke-width': 2,
                                 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
    svg.appendChild(sv('circle', { cx: X(pts.length - 1), cy: Y(last), r: 4,
                                   fill: 'var(--s1)', stroke: 'var(--surface)', 'stroke-width': 2 }));
    const band = (W - PL - PR) / pts.length;
    pts.forEach((pt, i) => {
      const hit = sv('rect', { x: X(i) - band / 2, y: 0, width: band, height: H, class: 'hit' });
      hit.addEventListener('pointermove', e => showTip(e,
        [{ value: nf(pt.v) + ' sold', label: fdate(pt.d), color: 'var(--s1)' }], p.name));
      hit.addEventListener('pointerleave', hideTip);
      svg.appendChild(hit);
    });
    card.appendChild(svg);
    host.appendChild(card);
  });
}

/* ---------- sold / unsold by unit type ---------- */
function bytype() {
  const host = $('#bytype'); host.textContent = '';
  const ps = visible().filter(p => p.types && p.types.length);
  if (!ps.length) {
    host.appendChild(el('p', 'note', 'Unit-type data appears after the first scheduled run.'));
    return;
  }
  const rows = [];
  ps.forEach(p => p.types.forEach(t => rows.push({ p, t })));
  const LW = 230, RW = 96, BH = 18, GAP = 12, H = rows.length * (BH + GAP) + 6;
  const W = Math.min(1180, host.clientWidth || 900), PW = Math.max(160, W - LW - RW);
  const maxU = Math.max(...rows.map(r => r.t.units));
  const svg = sv('svg', { width: '100%', viewBox: `0 0 ${W} ${H}`, role: 'img' });
  rows.forEach((r, i) => {
    const y = i * (BH + GAP) + 3;
    const label = r.p.types.length > 1 ? r.p.name + ' · ' + r.t.type : r.p.name;
    const t = sv('text', { x: LW - 10, y: y + BH / 2 + 4, 'text-anchor': 'end', class: 'clab' });
    t.textContent = label.length > 36 ? label.slice(0, 35) + '…' : label;
    svg.appendChild(t);
    const full = (r.t.units / maxU) * PW;
    const sold = r.t.units ? (r.t.sold / r.t.units) * full : 0;
    svg.appendChild(sv('rect', { x: LW, y, width: Math.max(2, full), height: BH, rx: 4, fill: 'var(--track)' }));
    if (sold > 0) {
      /* 2px surface gap between the sold fill and the unsold remainder */
      svg.appendChild(sv('rect', { x: LW, y, width: Math.max(2, sold - 2), height: BH, rx: 4,
                                   fill: 'var(--s1)', class: 'mark' }));
    }
    const v = sv('text', { x: LW + full + 8, y: y + BH / 2 + 4, class: 'vlab' });
    v.textContent = nf(r.t.sold) + ' / ' + nf(r.t.units);
    svg.appendChild(v);
    const hit = sv('rect', { x: 0, y: y - GAP / 2, width: W, height: BH + GAP, class: 'hit' });
    hit.addEventListener('pointermove', e => showTip(e,
      [{ value: nf(r.t.sold) + ' sold', label: 'of ' + nf(r.t.units) + ' units', color: 'var(--s1)' },
       { value: nf(r.t.units - r.t.sold) + ' unsold', label: r.t.units ? ((100 - r.t.sold / r.t.units * 100).toFixed(1) + '% remaining') : '' }],
      r.p.name + ' — ' + r.t.type));
    hit.addEventListener('pointerleave', hideTip);
    svg.appendChild(hit);
  });
  host.appendChild(svg);
}

/* ---------- weekly tracker table ---------- */
function table() {
  const host = $('#table'); host.textContent = '';
  const ps = visible();
  $('#tblnote').textContent = 'Every recorded snapshot, newest first. Scroll sideways for earlier weeks.';
  /* Newest column first: the number the reader wants is never behind a scroll. */
  const dates = DATA.dates.slice().reverse();
  const tb = el('table');
  const hd = el('tr');
  ['#', 'Project', 'Code', 'Developer', 'Units'].forEach((c, i) => hd.appendChild(el('th', i < 4 ? 'l' : '', c)));
  dates.forEach((d, i) => {
    const th = el('th', 'g' + (i === 0 ? ' new' : ''), fdate(d).replace(/ \d{4}$/, ''));
    th.colSpan = 2; hd.appendChild(th);
  });
  const hd2 = el('tr');
  for (let i = 0; i < 5; i++) hd2.appendChild(el('th', 'l', ''));
  dates.forEach((d, i) => {
    hd2.appendChild(el('th', 'g' + (i === 0 ? ' new' : ''), 'Sold'));
    hd2.appendChild(el('th', i === 0 ? 'new' : '', '+/–'));
  });
  const thead = el('thead'); thead.appendChild(hd); thead.appendChild(hd2); tb.appendChild(thead);
  const bd = el('tbody');
  let group = null;
  ps.forEach(p => {
    if (state.tracker === 'all' && p.trackerLabel !== group) {
      group = p.trackerLabel;
      const gr = el('tr', 'grp');
      const gc = el('td', 'l', group);
      gc.colSpan = 5 + dates.length * 2;
      gr.appendChild(gc); bd.appendChild(gr);
    }
    const tr = el('tr');
    [[String(p.no ?? ''), 'l'], [p.name, 'l'], [p.code || '–', 'l'], [p.developer, 'l'], [nf(p.units), '']]
      .forEach(([v, c]) => tr.appendChild(el('td', c, v)));
    const map = {}; p.series.forEach(s => map[s.d] = s.v);
    /* Deltas compare each snapshot with the one before it in chronological order,
       then the row is rendered newest-first. */
    const delta = {};
    let prev = null;
    DATA.dates.forEach(d => {
      const v = map[d];
      if (v === undefined) return;
      if (prev !== null) delta[d] = v - prev;
      prev = v;
    });
    dates.forEach((d, i) => {
      const isNew = i === 0;
      const v = map[d] === undefined ? null : map[d];
      tr.appendChild(el('td', 'g' + (isNew ? ' new' : ''), v === null ? '' : nf(v)));
      const dv = delta[d];
      tr.appendChild(el('td', isNew ? 'new' : '',
        dv === undefined ? '' : (dv > 0 ? '+' + dv : String(dv))));
    });
    bd.appendChild(tr);
  });
  tb.appendChild(bd); host.appendChild(tb);
}

/* ---------- controls ---------- */
function controls() {
  const seg = $('#ftrack'); seg.textContent = '';
  const groups = [['all', 'All projects']];
  const seen = new Set();
  DATA.projects.forEach(p => { if (!seen.has(p.tracker)) { seen.add(p.tracker); groups.push([p.tracker, p.trackerLabel]); } });
  groups.forEach(([k, label]) => {
    const b = el('button', '', label);
    b.setAttribute('aria-pressed', String(state.tracker === k));
    b.onclick = () => { state.tracker = k; render(); };
    seg.appendChild(b);
  });
  $('#frange').querySelectorAll('button').forEach(b => {
    b.setAttribute('aria-pressed', String(Number(b.dataset.r) === state.range));
    b.onclick = () => { state.range = Number(b.dataset.r); render(); };
  });
}

$('#theme').onclick = e => {
  const dark = document.documentElement.dataset.theme === 'dark';
  document.documentElement.dataset.theme = dark ? 'light' : 'dark';
  e.target.textContent = dark ? 'Dark' : 'Light';
};
$('#print').onclick = () => print();
document.querySelectorAll('[data-tbl]').forEach(b => {
  b.onclick = () => {
    const t = $('#' + b.dataset.tbl + '-t');
    const open = !t.classList.contains('hide');
    t.classList.toggle('hide', open);
    b.textContent = open ? 'Show as table' : 'Hide table';
  };
});

function render() { controls(); kpis(); movers(); sellthru(); trends(); bytype(); table(); }
$('#asat').textContent = fdate(DATA.latestDate);
$('#foot').textContent = 'Generated ' + DATA.generated +
  ' · Source: TEDUH portal, Jabatan Perumahan Negara (teduh.kpkt.gov.my) · ' +
  'Unit counts are read from the portal’s own unit list, so they match what the site shows.';
render();
addEventListener('resize', () => { movers(); sellthru(); bytype(); });
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
