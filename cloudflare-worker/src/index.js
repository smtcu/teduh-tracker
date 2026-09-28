const TEDUH = "https://teduh.kpkt.gov.my/api";
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36";
const GH_API = "https://api.github.com";

const STATE = {
  "01": "Johor", "02": "Kedah", "03": "Kelantan", "04": "Melaka",
  "05": "Negeri Sembilan", "06": "Pahang", "07": "Pulau Pinang", "08": "Perak",
  "09": "Perlis", "10": "Selangor", "11": "Terengganu", "14": "Kuala Lumpur",
  "16": "Putrajaya",
};

export default {
  // Runs on the Cron Trigger defined in wrangler.toml.
  async scheduled(event, env, ctx) {
    ctx.waitUntil(dispatchWorkflow(env));
  },

  // The fetch handler serves the dashboard's "Suggest a project" form:
  //   GET  /api/search?q=<name or code>  -> TEDUH matches for the picker
  //   POST /api/suggest                  -> validate + open a GitHub PR
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const headers = corsHeaders(env);

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers });
    }

    try {
      if (url.pathname === "/api/search" && request.method === "GET") {
        return json(await search(url.searchParams.get("q") || ""), 200, headers);
      }
      if (url.pathname === "/api/suggest" && request.method === "POST") {
        const body = await request.json().catch(() => ({}));
        const { status, payload } = await suggest(body, env);
        return json(payload, status, headers);
      }
    } catch (e) {
      console.error(`${url.pathname} failed:`, e);
      return json({ error: "Something went wrong on the server. Try again in a minute." }, 502, headers);
    }

    return new Response(
      "TEDUH tracker worker. POST /api/suggest and GET /api/search serve the dashboard form; the cron trigger refreshes the data.",
      { status: 200, headers }
    );
  },
};

function corsHeaders(env) {
  return {
    "Access-Control-Allow-Origin": env.ALLOWED_ORIGIN || "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
  };
}

function json(obj, status, headers) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { ...headers, "Content-Type": "application/json; charset=utf-8" },
  });
}

async function teduh(path) {
  const res = await fetch(`${TEDUH}${path}`, {
    headers: { "User-Agent": UA, Accept: "application/json" },
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`TEDUH ${path} -> ${res.status}`);
  return res.json();
}

/* ---------- search ---------- */

async function search(q) {
  q = q.trim();
  if (q.length < 3) return { results: [], total: 0 };

  // A TEDUH code typed directly ("30555-1") skips the name search.
  if (/^\d{2,6}(-\d{1,3})?$/.test(q)) {
    const d = await teduh(`/projek-swasta/${encodeURIComponent(q)}`);
    if (!d || !d.id) return { results: [], total: 0 };
    return {
      results: [{
        code: d.id,
        name: d.nama || "",
        developer: d.pemaju?.nama || "",
        location: d.lokasi || "",
        units: d.unitSummary?.unit ?? null,
        licensed: d.projek?.permitMula || "",
      }],
      total: 1,
    };
  }

  // `q=` matches project names only (never developer names), page size fixed at 20.
  const d = await teduh(`/projek-swasta?q=${encodeURIComponent(q)}`);
  const rows = d?.projects?.data || [];
  return {
    results: rows.slice(0, 20).map(r => ({
      code: r.id,
      name: r.nama || "",
      developer: r.pemaju?.nama || "",
      location: STATE[r.kod_negeri_id] || "",
      units: null,
      licensed: r.latest_lesen?.tarikh_lesen_pertama || "",
    })),
    total: d?.projects?.total ?? rows.length,
  };
}

/* ---------- suggest -> GitHub PR ---------- */

async function suggest(body, env) {
  const fail = (status, error) => ({ status, payload: { error } });

  const code = (body.code || "").trim();
  const tracker = (body.tracker || "").trim();
  const remarks = (body.remarks || "").trim().slice(0, 300);
  if (!/^\d{2,6}(-\d{1,3})?$/.test(code)) return fail(400, "Pick a project from the search results first.");
  if (!tracker) return fail(400, "Pick which tracker the project belongs to.");

  // 1. The project must exist on TEDUH.
  const detail = await teduh(`/projek-swasta/${encodeURIComponent(code)}`);
  if (!detail || !detail.id) return fail(404, `TEDUH has no project with code ${code}.`);
  const name = detail.nama || code;
  const developer = detail.pemaju?.nama || "";
  const licensedUnits = detail.unitSummary?.unit ?? null;

  // 2. It must still have units for sale. A completed project publishes no
  //    unsold units at all, so avail === 0 also catches those.
  const unitsPayload = await teduh(`/unit-projek-swasta/${encodeURIComponent(code)}`);
  let published = 0, sold = 0;
  for (const g of unitsPayload?.unitGroups || []) {
    for (const u of g.units || []) {
      published += 1;
      if (u.status === "sold") sold += 1;
    }
  }
  const avail = published - sold;
  if (published > 0 && avail === 0) {
    return fail(409, `${name} shows 0 unsold units on TEDUH (fully sold or completed), and the tracker only follows projects still selling.`);
  }
  const totalUnits = licensedUnits || published;

  // 3. The chosen tracker must already exist (new trackers are a code-owner
  //    job), and the project must not already sit in THAT tracker -- the same
  //    code can legitimately appear in a site tracker and a developer tracker.
  const gh = ghClient(env);
  const file = await gh(`/repos/${env.GH_OWNER}/${env.GH_REPO}/contents/projects.csv?ref=${env.GH_REF}`);
  const csvText = base64ToUtf8(file.content.replace(/\n/g, ""));
  const rows = parseCsv(csvText);
  const header = rows[0];
  const col = n => header.indexOf(n);
  const codeCol = col("code"), trackerCol = col("tracker"), noCol = col("no"), labelCol = col("tracker_label");
  let trackerLabel = "", trackerKnown = false;
  for (const r of rows.slice(1)) {
    if (r[trackerCol] !== tracker) continue;
    trackerKnown = true;
    if (labelCol >= 0 && !trackerLabel) trackerLabel = r[labelCol] || "";
    const codes = (r[codeCol] || "").split(",").map(s => s.trim());
    if (codes.includes(code)) {
      return fail(409, `${name} (${code}) is already on that tracker.`);
    }
  }
  if (!trackerKnown) {
    return fail(400, `"${tracker}" is not an existing tracker. Pick one from the list.`);
  }

  // 4. Append the row: next running number within the chosen tracker,
  //    launched/first_new left blank (all build scripts tolerate that).
  let nextNo = 1;
  for (const r of rows.slice(1)) {
    if (r[trackerCol] === tracker) {
      const n = parseInt(r[noCol], 10);
      if (!isNaN(n) && n >= nextNo) nextNo = n + 1;
    }
  }
  const newRow = header.map(h => ({
    tracker, tracker_label: trackerLabel, no: String(nextNo), project: name, code, developer,
    apdl: detail.projek?.permitNo || "",
    total_units: totalUnits ? String(totalUnits) : "",
    remarks,
  }[h] ?? ""));
  const newCsv = csvText.replace(/\s*$/, "") + "\n" + toCsvLine(newRow) + "\n";

  // 5. Branch + commit + PR. Merging the PR is the approval step.
  const branch = `suggest/${code}-${Date.now()}`;
  const main = await gh(`/repos/${env.GH_OWNER}/${env.GH_REPO}/git/ref/heads/${env.GH_REF}`);
  await gh(`/repos/${env.GH_OWNER}/${env.GH_REPO}/git/refs`, "POST", {
    ref: `refs/heads/${branch}`,
    sha: main.object.sha,
  });
  await gh(`/repos/${env.GH_OWNER}/${env.GH_REPO}/contents/projects.csv`, "PUT", {
    message: `Suggest ${name} (${code}) for ${tracker} tracker\n\nSubmitted via the dashboard form.`,
    content: utf8ToBase64(newCsv),
    sha: file.sha,
    branch,
  });
  const pct = published ? ((sold / published) * 100).toFixed(1) : "?";
  const pr = await gh(`/repos/${env.GH_OWNER}/${env.GH_REPO}/pulls`, "POST", {
    title: `Add ${name} to ${tracker} tracker`,
    head: branch,
    base: env.GH_REF,
    body: [
      `**${name}** (\`${code}\`) — suggested via the dashboard form.`,
      "",
      `| | |`,
      `|---|---|`,
      `| Developer (TEDUH) | ${developer || "?"} |`,
      `| Location | ${detail.lokasi || "?"} |`,
      `| Licensed units | ${licensedUnits ?? "?"} |`,
      `| Published on unit API | ${published} (${sold} sold, ${avail} unsold, ${pct}% sold) |`,
      `| APDL | ${detail.projek?.permitNo || "?"} |`,
      `| Licence period | ${detail.projek?.permitMula || "?"} to ${detail.projek?.permitTamat || "?"} |`,
      remarks ? `| Submitter remarks | ${remarks} |` : null,
      "",
      "**Merging this PR adds the project.** Check the developer/SPV name and the marketing name before merging; `launched` is left blank to fill in later. Close the PR to reject.",
    ].filter(l => l !== null).join("\n"),
  });

  return {
    status: 200,
    payload: {
      ok: true,
      message: `${name} sent for approval. It appears on the dashboard after it is approved and the next refresh runs.`,
      pr: pr.html_url,
    },
  };
}

function ghClient(env) {
  return async (path, method = "GET", body) => {
    const res = await fetch(`${GH_API}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        Accept: "application/vnd.github+json",
        "User-Agent": "teduh-cron-worker",
        "X-GitHub-Api-Version": "2022-11-28",
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`GitHub ${method} ${path} -> ${res.status} ${text.slice(0, 300)}`);
    }
    return res.json();
  };
}

/* ---------- CSV helpers (RFC 4180 quoting, as Python's csv module writes it) ---------- */

function parseCsv(text) {
  const rows = [];
  let row = [], field = "", inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') { field += '"'; i++; }
        else inQuotes = false;
      } else field += c;
    } else if (c === '"') {
      inQuotes = true;
    } else if (c === ",") {
      row.push(field); field = "";
    } else if (c === "\n" || c === "\r") {
      if (c === "\r" && text[i + 1] === "\n") i++;
      row.push(field); field = "";
      if (row.length > 1 || row[0] !== "") rows.push(row);
      row = [];
    } else field += c;
  }
  if (field !== "" || row.length) { row.push(field); rows.push(row); }
  return rows;
}

function toCsvLine(fields) {
  return fields.map(f => /[",\n\r]/.test(f) ? '"' + f.replace(/"/g, '""') + '"' : f).join(",");
}

function base64ToUtf8(b64) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new TextDecoder("utf-8").decode(bytes);
}

function utf8ToBase64(str) {
  const bytes = new TextEncoder().encode(str);
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin);
}

/* ---------- daily refresh dispatch (unchanged) ---------- */

async function dispatchWorkflow(env) {
  const url = `${GH_API}/repos/${env.GH_OWNER}/${env.GH_REPO}/actions/workflows/${env.GH_WORKFLOW_FILE}/dispatches`;

  const res = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "teduh-cron-worker",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: JSON.stringify({ ref: env.GH_REF }),
  });

  if (!res.ok) {
    const text = await res.text();
    console.error(`GitHub dispatch failed: ${res.status} ${text}`);
    throw new Error(`GitHub dispatch failed: ${res.status}`);
  }

  console.log("Workflow dispatch sent successfully.");
}
