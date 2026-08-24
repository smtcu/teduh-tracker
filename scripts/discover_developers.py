#!/usr/bin/env python3
"""One-off discovery: index every developer registered on TEDUH.

A TEDUH project code is the developer's own code plus a sequence number, so
"31332-1" is project 1 of developer 31332. Asking for a developer's first
project therefore returns that developer's registration details -- company
name, email, business address, registered address -- which is what lets us
group projects by the company that actually markets them, whatever name the
project is registered under.

Writes one row per probed code to data/developers.csv, including codes that
turned out to be empty, so a re-run resumes exactly where the last one stopped.

  python scripts/discover_developers.py --start 1 --end 33000
  python scripts/discover_developers.py --start 1 --end 33000 --minutes 300

Deliberately slow. This is a government portal and the scan only has to happen
once, so --rps defaults to a rate that will not bother anyone.
"""
import argparse, csv, json, os, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

API = "https://teduh.kpkt.gov.my/api/projek-swasta/{code}"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "developers.csv")

FIELDS = ["kod_pemaju", "found", "nama_pemaju", "emel", "telefon",
          "alamat_perniagaan", "alamat_daftar", "status_pemaju",
          "bilangan_projek", "probe_code", "projek_nama", "negeri", "daerah",
          "status_projek"]

PROJ_OUT = os.path.join(ROOT, "data", "projects_index.csv")
PROJ_FIELDS = ["kod_projek", "kod_pemaju", "nama_pemaju", "projek_nama",
               "negeri", "daerah", "unit", "bilik", "bilik_air", "status",
               "permit_mula", "permit_tamat"]


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def pick(d, *names):
    """Fetch the first matching key, ignoring case, spacing and underscores.

    TEDUH mixes snake_case and camelCase in the same object, so matching
    loosely is safer than guessing which spelling a field uses.
    """
    if not isinstance(d, dict):
        return ""
    table = {norm(k): v for k, v in d.items()}
    for n in names:
        v = table.get(norm(n))
        if v not in (None, "", [], {}):
            return v if not isinstance(v, (dict, list)) else ""
    return ""


def find_pemaju(payload):
    """The developer block, wherever it sits in the response."""
    if not isinstance(payload, dict):
        return {}
    direct = payload.get("pemaju")
    if isinstance(direct, dict):
        return direct
    for v in payload.values():                      # fall back to a scan
        if isinstance(v, dict) and any(norm(k) == "kodpemaju" for k in v):
            return v
    return {}


def find_projek(payload):
    if not isinstance(payload, dict):
        return {}
    p = payload.get("projek")
    return p if isinstance(p, dict) else {}


class Limiter:
    """Spaces requests out across all worker threads, and slows down when told to.

    TEDUH answers 429 well below the rate a server of its size could handle, so
    a fixed rate is guesswork. This starts at the requested rate and halves it
    every time the site pushes back, easing part of the way up again after a
    long clean run. Because every thread queues on the same next_at, a penalty
    pauses the whole scan, not just the thread that hit it.
    """

    def __init__(self, rps, floor_rps=0.2):
        self.gap = 1.0 / rps if rps > 0 else 0.0
        self.fast = self.gap                        # never go quicker than asked
        self.slow = 1.0 / floor_rps if floor_rps > 0 else 30.0
        self.lock = threading.Lock()
        self.next_at = 0.0
        self.clean = 0
        self.penalties = 0

    def wait(self):
        if not self.gap:
            return
        with self.lock:
            due = max(time.monotonic(), self.next_at)
            self.next_at = due + self.gap
        delay = due - time.monotonic()
        if delay > 0:
            time.sleep(delay)

    def penalise(self, pause):
        """Back off after a refusal, and hold every thread for `pause` seconds."""
        with self.lock:
            self.gap = min(self.slow, max(self.gap, 0.05) * 2)
            self.next_at = max(self.next_at, time.monotonic() + pause)
            self.clean = 0
            self.penalties += 1
            return self.gap

    def reward(self):
        with self.lock:
            self.clean += 1
            if self.clean >= 300 and self.gap > self.fast:
                self.gap = max(self.fast, self.gap / 1.5)
                self.clean = 0

    def rate(self):
        with self.lock:
            return 1.0 / self.gap if self.gap else 0.0


def retry_after(e, fallback):
    """Seconds the server asked us to wait, if it said."""
    try:
        v = e.headers.get("Retry-After")
        if v and str(v).strip().isdigit():
            return min(300, max(1, int(v)))
    except Exception:
        pass
    return fallback


def fetch(code, limiter, attempts=8):
    """Return the parsed payload, or None if the code does not exist.

    A 404 means no such project and is final -- no retry, since most codes in
    the range are empty and retrying them would multiply the scan for nothing.

    A 429 means we are going too fast. That is not an error to retry blindly:
    it slows the whole scan down and waits, so the next attempt is made at a
    rate the site is willing to serve.
    """
    last = None
    for i in range(attempts):
        limiter.wait()
        try:
            req = Request(API.format(code=code),
                          headers={"User-Agent": UA, "Accept": "application/json"})
            with urlopen(req, timeout=60) as r:
                limiter.reward()
                return json.loads(r.read().decode("utf-8"))
        except HTTPError as e:
            if e.code == 404:
                limiter.reward()
                return None
            last = e
            if e.code in (429, 503):
                pause = retry_after(e, min(120, 15 * (i + 1)))
                limiter.penalise(pause)
                continue                    # the pause is already in the queue
        except (URLError, json.JSONDecodeError, TimeoutError, ValueError) as e:
            last = e
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"{code}: {last}")


def row_from(dev, code, payload):
    pem, proj = find_pemaju(payload), find_projek(payload)
    return {
        "kod_pemaju": pick(pem, "kod_pemaju") or dev,
        "found": "yes",
        "nama_pemaju": pick(pem, "nama", "nama_pemaju"),
        "emel": pick(pem, "emel", "email"),
        "telefon": pick(pem, "telefon"),
        "alamat_perniagaan": pick(pem, "alamat_perniagaan"),
        "alamat_daftar": pick(pem, "alamat_daftar"),
        "status_pemaju": pick(pem, "statusPemaju", "status_pemaju"),
        "bilangan_projek": pick(pem, "bilanganProjek", "bilangan_projek"),
        "probe_code": code,
        "projek_nama": pick(proj, "nama") or pick(payload, "nama", "namaPemajuan"),
        "negeri": pick(proj, "negeri") or pick(payload, "negeri"),
        "daerah": pick(proj, "daerah") or pick(payload, "daerah"),
        "status_projek": pick(payload, "status") or pick(proj, "status"),
    }


def project_row(dev, code, payload, dev_row):
    proj = find_projek(payload)
    units = payload.get("unitSummary")
    if not isinstance(units, dict):
        units = pick(proj, "unitSummary") or {}
        if not isinstance(units, dict):
            units = {}
    return {
        "kod_projek": pick(proj, "kod_projek") or code,
        "kod_pemaju": dev,
        "nama_pemaju": dev_row.get("nama_pemaju", ""),
        "projek_nama": pick(proj, "nama") or pick(payload, "nama"),
        "negeri": pick(proj, "negeri") or pick(payload, "negeri"),
        "daerah": pick(proj, "daerah") or pick(payload, "daerah"),
        "unit": pick(units, "unit", "jumlahUnit", "bilanganUnit"),
        "bilik": pick(units, "bilik"),
        "bilik_air": pick(units, "bilikAir", "bilik_air"),
        "status": pick(payload, "status") or pick(proj, "status"),
        "permit_mula": pick(proj, "permitMula", "permit_mula"),
        "permit_tamat": pick(proj, "permitTamat", "permit_tamat"),
    }


def probe(dev, limiter, depth=3, with_projects=True):
    """Find this developer, and optionally every project it owns.

    Project 1 is usually present, but not always -- code 100-1 is missing while
    the developer exists -- so give up only after a few misses. Once the
    developer is known, bilanganProjek says how many projects to expect, which
    is what turns one developer code into a complete project list.

    Returns (developer_row, [project_rows]).
    """
    dev_row, first_code, first_payload = None, None, None
    for n in range(1, depth + 1):
        code = f"{dev}-{n}"
        payload = fetch(code, limiter)
        if payload:
            dev_row, first_code, first_payload = row_from(dev, code, payload), code, payload
            break
    if not dev_row:
        return {"kod_pemaju": dev, "found": "no"}, []
    if not with_projects:
        return dev_row, []

    want = dev_row.get("bilangan_projek")
    want = int(want) if str(want).strip().isdigit() else 1
    projects = [project_row(dev, first_code, first_payload, dev_row)]
    seen, misses, n = {first_code}, 0, 0
    # Codes are not always contiguous, so keep going a little past the count
    # rather than stopping at the first gap.
    while len(projects) < want and misses <= depth and n < want + depth + 2:
        n += 1
        code = f"{dev}-{n}"
        if code in seen:
            continue
        seen.add(code)
        payload = fetch(code, limiter)
        if payload:
            projects.append(project_row(dev, code, payload, dev_row))
            misses = 0
        else:
            misses += 1
    return dev_row, projects


def load_done(path, key):
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return {}
    with open(path, newline="", encoding="utf-8") as f:
        return {r[key]: r for r in csv.DictReader(f)}


def sort_key(code):
    """'31332-4' sorts after '31332-1' and after developer 9600."""
    bits = str(code).split("-")
    try:
        return (int(bits[0]), int(bits[1]) if len(bits) > 1 else 0)
    except ValueError:
        return (0, 0)


def save(path, rows, fields, key):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    ordered = sorted(rows.values(), key=lambda r: sort_key(r[key]))
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in ordered:
            w.writerow({k: r.get(k, "") for k in fields})
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end", type=int, default=33000)
    ap.add_argument("--rps", type=float, default=1.5,
                    help="starting requests per second across all threads. TEDUH answers "
                         "429 above roughly this, and the scan slows itself further if it "
                         "still gets refused")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--minutes", type=float, default=300, help="stop cleanly before the job limit")
    ap.add_argument("--depth", type=int, default=1,
                    help="project numbers to try before calling a code empty. 1 keeps the "
                         "sweep at one request per code; raise it with --redo-empty to "
                         "re-check the misses afterwards")
    ap.add_argument("--redo-empty", action="store_true",
                    help="re-probe codes previously recorded as empty, e.g. at a higher --depth")
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--projects-out", default=PROJ_OUT)
    ap.add_argument("--skip-projects", action="store_true",
                    help="index developers only, without listing their projects")
    ap.add_argument("--redo", action="store_true", help="re-probe codes already recorded")
    args = ap.parse_args()

    rows = load_done(args.out, "kod_pemaju")
    projects = load_done(args.projects_out, "kod_projek")
    want_projects = not args.skip_projects

    have_projects = set()
    for p in projects.values():
        have_projects.add(p["kod_pemaju"])

    def needs_work(d):
        if args.redo or d not in rows:
            return True
        if args.redo_empty and rows[d].get("found") == "no":
            return True
        # A developer indexed by an earlier developers-only run still needs its
        # project list, otherwise resuming would silently leave gaps.
        return want_projects and rows[d].get("found") == "yes" and d not in have_projects

    todo = [str(d) for d in range(args.start, args.end + 1) if needs_work(str(d))]
    print(f"{len(rows)} codes already recorded, {len(projects)} projects indexed; "
          f"{len(todo)} to probe ({args.start}-{args.end}) at {args.rps}/s"
          + ("" if want_projects else "  [developers only]"))
    if not todo:
        print("Nothing to do.")
        return

    limiter = Limiter(args.rps)
    deadline = time.monotonic() + args.minutes * 60
    lock = threading.Lock()
    counts = {"found": 0, "empty": 0, "error": 0, "projects": 0}
    stop = threading.Event()

    def flush():
        save(args.out, rows, FIELDS, "kod_pemaju")
        if want_projects:
            save(args.projects_out, projects, PROJ_FIELDS, "kod_projek")

    def work(dev):
        if stop.is_set():
            return None
        try:
            r, projs = probe(dev, limiter, args.depth, want_projects)
        except Exception as e:                      # keep the scan alive
            print(f"  {dev}: {e}", file=sys.stderr)
            with lock:
                counts["error"] += 1
            return None
        with lock:
            rows[dev] = r
            for p in projs:
                projects[p["kod_projek"]] = p
            counts["found" if r["found"] == "yes" else "empty"] += 1
            counts["projects"] += len(projs)
            n = counts["found"] + counts["empty"]
            if n % 250 == 0:
                flush()
                print(f"  {n}/{len(todo)} probed, {counts['found']} developers, "
                      f"{len(projects)} projects, {limiter.rate():.2f} req/s"
                      + (f", {limiter.penalties} backoffs" if limiter.penalties else ""),
                      flush=True)
            if time.monotonic() > deadline:
                stop.set()
        return None

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(work, todo))

    flush()
    last = max((int(k) for k in rows), default=args.start)
    print(f"\nfound {counts['found']}, empty {counts['empty']}, errors {counts['error']}")
    print(f"finished at {limiter.rate():.2f} req/s after {limiter.penalties} backoffs")
    if counts["error"]:
        print("Codes that errored were not recorded, so the next run retries them.")
    print(f"{len(rows)} codes recorded in total, highest {last}")
    if want_projects:
        print(f"{len(projects)} projects indexed in {os.path.basename(args.projects_out)}")
    if stop.is_set():
        remaining = [d for d in todo if d not in rows]
        nxt = min((int(d) for d in remaining), default=args.end + 1)
        print(f"\nTIME LIMIT REACHED — re-run from --start {nxt} to continue.")


if __name__ == "__main__":
    main()
