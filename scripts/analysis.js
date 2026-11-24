/* The Analysis page. build_dashboard.py drops this file into docs/index.html.

   Everything is worked out on the device from the figures already in the page:
   no AI, nothing leaves the site, and no number that is not in DATA.

   The rules she agreed (24 Nov 2026), all in one place:
   - only projects on her trackers are ranked, and every answer says how many;
   - a code on two trackers counts once, unless a developer is named, when it
     counts for that developer;
   - "top" is sold %, sold-out projects included, ties to more units sold;
   - rows with the same name on one tracker are one project, but a year or type
     only brings in the phases that fit it;
   - "last five years" is calendar years, by APDL date;
   - pace is four weeks, Friday to Friday, unless another period is picked;
   - every total is her total units. A row that shows more sold than its total
     cannot be ranked, so it is left out and named. */
const AN = (() => {
  const $id = id => document.getElementById(id);
  const nil = v => v === null || v === undefined;
  const norm = t => (t || '').toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '')
    .replace(/['‘’`]/g, '').replace(/[^a-z0-9]+/g, ' ').trim();
  const addDays = (iso, n) => { const d = new Date(iso + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
  const days = (a, b) => (new Date(b + 'T00:00:00Z') - new Date(a + 'T00:00:00Z')) / 864e5;
  const listOf = a => a.length < 2 ? a.join('') : a.slice(0, -1).join(', ') + ' and ' + a[a.length - 1];
  const plural = (n, w) => nf(n) + ' ' + w + (n === 1 ? '' : 's');
  const THIS_YEAR = +DATA.todayDate.slice(0, 4);
  const MONTHS = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december'];

  const DEVS = TRACKERS.filter(t => t.kind === 'developer'), AREAS = TRACKERS.filter(t => t.kind === 'area');
  const labelOf = k => (TRACKERS.find(t => t.key === k) || {}).label || k;
  const STATES = [...new Set(ALL.flatMap(p => (p.state || '').split(' / ')))].filter(Boolean).sort();
  const GROUPS = [];
  AREAS.forEach(t => ALL.forEach(p => {
    if (p.tracker === t.key && p.group && !GROUPS.some(g => g.key === t.key + '|' + p.group)) GROUPS.push({ key: t.key + '|' + p.group, label: p.group });
  }));
  const YEARS = [...new Set(ALL.map(p => (p.apdl || '').slice(0, 4)).filter(Boolean))].sort().reverse();

  /* ---------- which rows ---------- */
  const codesOf = new Map();          // 'a:johor' / 'g:johor|JBCC' -> its codes
  AREAS.forEach(t => codesOf.set('a:' + t.key, new Set(ALL.filter(p => p.tracker === t.key).flatMap(p => p.codes))));
  GROUPS.forEach(g => codesOf.set('g:' + g.key, new Set(ALL.filter(p => p.tracker + '|' + p.group === g.key).flatMap(p => p.codes))));
  /* One row per code. The area tracker's row wins, so her own name is the one shown. */
  const ONCE = (() => {
    const seen = new Set();
    return [...ALL].sort((a, b) => (a.trackerKind === 'developer') - (b.trackerKind === 'developer')).filter(p => {
      if (p.codes.some(c => seen.has(c))) return false;
      p.codes.forEach(c => seen.add(c)); return true;
    });
  })();
  const placeName = v => v.startsWith('s:') ? v.slice(2) : v.startsWith('a:') ? labelOf(v.slice(2)) + ' tracker' : v.split('|')[1];
  const inPlace = (p, v) => v.startsWith('s:') ? (p.state || '').split(' / ').includes(v.slice(2))
    : v.startsWith('a:') ? (p.tracker === v.slice(2) || p.codes.some(c => codesOf.get(v) && codesOf.get(v).has(c)))
    : (p.tracker + '|' + p.group === v.slice(2) || p.codes.some(c => codesOf.get(v) && codesOf.get(v).has(c)));
  const whyOut = p => !p.codes.length ? 'nocode' : nil(p.todaySold) ? 'noread' : !p.units ? 'nounits' : p.todaySold > p.units ? 'over' : '';
  const nameKey = p => p.tracker + '|' + p.name.trim().toLowerCase();
  const phaseCount = new Map();
  ALL.forEach(p => { if (!whyOut(p)) phaseCount.set(nameKey(p), (phaseCount.get(nameKey(p)) || 0) + 1); });

  /* ---------- readings ---------- */
  const reads = new Map();
  const readsOf = p => {
    if (!reads.has(p)) {
      const m = new Map(); p.weekly.forEach(x => m.set(x.d, x.v)); p.series.forEach(x => m.set(x.d, x.v));
      reads.set(p, [...m].sort((a, b) => a[0] < b[0] ? -1 : 1));
    }
    return reads.get(p);
  };
  /* Units sold as at a date: the last reading on or before it. Nothing yet but
     not launched yet either = 0; nothing yet and already launched = unknown. */
  const at = (p, d) => {
    let v = null;
    for (const [k, x] of readsOf(p)) { if (k > d) break; v = x; }
    return v === null && p.apdl && p.apdl > d ? 0 : v;
  };
  const soldIn = (p, a, b) => { const x = at(p, a), y = at(p, b); return x === null || y === null ? null : y - x; };
  function period(S) {
    const last = DATA.weekLatest, today = DATA.todayDate, per = S.per || 'w4';
    let m;
    if (per === 'w0') {
      const prev = DATA.weeks.filter(w => w < today && w !== today).pop() || last;
      return { from: prev, to: today, label: 'since ' + fdate(prev) };
    }
    if ((m = /^w(\d+)$/.exec(per))) { const from = addDays(last, -7 * m[1]); return { from, to: last, label: 'in the ' + m[1] + ' weeks to ' + fdate(last) }; }
    if ((m = /^m(\d\d?)$/.exec(per))) {        // m0 this month so far, m1 the month before
      const d = new Date(today.slice(0, 7) + '-01T00:00:00Z'); d.setUTCMonth(d.getUTCMonth() - +m[1]);
      return monthPeriod(d.toISOString().slice(0, 7));
    }
    if ((m = /^M(\d{4}-\d\d)$/.exec(per))) return monthPeriod(m[1]);
    if ((m = /^c(\d{4}-\d\d-\d\d)_(\d{4}-\d\d-\d\d)$/.exec(per))) return { from: m[1], to: m[2], label: 'from ' + fdate(m[1]) + ' to ' + fdate(m[2]) };
    return period({ per: 'w4' });
  }
  function monthPeriod(ym) {
    const first = ym + '-01', d = new Date(first + 'T00:00:00Z'); d.setUTCMonth(d.getUTCMonth() + 1);
    const end = addDays(d.toISOString().slice(0, 10), -1), to = end < DATA.todayDate ? end : DATA.todayDate;
    const nm = MONTHS[+ym.slice(5) - 1]; const M = nm[0].toUpperCase() + nm.slice(1) + ' ' + ym.slice(0, 4);
    return { from: addDays(first, -1), to, label: 'in ' + M + (to === end ? '' : ' so far') };
  }

  /* ---------- what is being asked ---------- */
  const blank = () => ({ a: 'top', n: 10, by: 'pct', dir: -1, dev: new Set(), place: new Set(), type: '', y0: '', y1: '', name: [],
    per: 'w4', pm: 'fast', gby: 'dev', ents: [], picks: [], sv: 'year', ly: 'pct' });
  let S = blank();

  const fitsName = (p, list) => !list.length || list.some(n => norm(p.name).includes(n) || norm(p.teduhName).includes(n) || p.codes.includes(n.replace(/ /g, '-')));
  function rowsFor(Q) {
    let L = Q.dev.size ? ALL.filter(p => Q.dev.has(p.tracker)) : ONCE;
    if (Q.place.size) L = L.filter(p => [...Q.place].some(v => inPlace(p, v)));
    if (Q.type) L = L.filter(p => p.kind === Q.type);
    if (Q.y0) L = L.filter(p => p.apdl && p.apdl.slice(0, 4) >= Q.y0);
    if (Q.y1) L = L.filter(p => p.apdl && p.apdl.slice(0, 4) <= Q.y1);
    return L.filter(p => fitsName(p, Q.name));
  }
  function combine(list) {
    const m = new Map();
    list.forEach(p => { const k = nameKey(p); if (!m.has(k)) m.set(k, []); m.get(k).push(p); });
    return [...m].map(([key, rows]) => {
      const units = rows.reduce((a, p) => a + p.units, 0), sold = rows.reduce((a, p) => a + p.todaySold, 0);
      const ap = rows.map(p => p.apdl).filter(Boolean).sort(), dv = [...new Set(rows.map(p => p.developer).filter(Boolean))];
      const kinds = [...new Set(rows.map(p => p.kind).filter(Boolean))];
      return { key, rows, name: rows[0].name.trim(), tracker: rows[0].tracker, dev: dv.length === 1 ? dv[0] : rows[0].trackerLabel,
        units, sold, unsold: units - sold, pct: sold / units, apdl: ap[0] || '', phases: rows.length, all: phaseCount.get(key) || rows.length,
        state: [...new Set(rows.map(p => p.state).filter(Boolean))].join(' / '), kind: kinds.length > 1 ? 'Mixed' : kinds[0] || '',
        perMonth: ap[0] ? sold / Math.max(1, days(ap[0], DATA.todayDate) / 30.44) : null };
    });
  }
  function pool(Q) {
    const L = rowsFor(Q), ok = L.filter(p => !whyOut(p));
    const left = { nocode: 0, noread: 0, nounits: 0, over: [] };
    L.forEach(p => { const w = whyOut(p); if (w === 'over') left.over.push(p); else if (w) left[w]++; });
    return { list: combine(ok), phases: ok.length, left };
  }
  /* Sales in the period, for a list of projects. A project is only measured if
     every one of its phases has a reading at the start of the period. */
  function paced(list, per) {
    const out = [], short = [];
    const weeks = days(per.from, per.to) / 7;
    list.forEach(g => {
      const v = g.rows.map(p => soldIn(p, per.from, per.to));
      if (v.some(nil)) { short.push(g); return; }
      const inP = v.reduce((a, b) => a + b, 0), pw = weeks > 0 ? inP / weeks : 0;
      const since = g.rows.reduce((a, p) => a + (p.todayNew || 0), 0);
      out.push({ ...g, inP, pw, since, months: g.unsold > 0 && pw > 0 ? g.unsold / (pw * 365.25 / 12 / 7) : null });
    });
    return { out, short };
  }

  /* ---------- words ---------- */
  const yearText = Q => !Q.y0 && !Q.y1 ? '' : Q.y0 === Q.y1 ? 'launched ' + Q.y0 : Q.y0 && Q.y1 ? 'launched ' + Q.y0 + '–' + Q.y1
    : Q.y0 ? 'launched from ' + Q.y0 : 'launched up to ' + Q.y1;
  /* A project's own name when the text is exactly one project, else the words in quotes. */
  const properName = n => { for (const g of BYKEY.values()) if (norm(g.name) === n) return g.name; return '“' + n + '”'; };
  function scopeText(Q, bare) {
    const who = [...Q.dev].map(labelOf), where = [...Q.place].map(placeName);
    const bits = [];
    if (Q.type) bits.push(Q.type.toLowerCase());
    if (Q.name.length) bits.push(listOf(Q.name.map(properName)));
    if (who.length) bits.push(listOf(who));
    if (where.length) bits.push((who.length || bits.length ? 'in ' : '') + listOf(where));
    let t = bits.join(' ') || 'all your trackers';
    if (Q.type && !who.length && !where.length && !Q.name.length) t = Q.type.toLowerCase() + ', all your trackers';
    if (bare && !who.length && !where.length && !Q.type && !Q.name.length) return yearText(Q);
    return t + (yearText(Q) ? ', ' + yearText(Q) : '');
  }
  function leftText(left, short) {
    const o = [];
    if (left.over.length) o.push(listOf(left.over.map(p => p.name + ' (' + nf(p.todaySold) + ' sold on a total of ' + nf(p.units) + ', so the total needs checking)')));
    if (left.nocode) o.push(plural(left.nocode, 'row') + ' with no TEDUH code');
    if (left.noread) o.push(plural(left.noread, 'row') + ' with no TEDUH reading');
    if (left.nounits) o.push(plural(left.nounits, 'row') + ' with no total units');
    if (short && short.length) o.push(plural(short.length, 'project') + ' not read at the start of the period');
    return o.length ? ' Left out: ' + o.join('; ') + '.' : '';
  }
  const among = (n, ph) => 'Among ' + plural(n, 'tracked project') + (ph > n ? ' (' + nf(ph) + ' phases)' : '') + ', as at ' + fdate(DATA.todayDate) + '.';
  const COMB = ' Phases with the same name are added together; only phases that fit the filters count.';
  const EARLY = ' Only projects on your trackers count. Older launches that sold out before tracking began are not on them, so early years read low.';
  const num = (v, d) => nil(v) ? '–' : v.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
  const plus = v => nil(v) ? '–' : (v > 0 ? '+' : '') + nf(v);
  const FMT = { int: nf, pct: pf, dec: v => num(v, 1), date: v => v ? fdate(v) : '–', text: v => v || '–', plus };
  const COL = {
    rank: { h: '#', t: 'int', f: (g, i) => i + 1 }, name: { h: 'Project', t: 'name', f: g => g.name },
    sold: { h: 'Sold', t: 'int', f: g => g.sold }, units: { h: 'Total units', t: 'int', f: g => g.units },
    unsold: { h: 'Unsold', t: 'int', f: g => g.unsold }, pct: { h: 'Sold %', t: 'pct', f: g => g.pct },
    apdl: { h: 'APDL', t: 'date', f: g => g.apdl }, perMonth: { h: 'Sold per month since APDL', t: 'dec', f: g => g.perMonth },
    dev: { h: 'Developer', t: 'text', f: g => g.dev }, state: { h: 'State', t: 'text', f: g => g.state }, kind: { h: 'Type', t: 'text', f: g => g.kind },
    inP: { h: 'Sold in period', t: 'plus', f: g => g.inP }, pw: { h: 'Per week', t: 'dec', f: g => g.pw }, months: { h: 'Months left', t: 'dec', f: g => g.months },
  };
  const cols = keys => keys.split(' ').map(k => COL[k]);
  const BY = { pct: 'sold %', sold: 'units sold', perMonth: 'units sold per month since APDL' };
  const ranker = (k, dir) => (a, b) => {
    const x = a[k], y = b[k];
    if (nil(x) || nil(y)) return nil(x) - nil(y);
    return (x - y) * dir || (b.sold - a.sold) || a.name.localeCompare(b.name);
  };
  const cut = (list, n) => n > 0 ? list.slice(0, n) : list;

  /* ---------- the five answers ----------
     Each returns {head, line, note, cols, rows, chart}. */
  const ANSWERS = {
    top(Q) {
      const P = pool(Q), L = cut(P.list.slice().sort(ranker(Q.by, Q.dir)), Q.n), st = scopeText(Q);
      const val = g => Q.by === 'pct' ? pf(g.pct) + ' sold (' + nf(g.sold) + ' of ' + nf(g.units) + ')'
        : Q.by === 'sold' ? nf(g.sold) + ' units sold (of ' + nf(g.units) + ')' : num(g.perMonth, 1) + ' units a month';
      const head = (Q.dir < 0 ? 'Top ' : 'Lowest ') + (Q.n > 0 ? Math.min(Q.n, L.length) : 'all ' + L.length) + ' by ' + BY[Q.by] + ': ' + st;
      const line = !L.length ? '' : L[0].name + (Q.dir < 0 ? ' leads at ' : ' is lowest at ') + val(L[0])
        + (L.length > 1 ? ', then ' + listOf(L.slice(1, 3).map(g => g.name + ' (' + (Q.by === 'pct' ? pf(g.pct) : Q.by === 'sold' ? nf(g.sold) : num(g.perMonth, 1)) + ')')) : '') + '.';
      return { head, line, note: among(P.list.length, P.phases) + ' Sold-out projects are included; ties go to the one with more units sold.' + (Q.by === 'perMonth' ? ' Per month runs from the first APDL date to today, so a project that sold out long ago reads low.' : '') + COMB + leftText(P.left),
        cols: cols('rank name sold units pct perMonth apdl dev state'), rows: L,
        chart: h => bars(h, L, g => Q.by === 'pct' ? g.pct : g[Q.by], { max: Q.by === 'pct' ? 1 : 0, track: Q.by === 'pct', text: g => Q.by === 'pct' ? pf(g.pct) : Q.by === 'sold' ? nf(g.sold) : num(g.perMonth, 1), label: BY[Q.by] }) };
    },
    pace(Q) {
      const P = pool(Q), per = period(Q), { out, short } = paced(P.list, per), st = scopeText(Q);
      /* Launched inside the period: too new to call slow or stalled (the tracker
         filter says the same), so those two lists leave them out. */
      const fresh = g => g.rows.every(p => p.apdl > per.from), weak = Q.pm === 'slow' || Q.pm === 'stalled';
      const young = weak ? out.filter(g => g.unsold > 0 && fresh(g)) : [];
      const open = out.filter(g => g.unsold > 0 && !(weak && fresh(g)));
      const seen = weak ? out.filter(g => !fresh(g)) : out;
      const defs = {
        fast: ['Fastest selling', () => out.filter(g => g.inP > 0).sort(ranker('inP', -1))],
        slow: ['Slowest selling', () => open.slice().sort((a, b) => (a.inP - b.inP) || (b.unsold - a.unsold))],
        /* Same test as the tracker filter: nothing in the period, and nothing since. */
        stalled: ['No sales', () => open.filter(g => g.inP <= 0 && !(per.to === DATA.weekLatest && g.since > 0)).sort((a, b) => b.unsold - a.unsold)],
        left: ['Closest to selling out at this pace', () => open.filter(g => g.months !== null).sort((a, b) => a.months - b.months)],
      };
      const [title, make] = defs[Q.pm], full = make(), L = cut(full, Q.n);
      const tail = full.length > L.length && Q.pm === 'stalled' ? ' ' + plural(full.length, 'project') + ' in all; the ' + L.length + ' with most unsold are shown.' : '';
      const line = !L.length ? '' : Q.pm === 'fast' ? L[0].name + ' sold the most ' + per.label + ': ' + plural(L[0].inP, 'unit') + (L.length > 1 ? ', then ' + listOf(L.slice(1, 3).map(g => g.name + ' (' + g.inP + ')')) : '') + '.'
        : Q.pm === 'slow' ? L[0].name + ' sold ' + plural(L[0].inP, 'unit') + ' ' + per.label + ', with ' + nf(L[0].unsold) + ' still unsold.'
        : Q.pm === 'stalled' ? plural(full.length, 'project') + ' of ' + nf(seen.length) + ' sold nothing ' + per.label + ', holding ' + nf(full.reduce((a, g) => a + g.unsold, 0)) + ' unsold units.'
        : L[0].name + ' would sell its last ' + nf(L[0].unsold) + ' units in ' + num(L[0].months, 1) + ' months at its pace ' + per.label + '.';
      let note = among(seen.length, seen.reduce((a, g) => a + g.phases, 0)) + ' Sales are net of cancellations, ' + per.label + ' (' + fdate(per.from, true) + ' reading to ' + fdate(per.to, true) + ').'
        + (Q.pm === 'left' ? ' Months left is unsold units at the same weekly pace; a short period makes it jumpy.' : '') + COMB + (young.length ? ' Not counted: ' + plural(young.length, 'project') + ' launched inside the period.' : '') + leftText(P.left, short) + tail;
      if (!out.length && short.length) {
        const first = short.flatMap(g => g.rows).map(p => (readsOf(p)[0] || [''])[0]).filter(Boolean).sort()[0];
        note = 'No readings that far back: the earliest for these projects is ' + fdate(first) + '. Pick a shorter period.';
      }
      const un = Q.pm === 'stalled', lf = Q.pm === 'left';
      return { head: title + (Q.n > 0 && L.length > 1 && !un ? ' (' + L.length + ')' : '') + ': ' + st + ', ' + per.label, line, note,
        cols: cols('rank name inP pw unsold months sold units pct apdl dev'), rows: L,
        chart: h => bars(h, L, g => un ? g.unsold : lf ? g.months : Math.max(0, g.inP), { text: g => un ? nf(g.unsold) : lf ? num(g.months, 1) : plus(g.inP), label: un ? 'unsold units' : lf ? 'months left' : 'units sold in the period' }) };
    },
    groups(Q) {
      const ents = Q.ents.length ? Q.ents : Q.gby === 'state' ? STATES.map(s => 's:' + s) : DEVS.map(t => 'd:' + t.key);
      const per = period(Q), over = [];
      const rows = ents.map(e => {
        const q = { ...Q, dev: new Set(e.startsWith('d:') ? [e.slice(2)] : Q.dev), place: new Set(e.startsWith('d:') ? Q.place : [e]) };
        const P = pool(q), pc = paced(P.list, per); over.push(...P.left.over);
        const units = P.list.reduce((a, g) => a + g.units, 0), sold = P.list.reduce((a, g) => a + g.sold, 0);
        return { key: e, name: e.startsWith('d:') ? labelOf(e.slice(2)) : placeName(e), n: P.list.length, units, sold, unsold: units - sold,
          pct: units ? sold / units : null, inP: pc.out.length ? pc.out.reduce((a, g) => a + g.inP, 0) : null, short: pc.short.length };
      }).filter(r => Q.ents.length || r.n).sort(ranker(Q.by === 'perMonth' ? 'pct' : Q.by, -1));
      const kindWord = Q.ents.length ? '' : Q.gby === 'state' ? 'States' : 'Developers';
      const q2 = { ...Q, dev: Q.gby === 'dev' && !Q.ents.length ? new Set() : Q.dev };
      const some = q2.dev.size || Q.place.size || Q.type || Q.y0 || Q.y1 || Q.name.length;
      const head = (kindWord || listOf(ents.map(e => e.startsWith('d:') ? labelOf(e.slice(2)) : placeName(e)))) + ' compared'
        + (some ? ': ' + scopeText(q2, true) : '') + (Q.by === 'inP' ? (some ? ', ' : ': ') + 'units sold ' + per.label : '');
      const f = rows[0], by = Q.by === 'sold' ? 'sold' : Q.by === 'units' ? 'units' : Q.by === 'unsold' ? 'unsold' : Q.by === 'inP' ? 'inP' : 'pct';
      const say = r => by === 'pct' ? pf(r.pct) : by === 'inP' ? plus(r.inP) : nf(r[by]);
      const word = { pct: 'sold %', sold: 'units sold', units: 'units launched', unsold: 'unsold units', inP: 'units sold ' + per.label }[by];
      const line = !f ? '' : f.name + ' is highest by ' + word + ' at ' + say(f) + (by === 'pct' ? ' (' + nf(f.sold) + ' of ' + nf(f.units) + ')' : '')
        + (rows.length > 1 ? ', then ' + listOf(rows.slice(1, 3).map(r => r.name + ' (' + say(r) + ')')) : '') + '.';
      const shorts = rows.reduce((a, r) => a + r.short, 0);
      const ov = [...new Set(over)];
      return { head, line, note: 'As at ' + fdate(DATA.todayDate) + '. Sold in period is ' + per.label + (shorts ? ', without ' + plural(shorts, 'project') + ' not read at its start' : '') + '.'
          + (Q.ents.length > 1 && Q.ents.some(e => !e.startsWith('d:')) ? ' Places can overlap, so these do not add up to a total.' : '') + EARLY + leftText({ over: ov }),
        cols: [COL.rank, { h: 'Name', t: 'text', f: r => r.name }, { h: 'Projects', t: 'int', f: r => r.n }, { h: 'Units launched', t: 'int', f: r => r.units },
          COL.sold, COL.unsold, COL.pct, { h: 'Sold in period', t: 'plus', f: r => r.inP }], rows,
        chart: h => stack(h, rows) };
    },
    projects(Q) {
      const per = period(Q);
      const L = Q.picks.map(k => BYKEY.get(k)).filter(Boolean).map(g => paced([g], per).out[0] || { ...g, inP: null, pw: null, months: null });
      const best = L.slice().sort(ranker('pct', -1))[0];
      return { head: L.length ? listOf(L.map(g => g.name)) : 'Compare projects', line: L.length > 1 ? best.name + ' is the most sold at ' + pf(best.pct) + ' (' + nf(best.sold) + ' of ' + nf(best.units) + '); '
          + listOf(L.filter(g => g !== best).map(g => g.name + ' is at ' + pf(g.pct))) + '.' : '',
        note: L.length ? 'As at ' + fdate(DATA.todayDate) + '. Sold in period is ' + per.label + ', net of cancellations.' + (L.some(g => g.phases > 1) ? ' Phases with the same name are added together.' : '') : 'Add two to six projects above.',
        cols: cols('name sold units unsold pct inP pw months perMonth apdl kind state dev'), rows: L,
        chart: h => L.length && lines(h, L, Q.ly) };
    },
    supply(Q) {
      if (Q.sv === 'unsold') {
        const P = pool(Q), L = cut(P.list.filter(g => g.unsold > 0).sort((a, b) => b.unsold - a.unsold || a.name.localeCompare(b.name)), Q.n);
        const tot = P.list.reduce((a, g) => a + g.unsold, 0);
        return { head: 'Most unsold units: ' + scopeText(Q), line: L.length ? L[0].name + ' has the most unsold, ' + nf(L[0].unsold) + ' of ' + nf(L[0].units) + ' units'
            + (L.length > 1 ? ', then ' + listOf(L.slice(1, 3).map(g => g.name + ' (' + nf(g.unsold) + ')')) : '') + '. In all, ' + nf(tot) + ' units are unsold.' : '',
          note: among(P.list.length, P.phases) + ' A licensed unit not yet released for sale counts as unsold.' + COMB + leftText(P.left),
          cols: cols('rank name unsold units sold pct apdl dev state'), rows: L, chart: h => stack(h, L) };
      }
      const L = rowsFor(Q), noDate = L.filter(p => !p.apdl && !whyOut(p)).length, left = pool(Q).left;
      const yrs = [...new Set(L.filter(p => p.apdl).map(p => p.apdl.slice(0, 4)))].sort();
      const rows = yrs.map(y => {
        const P = pool({ ...Q, y0: y, y1: y }), units = P.list.reduce((a, g) => a + g.units, 0), sold = P.list.reduce((a, g) => a + g.sold, 0);
        return { name: y, n: P.list.length, ph: P.phases, units, sold, unsold: units - sold, pct: units ? sold / units : null };
      }).filter(r => r.n);
      const T = rows.reduce((a, r) => ({ ph: a.ph + r.ph, units: a.units + r.units, sold: a.sold + r.sold }), { ph: 0, units: 0, sold: 0 });
      const top = rows.slice().sort((a, b) => b.units - a.units)[0];
      return { head: 'Launches by year: ' + scopeText(Q), line: rows.length ? nf(T.units) + ' units launched' + (rows.length > 1 ? ' in ' + rows[0].name + '–' + rows[rows.length - 1].name + ', most in ' + top.name + ' (' + nf(top.units) + ')' : ' in ' + rows[0].name) + '; '
          + nf(T.sold) + ' sold (' + pf(T.sold / T.units) + '), ' + nf(T.units - T.sold) + ' unsold.' : '',
        note: 'By APDL date, as at ' + fdate(DATA.todayDate) + '. A project launched in phases counts in each year it launched one.' + EARLY + (noDate ? ' ' + plural(noDate, 'row') + ' with no APDL date not shown.' : '') + leftText(left),
        cols: [{ h: 'Year', t: 'text', f: r => r.name }, { h: 'Projects', t: 'int', f: r => r.n }, { h: 'Phases', t: 'int', f: r => r.ph }, { h: 'Units launched', t: 'int', f: r => r.units }, COL.sold, COL.unsold, COL.pct],
        rows, chart: h => stack(h, rows) };
    },
  };

  /* Every project once, for Compare projects. */
  const BYKEY = new Map(combine(ONCE.filter(p => !whyOut(p))).map(g => [g.key, g]));
  const KEYFOR = new Map();           // any tracker's row -> the key it is compared under
  BYKEY.forEach((g, k) => g.rows.forEach(p => p.codes.forEach(c => KEYFOR.set(c, k))));

  /* ---------- charts ---------- */
  const CW = h => Math.max(300, Math.min(1240, h.clientWidth || innerWidth - 64));
  const CHART_MAX = 20;
  function hot(svg, x, y, w, h, show) {
    const r = sv('rect', { x, y, width: w, height: h, class: 'hit', tabindex: 0 });
    r.addEventListener('pointermove', show); r.addEventListener('pointerleave', hideTip);
    r.addEventListener('focus', () => { const b = r.getBoundingClientRect(); show({ clientX: b.left + b.width / 2, clientY: b.top + 8 }); });
    r.addEventListener('blur', hideTip);
    svg.appendChild(r); return r;
  }
  function frame(host, n, rw) {
    const W = CW(host), narrow = W < 560, LW = narrow ? 128 : 250, BH = 18, GAP = 13;
    const svg = sv('svg', { width: '100%', viewBox: `0 0 ${W} ${n * (BH + GAP) + 6}`, role: 'img' });
    host.appendChild(svg);
    return { W, LW, BH, GAP, PW: Math.max(80, W - LW - rw), svg, cut: narrow ? 17 : 36 };
  }
  const rowLabel = (c, y, t) => { const l = sv('text', { x: c.LW - 10, y: y + c.BH / 2 + 4, 'text-anchor': 'end', class: 'clab' }); l.textContent = trunc(t, c.cut); c.svg.appendChild(l); };
  const rowValue = (c, x, y, t) => { const v = sv('text', { x, y: y + c.BH / 2 + 4, class: 'vlab' }); v.textContent = t; c.svg.appendChild(v); };
  const gTip = g => [{ value: pf(g.pct), label: 'sold', color: 'var(--blue)' }, { value: nf(g.sold) + ' of ' + nf(g.units), label: 'units' }, { value: nf(g.unsold), label: 'unsold' }];
  function bars(host, list, val, o) {
    const L = list.slice(0, CHART_MAX), max = o.max || Math.max(1e-9, ...L.map(val)), c = frame(host, L.length, 66);
    L.forEach((g, i) => {
      const y = i * (c.BH + c.GAP) + 3, w = Math.max(2, Math.min(1, Math.max(0, val(g) || 0) / max) * c.PW);
      rowLabel(c, y, (i + 1) + '. ' + g.name);
      if (o.track) c.svg.appendChild(sv('rect', { x: c.LW, y, width: c.PW, height: c.BH, rx: 4, fill: 'var(--track)' }));
      c.svg.appendChild(sv('rect', { x: c.LW, y, width: w, height: c.BH, rx: 4, fill: 'var(--blue)', class: 'mark' }));
      rowValue(c, c.LW + (o.track ? c.PW : w) + 8, y, o.text(g));
      hot(c.svg, 0, y - c.GAP / 2, c.W, c.BH + c.GAP, e => showTip(e, (o.track ? [] : [{ value: o.text(g), label: o.label, color: 'var(--blue)' }]).concat(gTip(g)), g.name));
    });
    if (list.length > L.length) host.appendChild(el('p', 'note', 'The chart shows the first ' + CHART_MAX + '; the table has all ' + list.length + '.'));
  }
  function stack(host, list) {
    const L = list.slice(0, CHART_MAX);
    if (!L.length) return;
    const lg = el('div', 'lg');
    [['var(--blue)', 'Sold'], ['var(--track)', 'Unsold']].forEach(([col, t]) => { const s = el('span'), i = el('i', 'sw'); i.style.background = col; s.appendChild(i); s.appendChild(document.createTextNode(t)); lg.appendChild(s); });
    host.appendChild(lg);
    const c = frame(host, L.length, 112), max = Math.max(1, ...L.map(g => g.units));
    L.forEach((g, i) => {
      const y = i * (c.BH + c.GAP) + 3, full = Math.max(2, g.units / max * c.PW), s = g.units ? g.sold / g.units * full : 0;
      rowLabel(c, y, g.name);
      c.svg.appendChild(sv('rect', { x: c.LW, y, width: full, height: c.BH, rx: 4, fill: 'var(--track)', class: 'mark' }));
      if (s > 3) c.svg.appendChild(sv('rect', { x: c.LW, y, width: Math.max(2, s - (g.sold < g.units ? 2 : 0)), height: c.BH, rx: 4, fill: 'var(--blue)', class: 'mark' }));
      rowValue(c, c.LW + full + 8, y, nf(g.sold) + ' / ' + nf(g.units));
      hot(c.svg, 0, y - c.GAP / 2, c.W, c.BH + c.GAP, e => showTip(e, gTip(g), g.name));
    });
    if (list.length > L.length) host.appendChild(el('p', 'note', 'The chart shows the first ' + CHART_MAX + '; the table has all ' + list.length + '.'));
  }
  /* A project keeps its colour when another is removed. */
  const slot = new Map();
  const slotOf = k => { if (!slot.has(k)) { const used = new Set(S.picks.filter(x => x !== k).map(x => slot.get(x))); let i = 1; while (used.has(i) && i < 6) i++; slot.set(k, i); } return slot.get(k); };
  function lines(host, L, mode) {
    const dates = [...new Set(DATA.weeks.concat(DATA.todayDate))].sort();
    const ser = L.map(g => ({ g, col: 'var(--s' + slotOf(g.key) + ')', pts: dates.map(d => {
      if (g.rows.every(p => p.apdl > d)) return null;       // the line starts at launch
      const v = g.rows.map(p => at(p, d)); if (v.some(nil)) return null;
      const s = v.reduce((a, b) => a + b, 0); return mode === 'pct' ? s / g.units : s;
    }) }));
    const first = dates.findIndex((_, i) => ser.some(s => s.pts[i] !== null));
    if (first < 0) return;
    const D = dates.slice(first); ser.forEach(s => { s.pts = s.pts.slice(first); });
    const lg = el('div', 'lg');
    ser.forEach(s => { const x = el('span'), i = el('i', 'swl'); i.style.background = s.col; x.appendChild(i); x.appendChild(document.createTextNode(s.g.name)); lg.appendChild(x); });
    host.appendChild(lg);
    const W = CW(host), H = 260, PL = 48, PR = 58, PT = 10, PB = 26, fm = v => mode === 'pct' ? Math.round(v * 100) + '%' : nf(Math.round(v));
    const all = ser.flatMap(s => s.pts).filter(v => v !== null), hi0 = mode === 'pct' ? 1 : Math.max(1, ...all);
    const step = mode === 'pct' ? .25 : (() => { const r = hi0 / 4, m = Math.pow(10, Math.floor(Math.log10(r))); return Math.max(1, [1, 2, 2.5, 5, 10].map(k => k * m).find(k => k >= r)); })();
    const hi = Math.ceil(hi0 / step - 1e-9) * step, t0 = +new Date(D[0]), t1 = +new Date(D[D.length - 1]) || t0 + 1;
    const X = d => PL + (t1 === t0 ? 0 : (+new Date(d) - t0) / (t1 - t0)) * (W - PL - PR), Y = v => PT + (1 - v / hi) * (H - PT - PB);
    const svg = sv('svg', { width: '100%', viewBox: `0 0 ${W} ${H}`, role: 'img' });
    for (let v = 0; v <= hi + 1e-9; v += step) {
      svg.appendChild(sv('line', { x1: PL, x2: W - PR, y1: Y(v), y2: Y(v), class: 'gl' }));
      const t = sv('text', { x: PL - 8, y: Y(v) + 4, 'text-anchor': 'end', class: 'tk' }); t.textContent = fm(v); svg.appendChild(t);
    }
    const nT = W < 560 ? 3 : 6;
    for (let k = 0; k < nT; k++) {
      const d = D[Math.round(k * (D.length - 1) / (nT - 1))], t = sv('text', { x: X(d), y: H - 6, 'text-anchor': k === 0 ? 'start' : k === nT - 1 ? 'end' : 'middle', class: 'tk' });
      t.textContent = fdate(d, true); svg.appendChild(t);
    }
    const ends = [];
    ser.forEach(s => {
      let path = '', pen = false;
      s.pts.forEach((v, i) => { if (v === null) { pen = false; return; } path += (pen ? 'L' : 'M') + X(D[i]).toFixed(1) + ' ' + Y(v).toFixed(1); pen = true; });
      svg.appendChild(sv('path', { d: path, fill: 'none', stroke: s.col, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
      const li = s.pts.length - 1;
      if (s.pts[li] !== null) { svg.appendChild(sv('circle', { cx: X(D[li]), cy: Y(s.pts[li]), r: 4, fill: s.col, stroke: 'var(--surface)', 'stroke-width': 2 })); ends.push({ y: Y(s.pts[li]), t: fm(s.pts[li]) }); }
    });
    ends.sort((a, b) => a.y - b.y).forEach((e, i) => { if (i && e.y < ends[i - 1].y + 14) e.y = ends[i - 1].y + 14; });
    ends.forEach(e => { const t = sv('text', { x: W - PR + 9, y: e.y + 4, class: 'vlab' }); t.textContent = e.t; svg.appendChild(t); });
    const hair = sv('line', { y1: PT, y2: H - PB, class: 'ax', opacity: 0 }); svg.appendChild(hair);
    D.forEach((d, i) => {
      const a = i ? (X(D[i - 1]) + X(d)) / 2 : PL, b = i < D.length - 1 ? (X(d) + X(D[i + 1])) / 2 : W - PR;
      const r = hot(svg, a, PT, Math.max(1, b - a), H - PT - PB, e => {
        hair.setAttribute('x1', X(d)); hair.setAttribute('x2', X(d)); hair.setAttribute('opacity', 1);
        showTip(e, ser.map(s => ({ value: s.pts[i] === null ? 'no reading' : mode === 'pct' ? pf(s.pts[i]) : nf(s.pts[i]), label: s.g.name, color: s.col })), fdate(d));
      });
      ['pointerleave', 'blur'].forEach(ev => r.addEventListener(ev, () => hair.setAttribute('opacity', 0)));
    });
    host.appendChild(svg);
  }

  /* ---------- reading a typed question ----------
     Longest known phrase first, then numbers and dates, then filler. Anything
     left is named back to her and nothing is run. */
  const FILLER = new Set(('the a an of in at on to for by with from and or is are was were be been do does did has have had me my our i we you please show list give tell what whats which who where '
    + 'how many much that this those these it its their all any project projects development developments developer developers unit units sale sales sell sells selling sold '
    + 'launched launch launching been being so far currently now right than as per each within between during over tracker trackers tracked there most more data figures number numbers '
    + 'among under can could would see get find compared have rank ranked ranking performing performance property properties').split(' '));
  const ALIAS = { spsetia: ['sp setia', 's p setia', 'setia'], simedarby: ['sime', 'sime darby property'], ecoworld: ['eco world', 'ecoworld'], mahsing: ['mah sing'], uem: ['uem', 'uem sunrise'],
    skyworld: ['sky world'], mbworld: ['mb world', 'mbw'], chinhin: ['chin hin'], cpiland: ['cpi', 'cpi land'], trinitygroup: ['trinity'], tslaw: ['ts law', 'tslaw'], majesticgen: ['majestic'],
    setiaawan: ['setia awan'], gamuda: ['gamuda'], platinumvictory: ['platinum victory', 'pv'], lbs: ['lbs bina'], brdb: ['brdb'], ksl: ['ksl'] };
  const PLACE_ALIAS = { 's:Kuala Lumpur': ['kl', 'wilayah persekutuan'], 's:Penang': ['pulau pinang'], 's:Negeri Sembilan': ['n9', 'ns', 'n sembilan'], 's:Melaka': ['malacca'],
    'a:status13': ['klang valley', 'kv'], 'a:seputeh': ['seputeh', 'seputeh hills'], 'a:ukay': ['ukay'], 'a:johor': ['johor tracker', 'johor area tracker', 'johor area'] };
  const TYPE_ALIAS = { Landed: ['landed', 'landed house', 'landed houses', 'terrace', 'terraces', 'terrace house', 'terrace houses', 'semi d', 'bungalow', 'bungalows', 'townhouse', 'townhouses'],
    'High-rise': ['high rise', 'highrise', 'high rises', 'condo', 'condos', 'condominium', 'condominiums', 'apartment', 'apartments', 'serviced apartment', 'serviced apartments', 'service apartment', 'service apartments', 'soho'] };
  /* phrase -> what it asks for. Checked longest first, so "most unsold" beats "unsold". */
  const CMD = {
    'top:': ['top', 'best', 'best selling', 'top selling', 'highest', 'leading', 'top performing', 'best performing', 'most sold'],
    'low:': ['bottom', 'worst', 'lowest', 'worst selling', 'least sold'],
    'by:pct': ['sold percentage', 'percentage sold', 'percentage', 'percent', 'percent sold', 'sold percent', 'take up', 'take up rate', 'takeup', 'sell through'],
    'by:sold': ['units sold', 'by units sold', 'most units sold', 'by units', 'by volume', 'biggest seller', 'biggest sellers', 'number of units sold'],
    'by:perMonth': ['per month', 'a month', 'monthly', 'units per month', 'sold per month'],
    'pm:fast': ['fastest', 'fastest selling', 'fast selling', 'sold the most', 'most sales', 'sold most', 'selling fastest', 'selling the most', 'fast movers', 'movers', 'pace', 'speed', 'momentum'],
    'pm:slow': ['slowest', 'slowest selling', 'slow selling', 'slow', 'selling slowest', 'slow movers', 'sold the least'],
    'pm:stalled': ['stalled', 'no sales', 'no sale', 'sold nothing', 'not selling', 'not moving', 'zero sales', 'stuck', 'without sales', 'didnt sell', 'did not sell'],
    'pm:left': ['months left', 'sell out', 'selling out', 'sold out soon', 'closest to selling out', 'nearest to selling out', 'how long to sell', 'time to sell', 'months to sell out', 'about to sell out', 'almost sold out', 'nearly sold out'],
    'sv:unsold': ['unsold', 'most unsold', 'most unsold units', 'unsold units', 'unsold stock', 'remaining', 'remaining units', 'stock', 'overhang', 'units left', 'balance units', 'left unsold'],
    'sv:year': ['by year', 'each year', 'per year', 'every year', 'yearly', 'year by year', 'launches', 'supply', 'new launches', 'how many launched', 'how many launches', 'units launched', 'projects launched'],
    'cmp:': ['compare', 'comparison', 'compared with', 'compare with', 'versus', 'vs', 'against', 'side by side', 'difference between'],
    'gby:dev': ['by developer', 'each developer', 'which developer', 'developers compared', 'compare developers', 'top developers', 'best developers', 'best developer', 'which developers', 'all developers', 'between developers'],
    'gby:state': ['by state', 'each state', 'which state', 'compare states', 'states', 'which states', 'all states', 'top states', 'best state'],
  };
  const WORDNUM = { one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10, twelve: 12, fifteen: 15, twenty: 20 };
  let LEX = null;
  function lexicon() {
    if (LEX) return LEX;
    LEX = new Map();
    const put = (ph, kind, v) => { const k = norm(ph); if (!k) return; const e = LEX.get(k); if (!e) LEX.set(k, [{ kind, v }]); else if (!e.some(x => x.kind === kind && x.v === v)) e.push({ kind, v }); };
    const reserved = new Set();
    Object.entries(CMD).forEach(([v, ps]) => ps.forEach(ph => { put(ph, 'cmd', v); reserved.add(norm(ph)); }));
    DEVS.forEach(t => [t.label, t.key].concat(ALIAS[t.key] || []).forEach(ph => { put(ph, 'dev', t.key); reserved.add(norm(ph)); }));
    STATES.forEach(s => { put(s, 'place', 's:' + s); reserved.add(norm(s)); });
    Object.entries(PLACE_ALIAS).forEach(([v, ps]) => ps.forEach(ph => { put(ph, 'place', v); reserved.add(norm(ph)); }));
    GROUPS.filter(g => g.label !== 'Others').forEach(g => { put(g.label, 'place', 'g:' + g.key); reserved.add(norm(g.label)); });
    Object.entries(TYPE_ALIAS).forEach(([v, ps]) => ps.forEach(ph => { put(ph, 'type', v); reserved.add(norm(ph)); }));
    /* Project names, and the shorter ways of saying them. */
    const GENERIC = new Set('residensi residence residences the taman pangsapuri bandar rumah menara project phase ph suites suite condo plaza city park garden gardens hills heights homes eco new'.split(' '));
    const ok = k => k.length > 2 && !reserved.has(k) && !FILLER.has(k) && !GENERIC.has(k) && !/^\d+$/.test(k) && !(k in WORDNUM) && !MONTHS.includes(k);
    const variants = nm => {
      const out = new Set(), raw = [nm, nm.replace(/\(.*?\)|\[.*?\]/g, ' '), nm.split('@')[0], nm.split(/[([]/)[0]];
      (nm.match(/\(([^)]+)\)/g) || []).forEach(x => { raw.push(x); raw.push(x.split('@')[0]); });
      raw.forEach(r => { const k = norm(r); out.add(k); const w = k.split(' '); while (w.length > 1 && GENERIC.has(w[0])) { w.shift(); out.add(w.join(' ')); } });
      return [...out].filter(ok);
    };
    const addAs = (p, key) => [p.name, p.teduhName || ''].forEach(nm => nm && variants(nm).forEach(v => put(v, 'proj', key)));
    ALL.forEach(p => { if (whyOut(p)) return; const key = KEYFOR.get(p.codes[0]); if (key) addAs(p, key); });
    ALL.forEach(p => p.codes.forEach(c => { const key = KEYFOR.get(c); if (key) put(c, 'proj', key); }));
    /* Townships: the words several project names start with. */
    const pre = new Map();
    ONCE.forEach(p => { const w = norm(p.name).split(' '); for (let n = 1; n < Math.min(w.length, 4); n++) { const k = w.slice(0, n).join(' '); if (!pre.has(k)) pre.set(k, new Set()); pre.get(k).add(nameKey(p)); } });
    /* A first word or two only one project uses ("ParkCity", "Causewayz") is that project. */
    pre.forEach((set, k) => { if (set.size === 1 && ok(k) && k.length > 3 && !LEX.has(k)) { const key = [...set][0]; if (BYKEY.has(key)) put(k, 'proj', key); } });
    pre.forEach((set, k) => { if (set.size > 1 && ok(k) && !k.split(' ').every(w => GENERIC.has(w) || FILLER.has(w)) && (k.includes(' ') || k.length > 4) && !GENERIC.has(k.split(' ').pop())) put(k, 'town', k); });
    return LEX;
  }
  function parse(text) {
    const lex = lexicon(), orig = text.trim();
    const t = norm(text.replace(/(\d)\s*[-–—]\s*(\d)/g, '$1 to $2').replace(/%/g, ' percent '));
    const w = t ? t.split(' ') : [], used = new Array(w.length).fill(false);
    const got = { dev: [], place: [], type: [], proj: [], town: [], cmd: new Set(), y0: '', y1: '', per: '', n: 0 }, chips = [];
    const order = [];              // entities in the order typed, for Compare
    let i = 0;
    const join = (a, b) => w.slice(a, b).join(' ');
    const eat = (a, b) => { for (let k = a; k < b; k++) used[k] = true; };
    const isY = x => /^(19|20)\d\d$/.test(x || '');
    const numOf = x => /^\d{1,3}$/.test(x || '') ? +x : WORDNUM[x] || 0;
    while (i < w.length) {
      /* time and counts */
      const rest = join(i, i + 6); let m;
      const take = n => { eat(i, i + n); i += n; };
      if ((m = /^((?:19|20)\d\d) (?:to|until|till|through|and) ((?:19|20)\d\d)\b/.exec(rest))) { [got.y0, got.y1] = [m[1], m[2]].sort(); take(3); continue; }
      if (/^between (19|20)\d\d and (19|20)\d\d\b/.test(rest)) { [got.y0, got.y1] = [w[i + 1], w[i + 3]].sort(); take(4); continue; }
      if (['since', 'from', 'after'].includes(w[i]) && isY(w[i + 1]) && !(w[i + 2] === 'to' && isY(w[i + 3]))) { got.y0 = w[i] === 'after' ? String(+w[i + 1] + 1) : w[i + 1]; take(2); continue; }
      if (['before', 'until', 'till'].includes(w[i]) && isY(w[i + 1])) { got.y1 = w[i] === 'before' ? String(+w[i + 1] - 1) : w[i + 1]; take(2); continue; }
      if ((m = /^(?:last|past|recent|previous)( \w+)? (years?|weeks?|months?|days?)\b/.exec(rest))) {
        const word = (m[1] || '').trim(), n = word ? numOf(word) : 1, u = m[2].replace(/s$/, '');
        if (n && u !== 'day') {
          if (u === 'year') { if (word) { got.y0 = String(THIS_YEAR - n + 1); got.y1 = String(THIS_YEAR); } else got.y0 = got.y1 = String(THIS_YEAR - 1); }
          else if (u === 'week') got.per = 'w' + n;
          else if (!word) got.per = 'm1';
          else got.per = 'w' + Math.round(n * 365.25 / 12 / 7);
          take(word ? 3 : 2); continue;
        }
      }
      /* "sold nothing in 4 weeks", "5 years": the same as "last 4 weeks". */
      if (numOf(w[i]) && /^(years?|weeks?|months?)$/.test(w[i + 1] || '')) {
        const n = numOf(w[i]), u = w[i + 1].replace(/s$/, '');
        if (u === 'year') { got.y0 = String(THIS_YEAR - n + 1); got.y1 = String(THIS_YEAR); } else got.per = 'w' + (u === 'week' ? n : Math.round(n * 365.25 / 12 / 7));
        take(2); continue;
      }
      if (w[i] === 'this' && ['year', 'week', 'month'].includes(w[i + 1])) { if (w[i + 1] === 'year') got.y0 = got.y1 = String(THIS_YEAR); else got.per = w[i + 1] === 'week' ? 'w0' : 'm0'; take(2); continue; }
      if (isY(w[i])) { if (!got.y0) got.y0 = got.y1 = w[i]; else if (w[i] > got.y1) got.y1 = w[i]; else got.y0 = w[i]; take(1); continue; }
      /* longest known phrase */
      let hit = null, len = 0;
      for (let n = Math.min(9, w.length - i); n > 0; n--) { const e = lex.get(join(i, i + n)); if (e) { hit = e; len = n; break; } }
      const num = numOf(w[i]);
      if (num && !(hit && len > 1)) { if (['projects', 'project', 'best', 'top', 'fastest', 'slowest', 'developers', 'worst'].includes(w[i + 1]) || ['top', 'best', 'bottom', 'worst', 'first', 'fastest', 'slowest', 'lowest', 'highest', 'unsold', 'leading'].includes(w[i - 1])) { got.n = num; take(1); continue; } }
      const mon = w[i].length > 2 ? MONTHS.findIndex(x => x === w[i] || (x.slice(0, 3) === w[i]) || (w[i] === 'sept' && x === 'september')) : -1;
      if (mon >= 0 && !(hit && len > 1) && (w[i] !== 'may' || isY(w[i + 1]) || w[i - 1] === 'in')) {
        const y = isY(w[i + 1]) ? +w[i + 1] : (mon + 1 <= +DATA.todayDate.slice(5, 7) ? THIS_YEAR : THIS_YEAR - 1);
        got.per = 'M' + y + '-' + String(mon + 1).padStart(2, '0'); take(isY(w[i + 1]) ? 2 : 1); continue;
      }
      if (hit) {
        const pick = ['cmd', 'dev', 'place', 'type', 'proj', 'town'].map(k => hit.filter(h => h.kind === k)).find(a => a.length);
        const kind = pick[0].kind, ph = join(i, i + len);
        if (kind === 'cmd') pick.forEach(h => got.cmd.add(h.v));
        else if (kind === 'proj' && pick.length === 1) { got.proj.push(pick[0].v); order.push('p:' + pick[0].v); }
        else if (kind === 'proj' || kind === 'town') { got.town.push(ph); order.push('t:' + ph); }
        else { got[kind].push(pick[0].v); if (kind === 'dev') order.push('d:' + pick[0].v); if (kind === 'place') order.push(pick[0].v); }
        eat(i, i + len); i += len; continue;
      }
      if (FILLER.has(w[i]) || (w[i] === 'year' && isY(w[i + 1])) || w[i] === 'years' && isY(w[i + 1])) used[i] = true;
      i++;
    }
    /* What was understood, as chips. */
    [...new Set(got.dev)].forEach(v => chips.push(labelOf(v)));
    [...new Set(got.place)].forEach(v => chips.push(placeName(v)));
    [...new Set(got.type)].forEach(v => chips.push(v));
    [...new Set(got.proj)].forEach(v => chips.push(BYKEY.get(v).name));
    [...new Set(got.town)].forEach(v => chips.push('“' + v + '”'));
    const unknown = w.filter((x, k) => !used[k]);
    const yq = { y0: got.y0, y1: got.y1 };
    if (got.y0 || got.y1) chips.push(yearText(yq));
    if (got.per) chips.push(period({ per: got.per }).label);
    if (got.n) chips.push(got.n + ' rows');

    const base = () => { const q = blank();
      got.dev.forEach(v => q.dev.add(v)); got.place.forEach(v => q.place.add(v));
      q.type = [...new Set(got.type)].length === 1 ? got.type[0] : ''; q.y0 = got.y0; q.y1 = got.y1;
      q.name = [...new Set(got.town.concat(got.proj.map(k => norm(BYKEY.get(k).name))))];
      if (got.n) q.n = got.n; if (got.per) q.per = got.per;
      [...got.cmd].forEach(c => { const [k, v] = c.split(':'); if (k === 'by') q.by = v; if (k === 'low') q.dir = 1; });
      return q; };
    const projQ = () => { const q = base(); q.a = 'projects'; q.picks = [...new Set(got.proj)].slice(0, 6); q.name = []; return q; };
    const groupQ = ents => { const q = base(); q.a = 'groups'; q.ents = ents; if (ents.length) { q.dev = new Set(); q.place = new Set(); } return q; };
    const mk = (a, x) => Object.assign(base(), { a }, x);
    const cmd = k => [...got.cmd].filter(c => c.startsWith(k + ':')).map(c => c.split(':')[1])[0];
    const ents = [...new Set(order.filter(e => /^[dsag]:/.test(e)))], devsN = new Set(got.dev).size, plN = new Set(got.place).size;
    const isCmp = got.cmd.has('cmp:') || got.cmd.has('gby:dev') || got.cmd.has('gby:state');
    let q = null;
    if (got.cmd.has('gby:dev')) { q = groupQ([]); q.gby = 'dev'; q.dev = new Set(); if (cmd('pm') === 'fast') q.by = 'inP'; if (cmd('sv') === 'unsold') q.by = 'unsold'; }
    else if (got.cmd.has('gby:state')) { q = groupQ([]); q.gby = 'state'; q.place = new Set(); if (cmd('pm') === 'fast') q.by = 'inP'; if (cmd('sv') === 'unsold') q.by = 'unsold'; }
    else if (got.cmd.has('cmp:')) {
      if (new Set(got.proj).size > 1 && !ents.length && !got.town.length) q = projQ();
      else if (!got.proj.length && !got.town.length && ents.length > 1) {
        /* "compare UEM and Ecoworld in Johor": two developers, one place to look in. */
        if (devsN > 1 && plN === 1) { q = groupQ([...new Set(got.dev)].map(v => 'd:' + v)); q.place = new Set(got.place); }
        else if (plN > 1 && devsN === 1) { q = groupQ([...new Set(got.place)]); q.dev = new Set(got.dev); }
        else q = groupQ(ents);
      }
    }
    else if (cmd('pm')) q = mk('pace', { pm: cmd('pm') });
    else if (cmd('sv')) q = mk('supply', { sv: cmd('sv') });
    else if ((got.cmd.has('top:') || got.cmd.has('low:')) && got.per) q = mk('pace', { pm: got.cmd.has('low:') ? 'slow' : 'fast' });
    else if (got.cmd.has('top:') || got.cmd.has('low:') || (cmd('by') && !unknown.length)) q = mk('top', {});
    else if (got.per && !got.proj.length) q = mk('pace', { pm: 'fast' });
    if (new Set(got.type).size > 1) q = null;
    const sug = [];
    const add = (label, qq) => { if (sug.length < 4) sug.push({ label, q: qq }); };
    if (new Set(got.proj).size > 1) { add('Compare ' + listOf([...new Set(got.proj)].slice(0, 6).map(k => BYKEY.get(k).name)), projQ()); add('Pace of these projects', mk('pace', { pm: 'fast' })); }
    if (ents.length > 1) add('Compare ' + listOf(ents.map(e => e.startsWith('d:') ? labelOf(e.slice(2)) : placeName(e))), groupQ(ents));
    const b = base(), sc = scopeText(b);
    if (chips.length && new Set(got.type).size < 2) { add('Top 10 by sold %: ' + sc, mk('top', {})); add('Fastest selling: ' + sc, mk('pace', { pm: 'fast' })); add('Launches by year: ' + sc, mk('supply', { sv: 'year' })); add('Most unsold: ' + sc, mk('supply', { sv: 'unsold' })); }
    else if (!chips.length) { add('Top 10 by sold %, all your trackers', blank()); add('No sales in 4 weeks', Object.assign(blank(), { a: 'pace', pm: 'stalled' })); add('Developers compared', Object.assign(blank(), { a: 'groups' })); }
    return { text: orig, q: unknown.length ? null : q, unknown, chips, sug };
  }

  /* ---------- the address ---------- */
  function write() {
    const u = new URLSearchParams(), d = blank(), put = (k, v, dv) => { if (String(v) !== String(dv)) u.set(k, v); };
    put('a', S.a, ''); put('n', S.n, d.n); put('by', S.by, d.by); put('dir', S.dir, d.dir); put('type', S.type, ''); put('y', S.y0 || S.y1 ? S.y0 + '_' + S.y1 : '', '');
    put('dev', [...S.dev].join(','), ''); put('in', [...S.place].join(','), ''); put('name', S.name.join('~'), '');
    put('per', S.per, d.per); put('pm', S.pm, d.pm); put('gby', S.gby, d.gby); put('ents', S.ents.join(','), ''); put('picks', S.picks.join('~'), ''); put('sv', S.sv, d.sv); put('ly', S.ly, d.ly);
    history.replaceState(null, '', '#analysis?' + u.toString());
  }
  function readHash() {
    S = blank();
    const i = location.hash.indexOf('?'); if (i < 0) return;
    const u = new URLSearchParams(location.hash.slice(i + 1)), g = k => u.get(k) || '';
    const oneOf = (v, list, dv) => list.includes(v) ? v : dv;
    S.a = oneOf(g('a'), Object.keys(ANSWERS), 'top'); if (/^\d{1,3}$/.test(g('n'))) S.n = +g('n');
    S.by = oneOf(g('by'), ['pct', 'sold', 'perMonth', 'units', 'unsold', 'inP'], 'pct'); S.dir = g('dir') === '1' ? 1 : -1;
    S.type = oneOf(g('type'), ['Landed', 'High-rise', 'Mixed'], '');
    const y = g('y').split('_'); if (/^\d{4}$/.test(y[0])) S.y0 = y[0]; if (/^\d{4}$/.test(y[1] || '')) S.y1 = y[1];
    const okPlace = v => v.startsWith('s:') ? STATES.includes(v.slice(2)) : codesOf.has(v);
    const okDev = k => DEVS.some(t => t.key === k);
    g('dev').split(',').filter(okDev).forEach(v => S.dev.add(v)); g('in').split(',').filter(okPlace).forEach(v => S.place.add(v));
    S.name = g('name').split('~').map(norm).filter(Boolean); if (/^(w\d+|m\d+|M\d{4}-\d\d|c[\d-]{10}_[\d-]{10})$/.test(g('per'))) S.per = g('per');
    S.pm = oneOf(g('pm'), ['fast', 'slow', 'stalled', 'left'], 'fast'); S.gby = oneOf(g('gby'), ['dev', 'state'], 'dev');
    S.ents = g('ents').split(',').filter(e => e.startsWith('d:') ? okDev(e.slice(2)) : e && okPlace(e)); S.picks = g('picks').split('~').filter(k => BYKEY.has(k)).slice(0, 6);
    S.sv = oneOf(g('sv'), ['year', 'unsold'], 'year'); S.ly = oneOf(g('ly'), ['pct', 'units'], 'pct'); fixBy();
  }
  const BYS = { top: ['pct', 'sold', 'perMonth'], groups: ['pct', 'sold', 'units', 'unsold', 'inP'] };
  function fixBy() { if (BYS[S.a] && !BYS[S.a].includes(S.by)) S.by = 'pct'; }

  /* ---------- controls ---------- */
  function select(host, label, opts, val, on) {
    const l = el('label', 'anf'); l.appendChild(el('span', '', label));
    const s = el('select', 'ssel'); opts.forEach(([v, t]) => { const o = el('option', '', t); o.value = v; s.appendChild(o); });
    s.value = String(val); s.onchange = () => on(s.value); l.appendChild(s); host.appendChild(l); return s;
  }
  function adder(host, label, groups, has, on) {
    const l = el('label', 'anf'); l.appendChild(el('span', '', label));
    const s = el('select', 'ssel'); const o0 = el('option', '', 'Any…'); o0.value = ''; s.appendChild(o0);
    groups.forEach(([g, opts]) => { const og = document.createElement('optgroup'); og.label = g; opts.forEach(([v, t]) => { if (has(v)) return; const o = el('option', '', t); o.value = v; og.appendChild(o); }); if (og.children.length) s.appendChild(og); });
    s.onchange = () => { if (s.value) on(s.value); }; l.appendChild(s); host.appendChild(l); return s;
  }
  const chip = (host, text, off) => { const b = el('button', 'chip anchip', text + ' ×'); b.setAttribute('aria-label', 'Remove ' + text); b.onclick = off; host.appendChild(b); };
  const TABS = [['top', 'Top projects'], ['pace', 'Pace'], ['groups', 'Compare developers / places'], ['projects', 'Compare projects'], ['supply', 'Launches and unsold']];
  const DEV_OPTS = DEVS.map(t => [t.key, t.label]);
  const PLACE_GROUPS = [['States', STATES.map(s => ['s:' + s, s])], ['Your areas', AREAS.map(t => ['a:' + t.key, t.label + ' tracker'])], ['Johor groups', GROUPS.map(g => ['g:' + g.key, g.label])]];
  let boxes = innerWidth >= 640;
  function controls() {
    const tabs = $id('antabs'); tabs.textContent = '';
    TABS.forEach(([k, t]) => { const b = el('button', 'chip', t); b.setAttribute('aria-pressed', String(S.a === k)); b.onclick = () => { S.a = k; fixBy(); show(); }; tabs.appendChild(b); });
    const c = $id('anctl'); c.textContent = '';
    /* Folded on a phone, where the boxes would push the answer off the screen.
       Compare projects opens itself until there is something to compare. */
    const open_ = boxes || (S.a === 'projects' && S.picks.length < 2);
    const fold = el('button', 'chip anfold', open_ ? 'Hide boxes ▴' : 'Change boxes ▾');
    fold.setAttribute('aria-expanded', String(open_));
    fold.onclick = () => { boxes = !open_; controls(); };
    tabs.appendChild(fold);
    if (!open_) return;
    const row = el('div', 'anrow'), chips = el('div', 'chips anchips');
    const set = (k, v) => { S[k] = v; show(); };
    const N = () => select(row, 'Show', [[5, '5'], [10, '10'], [20, '20'], [50, '50'], [0, 'All']].concat([5, 10, 20, 50, 0].includes(S.n) ? [] : [[S.n, String(S.n)]]), S.n, v => set('n', +v));
    const PER = () => {
      const o = [['w0', 'This week so far'], ['w4', 'Last 4 weeks'], ['w8', 'Last 8 weeks'], ['w12', 'Last 12 weeks'], ['m0', 'This month so far'], ['m1', 'Last month']], custom = S.per.startsWith('c');
      if (!custom && !o.some(x => x[0] === S.per)) o.push([S.per, period(S).label]);
      o.push(['c', 'Pick dates…']);
      select(row, 'Period', o, custom ? 'c' : S.per, v => { if (v === 'c') { const p = period(S); S.per = 'c' + p.from + '_' + p.to; } else S.per = v; show(); });
      if (custom) {
        const p = period(S), wk = [...new Set(DATA.weeks.concat(DATA.todayDate, p.from, p.to))].sort().reverse().map(d => [d, fdate(d)]);
        select(row, 'From', wk, p.from, v => { S.per = 'c' + [v, p.to].sort().join('_'); show(); });
        select(row, 'To', wk, p.to, v => { S.per = 'c' + [p.from, v].sort().join('_'); show(); });
      }
    };
    if (S.a === 'top') { N(); select(row, 'Rank by', [['pct', 'Sold %'], ['sold', 'Units sold'], ['perMonth', 'Sold per month since APDL']], S.by, v => set('by', v)); select(row, 'Order', [[-1, 'Highest first'], [1, 'Lowest first']], S.dir, v => set('dir', +v)); }
    if (S.a === 'pace') { select(row, 'Show', [['fast', 'Fastest selling'], ['slow', 'Slowest selling'], ['stalled', 'No sales'], ['left', 'Closest to selling out']], S.pm, v => set('pm', v)); PER(); N(); }
    if (S.a === 'supply') { select(row, 'Show', [['year', 'Launches by year'], ['unsold', 'Most unsold units']], S.sv, v => set('sv', v)); if (S.sv === 'unsold') N(); }
    if (S.a === 'groups') {
      adder(row, 'Compare', [['Developers', DEVS.map(t => ['d:' + t.key, t.label])]].concat(PLACE_GROUPS), v => S.ents.includes(v), v => { S.ents.push(v); show(); });
      if (!S.ents.length) select(row, 'or all', [['dev', 'Developers'], ['state', 'States']], S.gby, v => set('gby', v));
      select(row, 'Rank by', [['pct', 'Sold %'], ['sold', 'Units sold'], ['units', 'Units launched'], ['unsold', 'Unsold units'], ['inP', 'Sold in period']], S.by, v => set('by', v)); PER();
      S.ents.forEach(e => chip(chips, e.startsWith('d:') ? labelOf(e.slice(2)) : placeName(e), () => { S.ents = S.ents.filter(x => x !== e); show(); }));
    }
    if (S.a === 'projects') {
      const l = el('label', 'anf anwide'); l.appendChild(el('span', '', 'Add a project (' + S.picks.length + ' of 6)'));
      const q = el('input', 'sgin'); q.type = 'search'; q.setAttribute('list', 'anplist'); q.placeholder = 'Type a project name'; q.autocomplete = 'off'; q.disabled = S.picks.length >= 6;
      const dl = document.createElement('datalist'); dl.id = 'anplist';
      const opts = new Map();
      BYKEY.forEach((g, k) => { if (S.picks.includes(k)) return; const t = g.name + ' · ' + labelOf(g.tracker); opts.set(t, k); const o = document.createElement('option'); o.value = t; dl.appendChild(o); });
      const pickIt = () => { const k = opts.get(q.value); if (k) { S.picks.push(k); show(); const n = document.querySelector('#anctl input[list]'); if (n) n.focus({ preventScroll: true }); } };
      q.oninput = pickIt; l.appendChild(q); row.appendChild(l); row.appendChild(dl); PER();
      select(row, 'Chart', [['pct', 'Sold %'], ['units', 'Units sold']], S.ly, v => set('ly', v));
      S.picks.forEach(k => chip(chips, BYKEY.get(k).name, () => { S.picks = S.picks.filter(x => x !== k); slot.delete(k); show(); }));
    }
    if (S.a !== 'projects') {
      const devOn = !(S.a === 'groups' && (S.ents.some(e => e.startsWith('d:')) || (!S.ents.length && S.gby === 'dev')));
      const plOn = !(S.a === 'groups' && (S.ents.some(e => !e.startsWith('d:')) || (!S.ents.length && S.gby === 'state')));
      if (devOn) adder(row, 'Developer', [['Developers', DEV_OPTS]], v => S.dev.has(v), v => { S.dev.add(v); show(); });
      if (plOn) adder(row, 'Place', PLACE_GROUPS, v => S.place.has(v), v => { S.place.add(v); show(); });
      select(row, 'Launched from', [['', 'Any year']].concat(YEARS.map(y => [y, y])), S.y0, v => { S.y0 = v; if (S.y1 && v > S.y1) S.y1 = v; show(); });
      select(row, 'to', [['', 'Any year']].concat(YEARS.map(y => [y, y])), S.y1, v => { S.y1 = v; if (v && S.y0 > v) S.y0 = v; show(); });
      select(row, 'Type', [['', 'Any'], ['Landed', 'Landed'], ['High-rise', 'High-rise'], ['Mixed', 'Mixed']], S.type, v => set('type', v));
      if (devOn) [...S.dev].forEach(v => chip(chips, labelOf(v), () => { S.dev.delete(v); show(); }));
      if (plOn) [...S.place].forEach(v => chip(chips, placeName(v), () => { S.place.delete(v); show(); }));
      S.name.forEach(v => chip(chips, properName(v), () => { S.name = S.name.filter(x => x !== v); show(); }));
    }
    c.appendChild(row); if (chips.children.length) c.appendChild(chips);
  }

  /* ---------- the answer ---------- */
  let last = null;
  const cell = (c, r, i) => c.t === 'name' ? c.f(r, i) : FMT[c.t](c.f(r, i));
  function goTo(g) {
    const p = g.rows[0]; route(p.tracker); FOCUS = pkey(p); pickedKey = pkey(p); render();
    const row = [...document.querySelectorAll('#table tr[data-proj]')].find(x => x.dataset.proj === pkey(p));
    if (row) { row.scrollIntoView({ block: 'center' }); row.classList.add('found'); setTimeout(() => row.classList.remove('found'), 2400); }
  }
  function answer() {
    const out = $id('anout'); out.textContent = '';
    const A = ANSWERS[S.a](S); last = A;
    out.appendChild(el('h3', 'anhead', A.head));
    if (A.line) out.appendChild(el('p', 'anline', A.line));
    if (!A.rows.length && S.a !== 'projects') out.appendChild(el('p', 'anline', 'No tracked project fits.'));
    out.appendChild(el('p', 'note', A.note));
    if (!A.rows.length) return;
    const bar = el('div', 'anbtns'), btn = (t, f) => { const b = el('button', 'ghost', t); b.onclick = () => f(b); bar.appendChild(b); };
    if (A.line) btn('Copy sentence', b => copy(A.head + '. ' + A.line, b));
    btn('Copy table', b => copy([A.cols.map(c => c.h)].concat(A.rows.map((r, i) => A.cols.map(c => cell(c, r, i)))).map(r => r.join('\t')).join('\n'), b));
    btn('Download Excel', () => download(A));
    out.appendChild(bar);
    const ch = el('div', 'anchart'); out.appendChild(ch); A.chart(ch);
    const tb = el('table'), hr = el('tr'), th = el('thead'), bd = el('tbody');
    const leftAl = c => c.t === 'name' || c.t === 'text';
    A.cols.forEach(c => hr.appendChild(el('th', leftAl(c) ? 'l' : '', c.h))); th.appendChild(hr); tb.appendChild(th);
    A.rows.forEach((r, i) => {
      const tr = el('tr');
      A.cols.forEach(c => {
        const td = el('td', leftAl(c) ? 'l' : '');
        if (c.t === 'name') {
          td.classList.add('nm'); const b = el('button', 'anlink', r.name); b.title = 'Open on the ' + labelOf(r.tracker) + ' tracker'; b.onclick = () => goTo(r); td.appendChild(b);
          if (r.all > 1) td.appendChild(el('span', 'sotag', r.phases === r.all ? r.phases + ' phases' : r.phases + ' of ' + r.all + ' phases'));
          if (r.units && r.sold >= r.units) td.appendChild(el('span', 'sotag', 'Sold out'));
        } else td.textContent = cell(c, r, i);
        tr.appendChild(td);
      });
      bd.appendChild(tr);
    });
    tb.appendChild(bd); const sc = el('div', 'scroll tall antab'); sc.appendChild(tb); out.appendChild(sc);
  }
  function copy(text, b) {
    const was = b.textContent, done = ok => { b.textContent = ok ? 'Copied' : 'Could not copy'; setTimeout(() => { b.textContent = was; }, 1600); };
    const old = () => { const t = el('textarea'); t.value = text; t.style.position = 'fixed'; t.style.opacity = '0'; document.body.appendChild(t); t.select(); let ok = false; try { ok = document.execCommand('copy'); } catch (e) {} t.remove(); done(ok); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(() => done(true), old); else old();
  }

  /* ---------- a small .xlsx, written by hand ----------
     Five XML files in an uncompressed zip: enough for one sheet, no library. */
  const CRC = (() => { const t = []; for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
  const crc = u => { let c = 0xFFFFFFFF; for (let i = 0; i < u.length; i++) c = CRC[(c ^ u[i]) & 255] ^ (c >>> 8); return (c ^ 0xFFFFFFFF) >>> 0; };
  function zip(files) {
    const enc = new TextEncoder(), parts = [], dir = []; let off = 0;
    const le = (n, b) => { const a = []; for (let i = 0; i < b; i++) a.push((n >>> (8 * i)) & 255); return a; };
    files.forEach(([name, text]) => {
      const nm = enc.encode(name), data = enc.encode(text), head = [...le(20, 2), ...le(0x0800, 2), ...le(0, 2), ...le(0, 2), ...le(0x21, 2), ...le(crc(data), 4), ...le(data.length, 4), ...le(data.length, 4), ...le(nm.length, 2), ...le(0, 2)];
      const loc = new Uint8Array([...le(0x04034b50, 4), ...head]); parts.push(loc, nm, data);
      dir.push(new Uint8Array([...le(0x02014b50, 4), ...le(20, 2), ...head, ...le(0, 2), ...le(0, 2), ...le(0, 2), ...le(0, 4), ...le(off, 4)]), nm);
      off += loc.length + nm.length + data.length;
    });
    const dl = dir.reduce((a, x) => a + x.length, 0);
    return new Blob([...parts, ...dir, new Uint8Array([...le(0x06054b50, 4), ...le(0, 4), ...le(files.length, 2), ...le(files.length, 2), ...le(dl, 4), ...le(off, 4), ...le(0, 2)])], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
  }
  function xlsx(A) {
    const X = s => String(s).replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    const ref = (c, r) => { let s = ''; for (let n = c + 1; n; n = Math.floor((n - 1) / 26)) s = String.fromCharCode(65 + (n - 1) % 26) + s; return s + r; };
    const str = (c, r, v, st) => `<c r="${ref(c, r)}" t="inlineStr"${st ? ` s="${st}"` : ''}><is><t xml:space="preserve">${X(v)}</t></is></c>`;
    const n = (c, r, v, st) => `<c r="${ref(c, r)}" s="${st}"><v>${v}</v></c>`;
    /* s: 1 bold, 2 whole number, 3 percent, 4 one decimal, 5 date */
    const serial = iso => Math.round(Date.parse(iso + 'T00:00:00Z') / 864e5) + 25569;
    const rows = [`<row r="1">${str(0, 1, A.head, 1)}</row>`, `<row r="2">${str(0, 2, A.line || '')}</row>`, `<row r="3">${str(0, 3, A.note)}</row>`];
    rows.push(`<row r="5">${A.cols.map((c, i) => str(i, 5, c.h, 1)).join('')}</row>`);
    A.rows.forEach((r, k) => {
      const R = 6 + k;
      rows.push(`<row r="${R}">${A.cols.map((c, i) => { const v = c.f(r, k);
        if (nil(v) || v === '') return '';
        return c.t === 'int' || c.t === 'plus' ? n(i, R, v, 2) : c.t === 'pct' ? n(i, R, v, 3) : c.t === 'dec' ? n(i, R, v, 4) : c.t === 'date' ? n(i, R, serial(v), 5) : str(i, R, v); }).join('')}</row>`);
    });
    const wide_ = A.cols.map((c, i) => `<col min="${i + 1}" max="${i + 1}" width="${c.t === 'name' ? 42 : c.t === 'text' ? 28 : 14}" customWidth="1"/>`).join('');
    const ns = 'http://schemas.openxmlformats.org/', hd = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>';
    return zip([
      ['[Content_Types].xml', `${hd}<Types xmlns="${ns}package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>`],
      ['_rels/.rels', `${hd}<Relationships xmlns="${ns}package/2006/relationships"><Relationship Id="rId1" Type="${ns}officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>`],
      ['xl/workbook.xml', `${hd}<workbook xmlns="${ns}spreadsheetml/2006/main" xmlns:r="${ns}officeDocument/2006/relationships"><sheets><sheet name="Analysis" sheetId="1" r:id="rId1"/></sheets></workbook>`],
      ['xl/_rels/workbook.xml.rels', `${hd}<Relationships xmlns="${ns}package/2006/relationships"><Relationship Id="rId1" Type="${ns}officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="${ns}officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>`],
      ['xl/styles.xml', `${hd}<styleSheet xmlns="${ns}spreadsheetml/2006/main"><numFmts count="3"><numFmt numFmtId="166" formatCode="#,##0.0"/><numFmt numFmtId="164" formatCode="0.0%"/><numFmt numFmtId="165" formatCode="dd mmm yyyy"/></numFmts><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="6"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/><xf numFmtId="3" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/><xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/><xf numFmtId="166" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/><xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>`],
      ['xl/worksheets/sheet1.xml', `${hd}<worksheet xmlns="${ns}spreadsheetml/2006/main"><cols>${wide_}</cols><sheetData>${rows.join('')}</sheetData></worksheet>`],
    ]);
  }
  function download(A) {
    const a = el('a'); a.href = URL.createObjectURL(xlsx(A));
    a.download = 'TEDUH ' + A.head.replace(/[^\w %&,–-]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 80) + ' ' + DATA.todayDate + '.xlsx';
    document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  }

  /* ---------- asking ---------- */
  function readBack(r) {
    const box = $id('anread'); box.textContent = ''; box.hidden = !r;
    if (!r) return;
    if (r.q) { box.className = 'anread ok'; box.appendChild(el('span', '', 'Read as: ')); box.appendChild(el('b', '', ANSWERS[r.q.a](r.q).head)); return; }
    box.className = 'anread';
    const line = (t, list) => { const p = el('p'); p.appendChild(el('b', '', t + ' ')); p.appendChild(document.createTextNode(list)); box.appendChild(p); };
    if (r.chips.length) line('Understood:', r.chips.join(' · '));
    if (r.unknown.length) line('Not understood:', '“' + [...new Set(r.unknown)].join('”, “') + '”');
    else line('', 'I can’t tell which analysis you want.');
    if (r.sug.length) {
      box.appendChild(el('p', '', 'Did you mean:'));
      const c = el('div', 'chips'); r.sug.forEach(s => { const b = el('button', 'chip', s.label); b.onclick = () => { S = s.q; fixBy(); readBack(null); show(); }; c.appendChild(b); }); box.appendChild(c);
    }
  }
  function ask(text) {
    if (!text.trim()) return;
    const r = parse(text);
    if (r.q) { S = r.q; fixBy(); }
    readBack(r);
    $id('anex').hidden = true;
    /* Not understood: the last answer goes too, so it cannot pass for this one's. */
    if (r.q) show(true); else { controls(); $id('anout').textContent = ''; }
  }
  const EXAMPLES = ['Top 10 UEM last five years', 'Top 10 KL 2026', 'Fastest selling in Johor last 4 weeks', 'Ecoworld no sales', 'Compare UEM vs Ecoworld vs SP Setia 2022-2026', 'Launches in KL by year'];
  function examples() {
    const c = $id('anex'); if (c.children.length) return;
    EXAMPLES.forEach(t => { const b = el('button', 'chip', t); b.onclick = () => { $id('anq').value = t; ask(t); }; c.appendChild(b); });
  }
  /* Once a box is changed, "Read as" no longer describes what is on screen. */
  function show(asked) { if (asked !== true) readBack(null); write(); controls(); answer(); }
  function open() { examples(); controls(); answer(); }
  const submit = input => e => { e.preventDefault(); ask(input.value); };
  $id('anform').onsubmit = submit($id('anq'));
  $id('homeask').onsubmit = e => {
    e.preventDefault(); const t = $id('homeq').value; if (!t.trim()) return;
    route('analysis'); S = blank(); $id('anq').value = t; $id('homeq').value = ''; render(); scrollTo(0, 0); ask(t);
  };
  return { open, readHash, resize: () => { if (last) answer(); }, reset: () => { S = blank(); readBack(null); $id('anq').value = ''; $id('anex').hidden = false; boxes = innerWidth >= 640; }, parse, ANSWERS, blank, xlsx, get S() { return S; }, set S(v) { S = v; }, show };
})();
