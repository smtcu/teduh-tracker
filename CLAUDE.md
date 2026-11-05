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
.github/workflows/watch-launches.yml the new-launch watch — runs after the morning refresh
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
scripts/watch_developers.py      new-launch watch -- see its own section below
scripts/apply_resolutions.py     applies her Resolve answers to purple Check notices
data/teduh_watch.csv             what the watch has found (and is still waiting on)
data/teduh_watch_extra.csv       extra things to watch that projects.csv cannot imply
data/teduh_watch_resolved/       one file per answer: <code> = accept | dismiss
prelaunch_sources.csv            pre-launch watch config: developer pages, sitemaps, Lowyat boards
data/prelaunch_finds.csv         signs of life for no-code rows: ads, news, agent pages (see below)
data/prelaunch_pages.csv         pages to keep looking at for no-code rows: agent sites, microsites
data/prelaunch_teduh.csv         TEDUH codes a no-code row hangs on (8 Conlay's suspended 14159-1/-2)
scripts/prelaunch_images.py      one building picture per pre-launch card -- see Pre-launch pictures
data/prelaunch_images.csv        every page it looked at, picture kept or why not
data/prelaunch_images_removed/   her "Wrong picture? Remove" answers, one file per picture id
scripts/selftest.py              pre-flight contract check — see below
data/teduh_history.csv           WEEKLY series — Fridays only — drives the Excel files
data/teduh_daily.csv             DAILY series — every run — drives the website
data/teduh_by_type.csv           sold/unsold by unit type, per run
data/teduh_unit_types_weekly.csv weekly unit-type series
data/teduh_units.csv             per-unit rows for the classified Johor projects
docs/index.html                  the dashboard
docs/downloads/                  generated .xlsx and .pdf files
```

## Schedule

The refresh has **no `schedule:` trigger**. It is started by `workflow_dispatch`,
called once a day by a Cloudflare Worker (`cloudflare-worker/`, deployed as
`teduh-workflow-trigger`):

| Worker cron | UTC | Malaysia time |
|---|---|---|
| `17 23 * * *` | 23:17 | 07:17 next day |

From the Actions tab, **Run workflow → What to run → "Rebuild the site only
(no scrape)"** (added 30 Oct 2026) rebuilds from the data already in the repo
in a few minutes: no scrape, no APDL fill, and no weekly files unless it is
Friday. The Worker's dispatches send no value, so they keep the default and
still scrape.

A second refresh at 16:00 MYT (`0 8 * * *`) ran until **9 Oct 2026** and was
removed on her call, to keep Actions minutes down for a private repo.
It was deleted as a Cron Trigger in the Cloudflare dashboard (Worker ->
Settings -> Trigger events), which needs no redeploy; `wrangler.toml` was
updated to match so a later `wrangler deploy` does not bring it back. Mentions
of "the 4pm refresh" further down are history.

The launch watch (`watch-launches.yml`) has no cron either. It runs on
`workflow_run`: GitHub starts it when a refresh finishes, and a job-level `if`
keeps only the morning one (a refresh created in UTC hour 23), so the watch runs
once a day at about 07:55 MYT, right after the morning figures are in. It can
never overlap a refresh because it only starts once one has ended, and the
next is hours away. A manual run from the Actions tab always goes ahead.

GitHub's own cron used to run the refresh alongside this and was removed on
23 Aug 2026. Two reasons, in order of importance:

1. **Overlapping runs corrupt a Friday rebuild.** On 12 Aug 2026 a GitHub-cron run
   and a dispatched run overlapped. Both regenerated the same `.xlsx` and `.pdf`
   files; git cannot merge binaries, so the second run hit a conflict it could not
   resolve, died mid-rebase and left a detached HEAD. `concurrency` queues the
   second run but does not save it — it only no-ops on days where nothing changed.
2. **GitHub's cron is queued and unreliable**, often an hour or more late. That is
   the whole reason the Worker exists.

The launch watch kept a GitHub cron (01:53 UTC) when it was split out on 22 Sep
2026, on the theory that an hour's lateness would not matter. It ran five to six
hours late every day, and on 28 Sep 2026 it started at 07:49 UTC, inside the 4pm
refresh. The watch had found nothing, but it rebuilt the site anyway, and its
commit changed the `generated` timestamp on the single JSON line of
`docs/index.html` that the refresh was also rewriting. The refresh's rebase
conflicted; `git pull --rebase || true` swallowed it; `git push` then failed on
a detached HEAD and the afternoon figures were lost. Three things changed as a
result: the watch now runs on `workflow_run` after the morning refresh instead
of on a cron, it only rebuilds and commits when `data/teduh_watch.csv` or
`projects.csv` actually changed, and every commit step aborts a failed rebase
before retrying, so a real conflict fails visibly instead of leaving the
checkout mid-rebase. A Worker-dispatched watch was the first draft of this fix
and was dropped because redeploying the Worker needs a laptop or a keyboard
select-all in the Cloudflare editor, neither of which the iPad offers.

The Worker holds a fine-grained PAT (repo-scoped, Actions: read and write) as an
encrypted secret named `GITHUB_TOKEN`. It is never in the repo or in the Worker
source — set it with `wrangler secret put`, or in the Cloudflare dashboard.

Note that GitHub auto-disables *scheduled* workflows after 60 days of repository
inactivity. That rule no longer applies here, since there is no `schedule:` left
to disable — but the daily commits keep the repo active regardless.

## scripts/selftest.py — run this before believing an edit is safe

```bash
python scripts/selftest.py
```

It imports every script, asserts the functions one module calls on another all
exist, and re-checks the handful of behaviours this repo has regressed on:
`block_of()`'s two-segment rule, that a roll-up never changes a sum, the
`"… units"` wording, and that every key in `block_groups.json` and every
`unit_types` name in `projects.csv` actually resolves. No network, no writes,
a couple of seconds.

It runs in two places:

- **`.github/workflows/selftest.yml`** — on every push and PR that touches
  `scripts/`, the config files or a workflow. This is the one that matters when
  editing in the GitHub web UI: a bad paste gets a red tick within a minute.
  Data-only commits are filtered out so the bot's daily pushes do not trigger it.
- **A pre-flight step in `weekly-teduh.yml`**, before the scrape, so a broken
  script costs seconds rather than failing part-way through a live run.

Why it exists: on 25 Aug 2026 `unit_types.py` was replaced by a hand-pasted copy
without `regroup()`, which `scrape_teduh.py` calls. Importing the module would
not have caught it — the missing name is only reached inside `main()` — so every
daily run died on its first project until someone noticed. The API section of
this test fails that case in seconds, by name.

Note that a failing pre-flight marks the run failed and prints the reason first,
but the later build steps use `if: always()` and will still attempt to run. That
is the pipeline's existing "publish what we can" behaviour, unchanged here.

## The three trackers

| tracker key | file | notes |
|---|---|---|
| `seputeh` | Seputeh Hills | 7 projects, has a Remarks column |
| `status13` | Klang Valley | 13 projects (renamed from "Developer Sales Status") |
| `johor` | Johor | 14 projects in two groups: Permas Jaya, JBCC |
| `ukay` | Ukay | 17 projects, flat list, no group headings |

## projects.csv columns

`tracker, group, no, project, code, developer, launched, apdl, total_units, first_new, remarks, pin, unit_types, note_prefix`

- `code` may be comma-separated for multi-code projects; the scraper sums them.
  Parkland by the River is the example — two codes summing to 1,051 on 07.08,
  matching her figure exactly.
- Blank `code` means the project is skipped by the scraper and left blank in Excel
  (The Eclipse is currently in this state).
- `unit_types` names the key(s) in `unit_types.json` for classified projects.
- `group` is the Johor section heading (`Permas Jaya` / `JBCC`).

### apdl — the advertising-permit date

`apdl` is the **earliest** advertising-permit start date for the project: the
`Tarikh Sah Laku Permit Terkini` begin date, or the earliest entry under
`Senarai Permit Terdahulu` where the permit has been renewed. TEDUH's *current*
permit start is often years later than the first one -- Residensi Rimba Flora
reads 23 May 2026 today but first opened 23 May 2023, and 2023 is the answer.

It is stored per project rather than fetched each run, because it never changes
once issued and fetching it would mean a second API call per project.

It **replaced the Launched date column on 01 Sep 2026**, in every tracker and on
the website, and sits immediately before TOTAL UNIT. The `launched` column is
still in projects.csv but nothing renders it. Blank-code rows have no APDL date.

On the website the frozen columns are now `#`, PROJECT, APDL DATE and TOTAL
UNITS (`.stick` .. `.stick4`); APDL is dropped below 760px, where four frozen
columns would leave nothing for the figures.

### remarks vs note_prefix — two different jobs

A third rule sits on top since 02 Sep 2026: a remark the data has **outgrown**
is suppressed at build time -- everywhere at once, projects.csv untouched.
Exactly two families, matched against the whole remark only (lowercased,
trailing full stop ignored), never as a substring:

- "Not yet launched" (and variants) stops printing once the row has a code
  **and** recorded sales. MAIA's first sold unit is what prompted this.
- "No TEDUH code" (and variants) stops printing once the row has a code.

The rule lives as `stale_remark()` in both build_trackers.py and
build_dashboard.py, kept identical, and selftest.py checks the two copies
agree. A remark that merely *contains* one of the phrases is left alone --
"No unit found on TEDUH" (20Trees) is not in the list and still prints,
because it stays true.

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

## The new-launch watch

`scripts/watch_developers.py` runs in its own workflow (`watch-launches.yml`,
started by GitHub when the morning refresh finishes) and answers "did a developer I track
register something new on TEDUH?". It probes one code past
each tracked developer's highest known phase (new registrations always take
the next `-N` -- MAIA arrived as 30141-2, Binastra Cochrane as 31332-1), and
re-checks registered-but-unlicensed codes for a permit; Ukay Spring sat that
way as 8763-2 for months. Known phases come from projects.csv,
data/projects_index.csv and the watch file itself, so nothing is probed twice,
and the network manners are imported from fill_apdl.py.

Finds go to `data/teduh_watch.csv`. The website then shows a **+N badge** on
that developer's tracker button and an orange note above the table, for
`BADGE_DAYS` (2 -- her call, down from 7) from `first_seen`. **A find that
already holds a sales permit is appended to its developer tracker in
projects.csv automatically** (registered TEDUH name, SPV, TEDUH unit count),
so the note reports something that happened; a permitless find waits and joins
the day its permit is issued. The four **area trackers are never written to**
-- which projects belong to Seputeh, Klang Valley, Johor or Ukay stays her
curation -- and nothing is emailed either way.

`data/teduh_watch_extra.csv` (`value,label,trackers`) lists what projects.csv
cannot imply: a dormant code to watch for a permit (`8763-2`), or a bare
developer code to watch for phases. `trackers` is a semicolon list of tracker
keys whose button should carry the badge.

A bare developer code whose `label` is the exact name of a **code-less row**
in one of its `trackers` (case aside) claims that row: `31361` -> THE SHANG
RESIDENCE, `31510` (SUCCESS GLO SDN. BHD.) -> Majestic PD Township*. Since
03 Nov 2026 (her call: "I want to confirm first") every phase found under a
claimed code is a **`name-match` notice on that row** -- purple, never
auto-added, permit or not. Her Accept fills the code into her row; Dismiss
changes nothing. The claim lapses once the row has a code. Logic is
`claimed_rows()` in watch_developers.py; selftest.py checks it.

Since 04 Sep 2026 there is also a **name watch**: every projects.csv row with
a blank code gets a TEDUH `q=` search on the most distinctive word of its
marketing name (generic words -- taman, residensi, park -- are skipped). A hit
that is not already tracked, in the register snapshot, or in the watch file
becomes a `name-match` notice: badge plus a "possible TEDUH match for X" note.
Name matches are **never auto-added** -- registered names rarely resemble
marketing names, so the match is a guess for her to confirm. This is how a
code eventually surfaces for Aetas Taman Desa, Chin Hin Ulu Kelang and
Villaria without anyone re-searching by hand.

Since 12 Oct 2026 the name watch searches **every** distinctive word, not just
the longest, and also matches the newest registrations from the SPV sweep
locally with hyphens and apostrophes closed up. Hanya Wahyu (31436-1) is why:
TEDUH registered it as RESIDENSI HAN-YA WAHYU, and its `q=` search for "hanya"
does not match HAN-YA.

A name-watch hit whose SPV name carries **another** tracker's name is dropped
as that developer's launch (D'NURI's EXSIM MX4 was once offered to BRDB) --
unless the SPV's email domain belongs to the tracker doing the search. Since
31 Oct 2026: M Mira (11606-3) was found by "mira" and then dropped, because its
SPV is MAXIM HEIGHTS SDN. BHD. -- but it registers `@mahsing.com.my` and is
Mah Sing's (so is 11606-2, M Adora).

The SPV sweep also matches on **email domain** when the SPV's name carries no
family name. TS Law's SPVs (PLAZA SENTOSA PROPERTIES, L & T REALTY, SKYLINE
EMBASSY, and 31436's) never say TS LAW, but all register `@tslawland.com`. The
domain map is built each run from the emails of SPVs already tracked
(`data/developers.csv`), skipping webmail, domains shared by two trackers, and
domains a tracker only borrowed through a JV (tracked SPVs must be at least a
quarter of that domain's SPVs -- this drops `@sunway.com.my`, which Majestic
Gen holds through one Sunway JV). SPVs newer than the developers.csv crawl cost
one detail fetch each, capped at `EMAIL_CHECKS_MAX` (40) per run. An email
match is a `new-spv` notice whose label is the domain; never auto-added.

**Colours on the site.** Finds that need her judgment -- `new-spv` (family
name or email domain) and `name-match` -- are never added, and show **purple**
(`--check`): a purple-tinted "Check:" banner and a purple `+N` on the tracker
button. Finds the watch added or that are informational keep a blue-edged
"Auto:" banner and an orange `+N`. A button can carry both pills.

**Purple stays until she answers it** (orange keeps `BADGE_DAYS`). The banner's
"Resolve…" link reveals two links to GitHub's new-file page, pre-filled as
`data/teduh_watch_resolved/<code>` containing `accept` or `dismiss`. Tapping
Commit there is the confirmation; only someone with write access to the repo
can, so a stray tap by a viewer does nothing. That push starts the refresh,
whose first step, `scripts/apply_resolutions.py`, applies it before the scrape
decision:

- accept on a `name-match` fills the code into the code-less row it matched
  (her name and total units stay) -- never a new row;
- accept on a `new-spv` appends a row to that developer tracker;
- dismiss marks the find `dismissed` and changes nothing else.

The files stay as the record and re-applying is a no-op. A new-SPV find whose
name also matches a code-less row in the same tracker is recorded as a
name-match on that row, so accepting it cannot duplicate the row (Hanya Wahyu
matched both ways). A guess whose permit arrives keeps its kind -- it is
never auto-added on permit day.

The script swallows its own failures -- a missed probe is caught on the next
run, and the watch must never cost the day's sales figures. On a day it finds
nothing it commits nothing: the site rebuild and the commit are skipped, since a
timestamp-only commit is what collided with the refresh on 28 Sep 2026. Sabah, Vietnam and industrial projects can never appear
here: they are outside TEDUH entirely.

## Pre-launch watch -- rows with no code yet

Added 29 Oct 2026, phase 1 of 6 (design agreed with her the same day). The
site's **Pre-launch** button (in the Areas row) lists every projects.csv row
with no TEDUH code, with what has been seen of it, closest to launch first. A
row leaves the list the day it gets a code; its finds stay in the files.

- `data/prelaunch_finds.csv` -- one line per sign of life (an ad, a news item,
  an agent page): stage, event date, ad start date, permit, developer or agent
  page, number of ads, price from, note. Stage is one of `STAGES` in
  build_dashboard.py: Register interest, Private viewing / VVIP, Gallery opens,
  Official launch, Launched. Fields not stated in the source stay **blank or
  "not shown" / "not stated" -- never a guess**. A blank `project` means a new
  project in one of her areas, not on any tracker: a purple Check notice.
- `data/prelaunch_pages.csv` -- pages to keep looking at (agent sites with
  floor plans, RSVP / landing pages, microsites). Store URLs **without**
  tracking codes (`gclid`, `gad_source`, `gbraid`): the agent sites she finds
  come from Google search ads and carry them.
- Both are keyed by tracker + project name, the only key a no-code row has;
  selftest.py fails a line that matches no row.
- The tracker that owns a row shows a blue "Seen:" line and a blue count on
  its button. Blue = information, nothing added. **Nothing in the pre-launch
  watch ever writes projects.csv** -- an accept (phase 4) is always hers.

Her own method, which the watch copies: search the project or area keywords,
collect agent sites and Lowyat threads (Property Talk and Property Q&A), then
**verify** each one -- the same name can be another project (Shang Villa,
the Melaka Shang Height projects), and a correct find can carry a different
name (HAN-YA). Verification is shown as evidence for her to judge, never
decided silently.

**Phase 2, the daily GitHub sources** (built 30 Oct 2026, approved plan):
`scripts/watch_prelaunch.py`, a step in watch-launches.yml after the
developer watch, 10-minute cap, `continue-on-error`. It reads Google News RSS
(one search per no-code row, one per area word), the `developer` / `sitemap`
/ `forum` rows of prelaunch_sources.csv (rows whose probe says blocked,
browser only, laptop or untested are skipped; social rows are for the laptop
Run C) and the saved pages. It writes only data/prelaunch_finds.csv (status
"new") and its memory, data/prelaunch_seen.json -- **the first run with no
memory file is a silent baseline**. Ticks per find: name, place, developer,
size, current (6 months), not resale; Strong = name + place + developer +
current + not resale (her rule, 29 Oct). Place words come from the name after
"@", an area tracker's words, and data/prelaunch_places.csv (projects.csv has
no place column). One-word names ("The Eclipse", "Permas") are searched and
count only next to their developer (`"The Eclipse"` alone is solar eclipses).
News looks back 30 days, except each no-code row's first search, which has no
date limit (seen.json "backfilled" lists the rows done; name-only and area
matches from it are dropped). `--report FILE` lists what it would find and writes nothing.
Strong-find emails (a GitHub issue) are **not switched on yet**: her choice
was to watch the page for a week first.

On the page, a row pools its finds: stage and event date from the furthest
stage, the other columns from the newest find that stated something, facts
merged, and a Source line linking each find's exact ad, post or article. A
"Seen:" line on a tracker opens Pre-launch at that row, outlined.

**Phase 4, her Accept / Dismiss** (built 30 Oct 2026): each purple "Check:
new in ..." notice has a "Resolve…" link (Add to the area tracker / dismiss),
and each source in a project's pop-up has "Wrong project? Dismiss this
source". Like the developer watch, each opens GitHub's new-file page for
`data/prelaunch_resolved/<find id>` = accept | dismiss; committing it is the
answer. The refresh runs scripts/apply_prelaunch_resolutions.py right after
apply_resolutions.py: dismiss marks the find dismissed; accept on a
new-in-area check adds a **code-less row** to that area tracker (name,
developer, units from the notice; "accept Other Name" overrides the name);
accept on a row's own find marks it accepted. The find id is a hash of
seen, tracker, url and note (never project or status, which an answer
changes) -- `find_id()`, shared with build_dashboard.py. selftest flags an
answer file whose find has gone.

**TEDUH status for a no-code row** (built 03 Nov 2026): some no-code rows
hang on TEDUH codes that are deliberately not tracked. 8 Conlay (Armani) is
KSK Land's suspended project, 14159-1 Block A and 14159-2 Block B under
DAMAI CITY SDN. BHD., being taken over by Magna Prima (to be renamed Hallson
Group); her suspended-era figures are in its `note_prefix`. A relaunch may
rename it, which the "Conlay" name watch would miss, so
`data/prelaunch_teduh.csv` (`tracker,project,value,label`) lists the codes
and `watch_prelaunch.py` reads them first every run: registered name, SPV,
TEDUH status, current permit start/end, permits on record, units and sold
(one detail + one unit-list request per code). The first reading is a find
(the row's TEDUH status); after that a find is made only when one of those
changes, listing old -> new. A bare developer code (`14159`) is also probed
up to 3 phases past the highest known, so a 14159-3 shows up and is followed
from then on. Finds are kind `teduh`, stage blank, with the permit in the
Permit column; memory is seen.json `teduh` / `teduh_next`. Like everything
in the pre-launch watch it never writes projects.csv -- the codes go on the
row only when she says so. Not in teduh_watch_extra.csv on purpose: there
the old expired permit would read as a new one and auto-add a duplicate row.

**Pre-launch pictures** (built 5 Nov 2026, her rules): each card can show one
picture of the **whole building, never a logo**, from **credible sources only**
-- the row's `official` pages in prelaunch_pages.csv, the developer's website
in prelaunch_sources.csv (not its front page), or an established news site
(`NEWS_OUTLETS` / `NEWS_HOSTS`). Never agent sites, portals, forums or social
media. Pictures are **linked to the source, never copied**, lazy-loaded on
the Pre-launch view only. `scripts/prelaunch_images.py` takes each page's
preview picture (og:image) and drops logo-named, event-named (opening
ceremony, award), small (<600px), square and shared pictures; a news story
must name the project and not be about an event. The first test turned up
The Eclipse's opening ceremony and an LBS awards photo for Sherwood -- that
is why the event rules exist -- and wrongly dropped EdgeProp's Selayang
Mulia render for "brand" in its name, so "brand" is not a logo word. Her
"Wrong picture? Remove" link files `data/prelaunch_images_removed/<id>`,
which triggers a rebuild-only refresh. `--report` writes nothing;
`.github/workflows/prelaunch-images-test.yml` runs it on any claude/ branch
push and shows the pictures on the run's Summary page.

Still to come: crt.sh and a search API. From GitHub,
PropertyGuru, iProperty, EdgeProp listings, Bursa and six developer sites
(Armani, UEM, Lagenda, Shang Height, Maxim, Majestic Gen) are blocked --
tested 29 Oct 2026 with scripts/probe_sources.py (Shang Height's address was
wrong then; shangheight.com is untested).

## Suggest a project -- filling a placeholder row

The site's "Suggest a project" form calls the `teduh-workflow-trigger` Worker
(`cloudflare-worker/src/index.js`), which opens a PR against projects.csv;
merging is the approval. Since 13 Oct 2026, once a tracker is picked the form
lists that tracker's rows with **no code** (not-yet-launched placeholders) and
she must say whether the find is one of them. Picking one fills the code into
that row -- her name, total units and remarks stay, a blank developer or
total comes from TEDUH -- instead of appending a duplicate row. Neither path
writes `apdl`: `fill_apdl.py` fills the earliest permit date on the next
refresh (the form used to put the permit *number* there). The same day the
stale-remark rule was extended to `note_prefix`, so a filled placeholder's
"Not launched yet." caveat stops printing once it records sales. Worker
changes only take effect after a `wrangler deploy` from a laptop.

## Website search, badges and code ranges

- The search box matches the marketing name, the **registered TEDUH name**
  (`teduh_name` from the scrape -- Trinity Sensoria is BAYU CERIA, Dawn KLCC
  is MENARA SENJA), every code, and the developer. Picking a result switches
  tracker and selects the project.
- Multi-code projects display as a compressed range: `10279-5 ~ 8`, via
  `code_range()` in build_dashboard.py. projects.csv still stores every code
  in full -- only the display is compressed.

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

### Scrape pace -- one request every 1.1s, shared

`scrape_teduh.py` fetches every code up front with four workers sharing one
clock: TEDUH sees one request every `PAUSE` (1.1s) seconds, whichever worker
sends it. That brought the scrape from ~34 minutes (one code at a time, ~2.4s
each) to ~16. With one daily refresh plus the launch watch that is ~38
minutes a day, ~1,150 a month, against the 2,000 a private repo gets on
GitHub Free (two refreshes came to ~1,650).

Do not raise the pace without a test run. TEDUH rate-limits: on 08 Oct 2026 a
first draft with four workers each pausing on their own (~1.7 requests a
second) was refused with 429 within 45 seconds. The second draft, this one,
ran clean at 15.5 minutes, and both test runs matched the 4pm run on all 778
rows. A 429 holds every worker for TEDUH's `Retry-After` and slows the pace
once per refusal (`push_back`); the circuit breaker (three dead codes in a row
-> exit 3, nothing written) is unchanged.

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

- **Embun / Emery @ Kemensah (ukay tracker), settled 04 Sep 2026.** Titijaya's
  phase 1 is Embun, 12369-1, 51 units, completed Dec 2016. Phase 2 is
  **Emery**: its first 16 units are TEDUH's `12369-2` (registered as "EMBUN",
  APDL 2014-06-25, all sold), and the remaining 36 units are **not on TEDUH**
  -- no 12369-3 exists. Emery's tracker row carries total_units 52 on her
  instruction; the phase walk will catch 12369-3 when it registers.
- **Aetas naming (avaland tracker), 04 Sep 2026.** `20017-1` (Residensi Aetas
  Damansara) is **Aetas Damansara** -- it was mislabelled "Aetas Taman Desa" in
  an earlier sheet. Aetas Taman Desa is a separate, not-yet-launched Avaland
  project tracked with a blank code; the name watch searches for it daily.

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

Since 05 Nov 2026 a phone has two layouts for the weekly tracker, switched by a
**Table | Cards** button above it (phones only): **Table first** (her call), with
a 100 / 75 / 55% zoom; Cards is one card per project with Today and the newest
week, the rest one tap away. The choice is remembered per device
(`teduh.pview2`). Row 2 of the sticky header is measured into `--r1h` by
`fixHead()`, because a fixed 34px left a slit on phones. The cumulative small
multiples use `minmax(0,1fr)` columns: plain `1fr` let nowrap titles push the
whole page wider than the phone. Pre-launch shows the first 3 purple Check
banners and folds the rest behind "Show N more to check". `docs/mobile-draft.html`
is the static draft these came from; it is not rebuilt by the daily run.

## Practical constraints

Samantha often works from an iPad, editing files directly in the GitHub web UI.
When handing her a change, give a **whole file to select-all-and-paste** rather
than a partial edit — a half-pasted workflow file broke the repo twice. Tell her
explicitly to select all, delete, confirm the box is empty, then paste.
