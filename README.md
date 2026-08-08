# TEDUH Competitor Tracker — automated

Pulls unit-level sales data for your tracked competitor projects from the TEDUH
portal every morning, publishes a private dashboard, and regenerates both Excel
trackers. Everything runs on GitHub's servers — your laptop does not need to be on.

## What runs, and when

Every day at 10:00 AM Malaysia time, GitHub:

1. calls TEDUH's unit API for each project code in `projects.csv` and counts how
   many units are marked sold;
2. appends the snapshot to `data/teduh_daily.csv`, plus a unit-type breakdown in
   `data/teduh_by_type.csv`;
3. on **Fridays only**, also appends to `data/teduh_history.csv` — the weekly series
   behind the Excel trackers, so the spreadsheets keep exactly one column per week;
4. rebuilds the dashboard at `docs/index.html` and both `.xlsx` files in
   `docs/downloads/`;
5. commits everything back to this repository, which republishes the website.

## Part 1 — set up the repository (about 5 minutes)

1. Create a free account at github.com if you do not have one.
2. Click **New repository**, name it `teduh-tracker`, and choose **Private**.
3. On the new repository page click **uploading an existing file**, then drag in
   `projects.csv`, `README.md`, and the `data`, `docs` and `scripts` folders.
   Click **Commit changes**.
4. The schedule file has to be added separately, because browsers hide folders whose
   name starts with a dot. Click **Add file → Create new file**, and in the filename
   box type exactly:

   ```
   .github/workflows/weekly-teduh.yml
   ```

   GitHub turns each `/` into a folder as you type. Open `weekly-teduh.yml` from this
   package in Notepad, copy everything in it, paste it into the big text box, and
   click **Commit changes**.
5. Open the **Actions** tab. If prompted, click **I understand my workflows, go ahead and enable them**.
6. Click **TEDUH tracker refresh** in the left sidebar, then **Run workflow** to test
   it now rather than waiting until tomorrow morning.
7. After a minute or two, open `data/teduh_daily.csv` and confirm new rows appeared
   with today's date. If they did, the data side is working.

## Part 2 — publish the private website (about 10 minutes)

Cloudflare Pages hosts the site free and can put a login in front of it. GitHub's own
free hosting cannot — it only serves public sites — which is why we use Cloudflare.

1. Sign up free at dash.cloudflare.com.
2. In the sidebar choose **Workers & Pages → Create → Pages → Connect to Git**.
3. Authorise Cloudflare to read your GitHub account and pick `teduh-tracker`.
4. On the build settings screen:
   - Framework preset: **None**
   - Build command: **leave empty**
   - Build output directory: `docs`
5. Click **Save and Deploy**. After about a minute you get a URL like
   `teduh-tracker.pages.dev`. The site is live but currently public.
6. Now lock it. In the sidebar go to **Zero Trust → Access → Applications → Add an
   application → Self-hosted**.
   - Application name: `TEDUH tracker`
   - Domain: the `.pages.dev` hostname from step 5
   - Add a policy: name it `Team`, action **Allow**, include **Emails** and list every
     address that should have access — starting with your own.
7. Save. Visiting the site now asks for an email address and sends a one-time code.
   Only the addresses you listed can get in.

Cloudflare Access is free for up to 50 people. To add or remove someone later, edit
that email list — no need to touch the repository.

From then on, every daily commit redeploys the site automatically.

## Adding or removing a project

Edit `projects.csv` on GitHub (click the file, then the pencil icon). One row per project:

| column | meaning |
|---|---|
| `tracker` | `seputeh` or `status13` — which of the two Excel files it belongs to |
| `no` | row number within that tracker |
| `project` | project name as you want it to read |
| `code` | TEDUH project code, e.g. `30216-1`. Leave blank if the project is not on TEDUH yet |
| `developer` | developer name |
| `launched` | `YYYY-MM-DD`, Seputeh tracker only |
| `total_units` | total units, used for the `%` column |
| `first_new` | new sales in the very first recorded week, Seputeh tracker only |
| `remarks` | free text, Seputeh tracker only |

Projects with a blank `code` are skipped by the scraper and left blank in Excel.
To find a project's code, search for it at
teduh.kpkt.gov.my/semakan-status-kemajuan — the code is the number in the first column.

## Files

```
weekly-teduh.yml                  the daily schedule (goes in .github/workflows/)
projects.csv                      which projects to track
data/teduh_daily.csv              one row per project per day — drives the website
data/teduh_history.csv            one row per project per week — drives the Excel files
data/teduh_by_type.csv            sold/unsold split by unit type
docs/index.html                   the dashboard (published by Cloudflare Pages)
docs/downloads/                   the generated .xlsx files
scripts/scrape_teduh.py           the scraper
scripts/build_dashboard.py        builds the website
scripts/build_trackers.py         builds both Excel files
```

## Changing the schedule

Edit the `cron` line in `.github/workflows/weekly-teduh.yml` on GitHub. It is written
in UTC, which is Malaysia time minus 8 hours.

| you want | cron line |
|---|---|
| Daily 10:00 AM | `0 2 * * *` |
| Weekdays 9:00 AM | `0 1 * * 1-5` |
| Fridays only, 10:00 AM | `0 2 * * 5` |

The Friday-only Excel column is decided in the script, not the schedule, so the
spreadsheets stay weekly no matter how often the site refreshes.

## If a run fails

GitHub emails you when a run fails. Open the **Actions** tab and click the failed run
to see which project code could not be fetched. The usual causes are a project code
that changed on TEDUH, or the portal being briefly down — re-running the workflow the
next day is normally enough. Projects that did succeed are still saved, and the site
keeps showing the last good data rather than going blank.
