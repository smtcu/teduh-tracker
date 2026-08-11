#!/usr/bin/env python3
"""Rebuild both TEDUH weekly Excel trackers from projects.csv + teduh_history.csv.

Usage: python3 build_trackers.py <projects.csv> <teduh_history.csv> <outdir> [report_date YYYY-MM-DD]

Layout is copied from Samantha's originals:
  seputeh  : NO | PROJECT | CODE | DEVELOPER | Launched | TOTAL UNIT | (NEW SALES,TOTAL SOLD,%) x weeks | Remarks
  status13 : NO | PROJECT | CODE | DEVELOPER | TOTAL UNIT | (SOLD,%) | (NEW SALES,TOTAL SOLD,%) x weeks
NEW SALES and % are live Excel formulas, never hardcoded results.
"""
import csv, sys, os
from datetime import datetime
import openpyxl
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.utils import get_column_letter as L

def F(**k):
    k.setdefault('size', 10)
    return Font(name='Arial', **k)

TH = Side(style='thin'); BORD = Border(left=TH, right=TH, top=TH, bottom=TH)
CTR = Alignment(horizontal='center', vertical='center', wrap_text=True)
LFT = Alignment(horizontal='left', vertical='center', wrap_text=True)
HDR = PatternFill('solid', fgColor='D9E1F2')
NEWFILL = PatternFill('solid', fgColor='FFF2CC')   # highlights the newest week

def cell(ws, r, c, v=None, font=None, align=CTR, fill=None, fmt=None):
    x = ws.cell(r, c, v)
    x.font = font or F(); x.alignment = align; x.border = BORD
    if fill: x.fill = fill
    if fmt: x.number_format = fmt
    return x

def load(projects_csv, history_csv):
    """Return (projects, {tracker: [snapshot_keys...]}, lookup).

    A snapshot is one weekly column. It is keyed by (seq, week) rather than the
    date alone, because the tracker legitimately contains two columns bearing the
    same date -- deduping on date would silently drop a week of history.
    Rows appended by the scraper have a blank seq; they are assigned the next
    sequence number for their tracker, in date order.
    """
    projects = list(csv.DictReader(open(projects_csv, encoding='utf-8')))
    hist = list(csv.DictReader(open(history_csv, encoding='utf-8')))

    maxseq = {}
    for h in hist:
        if str(h.get('seq', '')).strip().isdigit():
            t = h['tracker']
            maxseq[t] = max(maxseq.get(t, 0), int(h['seq']))
    assigned = {}
    for h in sorted(hist, key=lambda x: (x['tracker'], x['week'])):
        if not str(h.get('seq', '')).strip().isdigit():
            k = (h['tracker'], h['week'])
            if k not in assigned:
                maxseq[h['tracker']] = maxseq.get(h['tracker'], 0) + 1
                assigned[k] = maxseq[h['tracker']]

    order, lookup = {}, {}
    for h in hist:
        t = h['tracker']
        seq = int(h['seq']) if str(h.get('seq', '')).strip().isdigit() else assigned[(t, h['week'])]
        snap = (seq, h['week'])
        order.setdefault(t, set()).add(snap)
        v = h['total_sold']
        try: v = int(float(v)) if v not in ('', 'None', None) else None
        except (TypeError, ValueError): v = None
        lookup[(t, snap, h['code'])] = v
    order = {t: sorted(v) for t, v in order.items()}
    return projects, order, lookup

def build_seputeh(projects, weeks, lookup, report_date, path):
    wb = openpyxl.Workbook(); wb.calculation.fullCalcOnLoad = True; ws = wb.active; ws.title = report_date.strftime('%Y%m%d')
    ws['A1'] = 'Teduh Weekly Update: Seputeh Hills Competitor Studies'; ws['A1'].font = F(bold=True, size=12)
    ws['A2'] = 'Report as at ' + report_date.strftime('%d/%m/%Y'); ws['A2'].font = F(bold=True, color='FF0000')
    for i, h in enumerate(['NO','PROJECT','PROJECT \nCODE','DEVELOPER','Launched date','TOTAL \nUNIT'], 1):
        cell(ws, 4, i, h, F(bold=True), fill=HDR)
    col = 7
    for i, (_, wk) in enumerate(weeks):
        last = (i == len(weeks) - 1)
        ws.merge_cells(start_row=3, start_column=col, end_row=3, end_column=col+2)
        cell(ws, 3, col, datetime.strptime(wk, '%Y-%m-%d'), F(bold=True), fmt='DD.MM.YYYY', fill=NEWFILL if last else None)
        for j, h in enumerate(['NEW SALES','TOTAL SOLD','%']):
            cell(ws, 4, col+j, h, F(bold=True), fill=NEWFILL if last else HDR)
        col += 3
    rem = col
    cell(ws, 4, rem, 'Remarks', F(bold=True), fill=HDR)

    rows = sorted((p for p in projects if p['tracker'] == 'seputeh'),
                  key=lambda x: (x.get('pin', '').strip().lower() not in ('yes', 'y', '1', 'true')))
    for r, p in enumerate(rows, 5):
        cell(ws, r, 1, int(p['no']))
        cell(ws, r, 2, p['project'], align=LFT)
        cell(ws, r, 3, p['code'])
        cell(ws, r, 4, p['developer'], align=LFT)
        cell(ws, r, 5, datetime.strptime(p['launched'], '%Y-%m-%d') if p['launched'] else None, fmt='MMM-YY')
        cell(ws, r, 6, int(p['total_units']), fmt='#,##0')
        col, prev = 7, None
        for i, snap in enumerate(weeks):
            v = lookup.get(('seputeh', snap, p['code']))
            fill = NEWFILL if i == len(weeks) - 1 else None
            n, t, pc = cell(ws, r, col, fmt='#,##0', fill=fill), cell(ws, r, col+1, fmt='#,##0', fill=fill), cell(ws, r, col+2, fmt='0.0%', fill=fill)
            if v is not None:
                t.value = v
                n.value = f'={L(col+1)}{r}-{prev}{r}' if prev else (int(p['first_new']) if str(p['first_new']).strip() else None)
                pc.value = f'={L(col+1)}{r}/$F${r}'
                prev = L(col+1)
            col += 3
        cell(ws, r, rem, p['remarks'], align=LFT)

    for c, w in [('A',4),('B',26),('C',10),('D',28),('E',12),('F',8)]:
        ws.column_dimensions[c].width = w
    for c in range(7, rem): ws.column_dimensions[L(c)].width = 9
    ws.column_dimensions[L(rem)].width = 42
    ws.freeze_panes = 'G5'; ws.row_dimensions[4].height = 30
    wb.save(path); return path

def build_status13(projects, weeks, lookup, report_date, path):
    wb = openpyxl.Workbook(); wb.calculation.fullCalcOnLoad = True; ws = wb.active; ws.title = report_date.strftime('%d%m%Y')
    ws['A2'] = 'Report as at ' + report_date.strftime('%d/%m/%Y'); ws['A2'].font = F(bold=True, color='FF0000')
    ws['A3'] = 'TEDUH WEEKLY UPDATE '; ws['A3'].font = F(bold=True, size=12)
    for i, h in enumerate(['NO','PROJECT','PROJECT \nCODE','DEVELOPER','TOTAL \nUNIT'], 1):
        cell(ws, 4, i, h, F(bold=True), fill=HDR)
    ws.merge_cells('F3:G3')
    cell(ws, 3, 6, datetime.strptime(weeks[0][1], '%Y-%m-%d'), F(bold=True), fmt='DD/MM/YYYY')
    cell(ws, 4, 6, 'SOLD', F(bold=True), fill=HDR); cell(ws, 4, 7, '%', F(bold=True), fill=HDR)
    col = 8
    for i, (_, wk) in enumerate(weeks[1:], 1):
        last = (i == len(weeks) - 1)
        ws.merge_cells(start_row=3, start_column=col, end_row=3, end_column=col+2)
        cell(ws, 3, col, datetime.strptime(wk, '%Y-%m-%d'), F(bold=True), fmt='DD/MM/YYYY', fill=NEWFILL if last else None)
        for j, h in enumerate(['NEW SALES ','TOTAL SOLD','%']):
            cell(ws, 4, col+j, h, F(bold=True), fill=NEWFILL if last else HDR)
        col += 3
    end = col

    rows = sorted((p for p in projects if p['tracker'] == 'status13'),
                  key=lambda x: (x.get('pin', '').strip().lower() not in ('yes', 'y', '1', 'true')))
    for r, p in enumerate(rows, 5):
        key = p['code'] if p['code'] else f'NOCODE-R{r}'
        cell(ws, r, 1, int(p['no']))
        cell(ws, r, 2, p['project'], align=LFT)
        cell(ws, r, 3, p['code'])
        cell(ws, r, 4, p['developer'], align=LFT)
        cell(ws, r, 5, int(p['total_units']), fmt='#,##0')
        v0 = lookup.get(('status13', weeks[0], key))
        cell(ws, r, 6, v0, fmt='#,##0')
        cell(ws, r, 7, f'=F{r}/$E${r}' if v0 is not None else None, fmt='0.0%')
        col, prev = 8, ('F' if v0 is not None else None)
        for i, snap in enumerate(weeks[1:], 1):
            v = lookup.get(('status13', snap, key))
            fill = NEWFILL if i == len(weeks) - 1 else None
            n, t, pc = cell(ws, r, col, fmt='#,##0', fill=fill), cell(ws, r, col+1, fmt='#,##0', fill=fill), cell(ws, r, col+2, fmt='0.0%', fill=fill)
            if v is not None:
                t.value = v
                if prev: n.value = f'={L(col+1)}{r}-{prev}{r}'
                pc.value = f'={L(col+1)}{r}/$E${r}'
                prev = L(col+1)
            col += 3

    for c, w in [('A',4),('B',26),('C',10),('D',30),('E',8)]:
        ws.column_dimensions[c].width = w
    for c in range(6, end): ws.column_dimensions[L(c)].width = 9
    ws.freeze_panes = 'F5'; ws.row_dimensions[4].height = 30
    wb.save(path); return path

def build_johor(projects, weeks, lookup, notes, report_date, path):
    """Johor keeps every week ever recorded, in two sections, with a Remarks column."""
    wb = openpyxl.Workbook(); wb.calculation.fullCalcOnLoad = True
    ws = wb.active; ws.title = report_date.strftime('%d%m%Y')
    ws['A2'] = 'Report as at ' + report_date.strftime('%d/%m/%Y'); ws['A2'].font = F(bold=True, color='FF0000')
    ws['A3'] = 'WEEKLY TEDUH SALES REPORT (JB PROJECTS)'; ws['A3'].font = F(bold=True, size=12)
    for i, h in enumerate(['NO', 'PROJECT', 'DEVELOPER', 'TOTAL \nUNIT'], 1):
        cell(ws, 4, i, h, F(bold=True), fill=HDR)
    col = 5
    for i, snap in enumerate(weeks):
        last = (i == len(weeks) - 1)
        ws.merge_cells(start_row=3, start_column=col, end_row=3, end_column=col + 2)
        cell(ws, 3, col, datetime.strptime(snap[1], '%Y-%m-%d'), F(bold=True), fmt='DD/MM/YYYY',
             fill=NEWFILL if last else None)
        for j, h in enumerate(['NEW SALES', 'TOTAL SOLD', 'TOTAL %']):
            cell(ws, 4, col + j, h, F(bold=True), fill=NEWFILL if last else HDR)
        col += 3
    rem_col = col
    cell(ws, 4, rem_col, 'NOTES', F(bold=True), fill=HDR)

    rows = [p for p in projects if p['tracker'] == 'johor']
    r = 5
    group = None
    for p in rows:
        if p.get('group') and p['group'] != group:
            group = p['group']
            cell(ws, r, 1, group, F(bold=True), align=LFT, fill=HDR)
            for c in range(2, rem_col + 1):
                cell(ws, r, c, None, fill=HDR)
            r += 1
        key = (p.get('code') or '').split(',')[0].strip() or f"NOCODE-{p['project']}"
        units = int(p['total_units']) if str(p.get('total_units', '')).strip().isdigit() else 0
        cell(ws, r, 1, int(p['no']))
        cell(ws, r, 2, p['project'], align=LFT)
        cell(ws, r, 3, p['developer'], align=LFT)
        cell(ws, r, 4, units, fmt='#,##0')
        col, prev = 5, None
        for i, snap in enumerate(weeks):
            v = lookup.get(('johor', snap, key))
            fill = NEWFILL if i == len(weeks) - 1 else None
            n = cell(ws, r, col, fmt='#,##0', fill=fill)
            t = cell(ws, r, col + 1, fmt='#,##0', fill=fill)
            pc = cell(ws, r, col + 2, fmt='0.0%', fill=fill)
            if v is not None:
                t.value = v
                if prev:
                    n.value = f'={L(col + 1)}{r}-{prev}{r}'
                pc.value = f'={L(col + 1)}{r}/$D${r}'
                prev = L(col + 1)
            col += 3
        cell(ws, r, rem_col, notes.get(key, p.get('remarks', '')), align=LFT)
        r += 1

    for c, w in [('A', 4), ('B', 26), ('C', 22), ('D', 9)]:
        ws.column_dimensions[c].width = w
    for c in range(5, rem_col):
        ws.column_dimensions[L(c)].width = 9
    ws.column_dimensions[L(rem_col)].width = 46
    ws.freeze_panes = 'E5'; ws.row_dimensions[4].height = 30
    wb.save(path); return path


if __name__ == '__main__':
    pcsv, hcsv, outdir = sys.argv[1], sys.argv[2], sys.argv[3]
    rd = datetime.strptime(sys.argv[4], '%Y-%m-%d') if len(sys.argv) > 4 else datetime.now()
    os.makedirs(outdir, exist_ok=True)
    projects, order, lookup = load(pcsv, hcsv)
    notes = {}
    for row in csv.DictReader(open(hcsv, encoding='utf-8')):
        n = (row.get('block_note') or '').strip()
        if n:
            notes[row.get('code', '')] = n
    p1 = build_seputeh(projects, order['seputeh'], lookup, rd,
                       os.path.join(outdir, rd.strftime('%Y%m%d') + '_Seputeh Hills_Teduh Weekly Update.xlsx'))
    p2 = build_status13(projects, order['status13'], lookup, rd,
                        os.path.join(outdir, rd.strftime('%d%m%Y') + 'Tduh Developer Project Sales Status 13.xlsx'))
    print(p1); print(p2)
    if 'johor' in order:
        p3 = build_johor(projects, order['johor'], lookup, notes, rd,
                         os.path.join(outdir, rd.strftime('%Y%m%d') + '_Johor_Teduh_Weekly_Update.xlsx'))
        print(p3)
