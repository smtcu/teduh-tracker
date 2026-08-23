# TEDUH Competitor Tracker — working notes for Claude

Read this before touching anything. It carries the decisions and constraints that
the code alone does not explain. `README.md` covers first-time setup; this file
covers how to work on the system without breaking it.

## What this is

Samantha tracks competitor housing-unit sales from Malaysia's TEDUH government
portal (`teduh.kpkt.gov.my`) into Excel. The site has no export, so it used to be
copied by hand. This repository automates it: GitHub Actions scrapes TEDUH every
morning, rebuilds a private password-protected website, regenerates three Excel
trackers, and emails a PDF report with a WhatsApp alert.

It runs entirely on GitHub's servers. Her laptop does not need to be on — that
requirement drove the whole architecture.

## How Samantha wants to work

These are her explicit instructions, repeated across the project. Follow them.

- **"Don't give me code first, run things with me."** Discuss the approach and
  verify the reasoning before writing code. Show your working on the data.
- **Follow her Excel exactly.** Where her spreadsheet and TEDUH disagree on a
  project name, developer, total units or a historical figure, her file wins.
  Do not silently "correct" her numbers to match the portal.
- **Never handle credentials.** All secrets live in GitHub Secrets and Cloudflare.
  She sets them herself. Never ask her to paste a password, app password or API
  key into the chat, and never generate one for her.
- **Verify before claiming.** She catches errors. Reconcile arithmetic, check
  totals tie, and say plainly when something does not add up rather than
  smoothing over it.

## The daily / weekly separation — the most important rule

She asked for this explicitly and has caught violations twice.

- **The three Excel trackers change on Fridays only.** One column per week, no
  exceptions. A Saturday figure must never land in a weekly column.
- **Daily data lives separately** in `data/teduh_daily.csv` and drives the website,
  the daily workbook and the daily PDF.

The gate is `IS_FRIDAY` in `scripts/scrape_teduh.py`, decided from the real
calendar date in Malaysia time. It ignores `workflow_dispatch`, so a manual run
can never add a weekly column. The workflow YAML's own Friday check *does* treat a
manual run as Friday, but that only re-runs the build steps against unchanged
history — same data, a file named with today's date. Harmless, occasionally
confusing.

## Repo map

```
projects.csv                     which projects to track — the config driving everything
unit_types.json                  unit-type classification rules for 4 Johor projects
block_groups.json                rolls TEDUH block names into her reported groupings
.github/workflows/weekly-teduh.yml  the pipeline — workflow_dispatch only, no cron
cloudflare-worker/               the Worker that fires workflow_dispatch twice a day
worker.js / wrangler.toml        Cloudflare password gate for the website (unrelated
                                 to cloudflare-worker/ above — different Worker)
scripts/scrape_teduh.py          the scraper — writes all the data files
scripts/unit_types.py            unit-number parsing, classification, block notes
scripts/build_dashboard.py       builds docs/index.html (self-contained, ~47KB)
scripts/build_trackers.py        builds the three weekly .xlsx trackers
scripts/build_daily_xlsx.py      builds the daily workbook
scripts/build_pdf.py             weekly and daily PDF reports (landscape A4)
scripts/build_unit_workbook.py   unit-type and unit-list workbook
scripts/weekly_summary.py        the summary text used in the email and WhatsApp
data/teduh_history.csv           WEEKLY series — Fridays only — drives the Excel files
data/teduh_daily.csv             DAILY series — every run — drives the website
data/teduh_by_type.csv           sold/unsold by unit type, per run
data/teduh_unit_types_weekly.csv weekly unit-type series
data/teduh_units.csv             per-unit rows for the classified Johor projects
docs/index.html                  the dashboard
docs/downloads/                  generated .xlsx and .pdf files
```

## Schedule

The workflow has **no `schedule:` trigger**. It is started by `workflow_dispatch`,
called twice a day by a Cloudflare Worker (`cloudflare-worker/`, deployed as
`teduh-workflow-trigger`):

| Worker cron | UTC | Malaysia time |
|---|---|---|
| `17 23 * * *` | 23:17 | 07:17 next day |
| `0 8 * * *` | 08:00 | 16:00 same day |

GitHub's own cron used to run alongside this and was removed on 23 Aug 2026.
Two reasons, in order of importance:

1. **Overlapping runs corrupt a Friday rebuild.** On 12 Aug 2026 a GitHub-cron run
   and a dispatched run overlapped. Both regenerated the same `.xlsx` and `.pdf`
   files; git cannot merge binaries, so the second run hit a conflict it could not
   resolve, died mid-rebase and left a detached HEAD. `concurrency` queues the
   second run but does not save it — it only no-ops on days where nothing changed.
2. **GitHub's cron is queued and unreliable**, often an hour or more late. That is
   the whole reason the Worker exists.

The Worker holds a fine-grained PAT (repo-scoped, Actions: read and write) as an
encrypted secret named `GITHUB_TOKEN`. It is never in the repo or in the Worker
source — set it with `wrangler secret put`, or in the Cloudflare dashboard.

Note that GitHub auto-disables *scheduled* workflows after 60 days of repository
inactivity. That rule no longer applies here, since there is no `schedule:` left
to disable — but the daily commits keep the repo active regardless.

## The three trackers

| tracker key | file | notes |
|---|---|---|
| `seputeh` | Seputeh Hills | 6 projects, has Launched and Remarks columns |
| `status13` | Klang Valley | 13 projects (renamed from "Developer Sales Status") |
| `johor` | Johor | 14 projects in two groups: Permas Jaya, JBCC |

## projects.csv columns

`tracker, group, no, project, code, developer, launched, total_units, first_new, remarks, pin, unit_types, note_prefix`

- `code` may be comma-separated for multi-code projects; the scraper sums them.
  Parkland by the River is the example — two codes summing to 1,051 on 07.08,
  matching her figure exactly.
- Blank `code` means the project is skipped by the scraper and left blank in Excel
  (The Eclipse is currently in this state).
- `unit_types` names the key(s) in `unit_types.json` for classified projects.
- `group` is the Johor section heading (`Permas Jaya` / `JBCC`).

### remarks vs note_prefix — two different jobs

Both feed the Remarks column, and picking the wrong one loses information.

- **`remarks` replaces the generated note outright.** Use it when the text is the
  whole story and block numbers would add nothing: Seputeh's unit-size lines,
  HillView's sale-scope note.
- **`note_prefix` is a standing caveat that keeps the live numbers after it.**
  Use it when the numbers matter but are misleading without context. Causewayz
  Square is the case: 1,421 of 3,692 sold reads as weak selling until you know
  Block C's 833 units were never released, so its `note_prefix` carries that
  sentence and the block breakdown regenerates behind it every run.

A generated note overwrites a seeded one whenever it is non-empty, so a caveat
left only in `data/teduh_history.csv` *will* be lost on the next scrape. That is
exactly how Causewayz's "Block C is not opened yet" disappeared. Anything that
must survive belongs in one of these two columns.

## block_groups.json

TEDUH's block names are not always the names in her report. This file rolls them
up, keyed by the project's first code:

| project | TEDUH | reported as |
|---|---|---|
| Parkland by the River | `1A` `1B` `2A` `2B` | `Phase 1`, `Phase 2` |
| Causewayz Square | `A` `B1` `B2` `D1` `D2` | `Block A`, `Block B`, `Block D` |

`label` is the word before the name, `"Block "` by default; Parkland sets it to
`""` because "Phase 1" already reads whole. A block that is not listed keeps its
own name, so a new tower appearing on TEDUH shows up rather than being silently
folded into another. Roll-ups never change the arithmetic — verified at the time
of writing: Parkland 667 + 391 = 1,058 and Causewayz 449 + 516 + 456 = 1,421,
both equal to Total Sold.

## TEDUH API

Undocumented JSON, no auth:

- `/api/projek-swasta/{code}` — project detail
- `/api/unit-projek-swasta/{code}` — unit list, each unit has `status: "sold" | "avail"`

**Sandboxed environments usually cannot reach `teduh.kpkt.gov.my`** (the proxy
returns `CONNECT tunnel failed, 403`). GitHub Actions can. That is why the runtime
is Actions rather than anything local. If you need to inspect unit numbers while
developing, a web-fetch tool sometimes gets through where curl does not.

## Unit numbers — read this before touching `block_of`

TEDUH uses two different shapes, and confusing them has caused two separate bugs.

**Three segments = BLOCK-FLOOR-UNIT.** `A-08-03`, `1A-07-01`, `D1-12-01`. The
prefix is a real block. These projects get a Remarks note breaking sales down by
block.

**Two segments = FLOOR-UNIT.** `9-1`, `10-3A`, `12-01`. Single-tower projects; the
prefix is a *floor*, not a block. These have no block breakdown and their Remarks
must stay blank.

Two further wrinkles:

- The unit segment is not always numeric — `A-08-03A` is real (Binastra Cochrane
  has one per floor). `block_of` must not require the segments to parse as
  integers. Requiring that dropped 11 sold units from Binastra's note while
  Total Sold stayed correct.
- Some unit numbers contain stray spaces — HillView Senibong Cove has `A- 01-02`.
  Strip before parsing.

So `block_of` requires **three segments** but does **not** require them to be
numbers. Anything unparseable is bucketed under `OTHER` so the note always sums to
Total Sold; if *every* unit lands in `OTHER` the note returns empty, which is the
correct outcome for a single-tower project.

Johor projects with no blocks: **The Asteriaz** and **Gen Sphere**. About 17 of the
Seputeh and Klang Valley projects are also single-tower, including Residensi Hana,
M Aurora, Arte Star Milano, Residensi Ambien, The Batai and ParkCity Residences.

Blanking a generated note never erases a seeded one — both `build_trackers.py` and
`build_dashboard.py` keep the last **non-empty** note per project code, so the
notes seeded from her Excel survive.

`classify()` is deliberately stricter than `block_of()`. Do not loosen it. It is
verified 100% against her own classified lists: Straits View 291/291, Permas
Heights 925/925, Parkland phase 1 666/666, phase 2 385/385. Exact-unit overrides
beat the general rule — that is what separates `A-6-3` (A2) from `A-7-3` (A).

## Settled data decisions — do not re-litigate

- **HillView Senibong Cove total units = 1500.** TEDUH says 416; her Excel had 383
  at one point. She chose 1500.
- **Parkland total units = 2156**, despite a 2152 conflict elsewhere. Her call.
- **The June 19 / June 26 gaps stay as they are.** "Skip june gap."
- **Calia** is 281 on 31.07 and 284 on 07.08. An earlier 119 was a typo producing
  a false −156.
- **Binastra Cochrane** (`31332-1`, BINASTRA SYNERGY SDN. BHD., 830 units, permit
  02 Jul 2026) was added to Klang Valley as row 14 on 16 Aug 2026. Its 139 sold was
  seeded into `data/teduh_history.csv` dated 2026-08-14 as a baseline, so its first
  NEW SALES window is 5 days rather than 7. Deliberate, and she agreed to it.

## Verification habits that have paid off

- After any change to note generation, check the note sums to Total Sold. The
  scraper prints a `WARN` line when it does not.
- After any change to `unit_types.py`, re-run the classification check against her
  workbook before claiming anything is fixed.
- openpyxl writes formulas, not values. Set `fullCalcOnLoad = True` and verify with
  a recalc pass rather than assuming.
- When rebuilding a file she supplied, diff it cell-for-cell against her upload.

## Charts

The dashboard uses a validated two-colour palette, `#2a78d6` blue and `#eb6834`
orange. Bars are weekly sales, the overlaid line is the 4-week average pace — same
units, **one axis**. Never introduce a dual axis.

## Mobile

The website has to work on a phone. Frozen columns are `position: sticky`; note
that sticky on a `<td>` with a large `colspan` does not keep contents in view — the
inner div has to be the sticky element. On screens under 640px the Remarks and `#`
columns are hidden and the note moves to its own row.

## Practical constraints

Samantha often works from an iPad, editing files directly in the GitHub web UI.
When handing her a change, give a **whole file to select-all-and-paste** rather
than a partial edit — a half-pasted workflow file broke the repo twice. Tell her
explicitly to select all, delete, confirm the box is empty, then paste.
