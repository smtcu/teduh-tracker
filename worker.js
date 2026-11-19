/**
 * Sign-in gate for the TEDUH competitor tracker.
 *
 * Every request passes through here first -- the dashboard, the spreadsheets and
 * the CSV downloads -- so nothing is reachable without signing in, apart from
 * the logo and home-screen icons listed in PUBLIC_PATHS below.
 *
 * Since 19 Nov 2026 this is a sign-in page with a Log out button, instead of
 * the browser's own password pop-up (Basic Auth), which a website cannot sign
 * out of. Signing in sets a cookie that lasts SESSION_SECONDS (one hour, her
 * call) from the moment of signing in; after that the sign-in page comes back.
 *
 *   /login   the sign-in page (GET) and the form it posts to (POST)
 *   /logout  deletes the cookie on this device and goes back to /login
 *
 * One shared username and password, read from Cloudflare's dashboard
 * (Settings -> Variables and Secrets, SITE_USER and SITE_PASSWORD) and never
 * stored in this repository. The cookie is signed with a key made from those
 * two values, so changing the password in Cloudflare signs every device out.
 */

const SESSION_SECONDS = 60 * 60; // one hour
const COOKIE = "teduh_session";

/**
 * The only files served without signing in: the logo, home-screen icons and the
 * manifest that names them. Phones fetch these on their own, without the login,
 * when you add the site to a home screen; the sign-in page shows the logo too.
 * They are pictures and nothing else -- every dashboard page, spreadsheet, PDF
 * and CSV stays behind the sign-in. Exact paths only, so nothing else can slip
 * through.
 */
const PUBLIC_PATHS = new Set([
  "/manifest.webmanifest",
  "/brand/apple-touch-icon.png",
  "/brand/icon-192.png",
  "/brand/icon-512.png",
  "/brand/favicon.png",
  "/brand/logo.png",
  "/brand/logo-dark.png",
]);

/** Compare two strings without leaking their contents through timing. */
function safeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string") return false;
  const enc = new TextEncoder();
  const x = enc.encode(a);
  const y = enc.encode(b);
  if (x.length !== y.length) return false;
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x[i] ^ y[i];
  return diff === 0;
}

/** Stray spaces and newlines are easy to paste in by accident; ignore them. */
function tidy(value) {
  return typeof value === "string" ? value.trim() : "";
}

function toHex(buffer) {
  return [...new Uint8Array(buffer)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** HMAC-SHA256 of `message`, keyed on the site's username and password. */
async function sign(message, user, pass) {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    enc.encode(`teduh-session\n${user}\n${pass}`),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  return toHex(await crypto.subtle.sign("HMAC", key, enc.encode(message)));
}

/** The cookie is "<expiry in unix seconds>.<signature of that expiry>". */
async function makeSession(user, pass) {
  const expires = Math.floor(Date.now() / 1000) + SESSION_SECONDS;
  return `${expires}.${await sign(String(expires), user, pass)}`;
}

async function sessionIsValid(value, user, pass) {
  if (!value) return false;
  const dot = value.indexOf(".");
  if (dot < 1) return false;
  const expires = value.slice(0, dot);
  if (!/^\d+$/.test(expires)) return false;
  if (Number(expires) <= Math.floor(Date.now() / 1000)) return false;
  return safeEqual(value.slice(dot + 1), await sign(expires, user, pass));
}

function readCookie(request, name) {
  const header = request.headers.get("Cookie") || "";
  for (const part of header.split(";")) {
    const eq = part.indexOf("=");
    if (eq > 0 && part.slice(0, eq).trim() === name) return part.slice(eq + 1).trim();
  }
  return "";
}

/** Only ever send someone back to a page on this site, never to another one. */
function safeNext(value) {
  if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//")) return "/";
  if (value.startsWith("/login") || value.startsWith("/logout") || value.includes("\\")) return "/";
  return value;
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function redirect(location, extraHeaders = {}) {
  return new Response(null, {
    status: 303,
    headers: { Location: location, "Cache-Control": "no-store", ...extraHeaders },
  });
}

const NO_INDEX = { "X-Robots-Tag": "noindex, nofollow", "Cache-Control": "no-store" };

function loginPage({ next = "/", message = "", kind = "info", status = 200 } = {}) {
  const note = message ? `<p class="msg ${kind}" role="status">${escapeHtml(message)}</p>` : "";
  const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>TEDUH Tracker</title>
<link rel="icon" href="/brand/favicon.png">
<link rel="apple-touch-icon" href="/brand/apple-touch-icon.png">
<style>
:root{--plane:#f4f4f2;--surface:#fcfcfb;--ink:#0b0b0b;--muted:#6f6e69;--border:rgba(11,11,11,.16);
  --field:#fff;--blue:#2a78d6;--infobg:#eaf2fd;--infoink:#1d5aa6;--errbg:#fdecea;--errink:#a3271b}
@media (prefers-color-scheme: dark){:root{--plane:#0d0d0d;--surface:#1a1a19;--ink:#fff;--muted:#9d9c94;
  --border:rgba(255,255,255,.18);--field:#232322;--blue:#3987e5;--infobg:#16304f;--infoink:#cfe2fb;
  --errbg:#4a1d18;--errink:#ffd3cc}}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:16px;
  background:var(--plane);color:var(--ink);font:16px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif}
form{width:100%;max-width:360px;background:var(--surface);border:1px solid var(--border);border-radius:14px;
  padding:28px 24px;box-shadow:0 1px 2px rgba(11,11,11,.05),0 6px 20px rgba(11,11,11,.06)}
.logo{display:block;width:190px;height:auto;margin:0 auto 20px}
.logo.dark{display:none}
@media (prefers-color-scheme: dark){.logo.light{display:none}.logo.dark{display:block}}
label{display:block;font-size:13px;font-weight:600;color:var(--muted);margin:14px 0 5px}
input{width:100%;font:inherit;font-size:16px;padding:11px 12px;border:1px solid var(--border);border-radius:9px;
  background:var(--field);color:var(--ink)}
input:focus{outline:2px solid var(--blue);outline-offset:1px}
button{width:100%;margin-top:20px;padding:12px;font:inherit;font-size:16px;font-weight:650;border:0;border-radius:9px;
  background:var(--blue);color:#fff;cursor:pointer}
.msg{margin:0 0 6px;padding:10px 12px;border-radius:9px;font-size:14px;text-align:center}
.msg.info{background:var(--infobg);color:var(--infoink)}
.msg.error{background:var(--errbg);color:var(--errink)}
.foot{margin:16px 0 0;font-size:12.5px;color:var(--muted);text-align:center}
</style>
</head>
<body>
<form method="post" action="/login">
  <img class="logo light" src="/brand/logo.png" alt="CPI Land | TEDUH Tracker" width="214" height="64">
  <img class="logo dark" src="/brand/logo-dark.png" alt="CPI Land | TEDUH Tracker" width="214" height="64">
  ${note}
  <input type="hidden" name="next" value="${escapeHtml(next)}">
  <label for="u">Username</label>
  <input id="u" name="username" autocomplete="username" autocapitalize="none" spellcheck="false" required>
  <label for="p">Password</label>
  <input id="p" name="password" type="password" autocomplete="current-password" required>
  <button type="submit">Sign in</button>
  <p class="foot">You stay signed in on this device for one hour.</p>
</form>
</body>
</html>`;
  return new Response(html, {
    status,
    headers: { "Content-Type": "text/html; charset=utf-8", ...NO_INDEX },
  });
}

function sessionCookie(value, maxAge) {
  return `${COOKIE}=${value}; Max-Age=${maxAge}; Path=/; HttpOnly; Secure; SameSite=Lax`;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;
    const isRead = request.method === "GET" || request.method === "HEAD";

    if (isRead && PUBLIC_PATHS.has(path)) {
      const response = await env.ASSETS.fetch(request);
      const out = new Response(response.body, response);
      out.headers.set("Cache-Control", "public, max-age=86400");
      out.headers.set("X-Robots-Tag", "noindex, nofollow");
      return out;
    }

    const user = tidy(env.SITE_USER);
    const pass = tidy(env.SITE_PASSWORD);

    // Fail closed: if no credentials are configured, let nobody in rather than everybody.
    if (!user || !pass) {
      return new Response(
        "This site is not configured yet. Add SITE_USER and SITE_PASSWORD in the Cloudflare dashboard.",
        { status: 503, headers: { "Cache-Control": "no-store" } }
      );
    }

    // Log out: delete the cookie on this device. Nothing else is touched.
    if (path === "/logout") {
      return redirect("/login?out=1", { "Set-Cookie": sessionCookie("", 0) });
    }

    if (path === "/login") {
      if (request.method === "POST") {
        let form;
        try {
          form = await request.formData();
        } catch {
          return loginPage({ message: "Something went wrong. Please try again.", kind: "error", status: 400 });
        }
        const next = safeNext(form.get("next"));
        // Both checks always run, so a wrong username and a wrong password cost the same time.
        const userOk = safeEqual(tidy(form.get("username")), user);
        const passOk = safeEqual(tidy(form.get("password")), pass);
        if (!userOk || !passOk) {
          // A short pause makes guessing the password slow.
          await new Promise((resolve) => setTimeout(resolve, 1000));
          return loginPage({ next, message: "Wrong username or password.", kind: "error", status: 401 });
        }
        const session = await makeSession(user, pass);
        return redirect(next, { "Set-Cookie": sessionCookie(session, SESSION_SECONDS) });
      }
      // Already signed in? Go straight to the site.
      if (await sessionIsValid(readCookie(request, COOKIE), user, pass)) {
        return redirect(safeNext(url.searchParams.get("next")));
      }
      if (url.searchParams.get("out") === "1") {
        return loginPage({ message: "You have been logged out." });
      }
      if (url.searchParams.get("expired") === "1") {
        return loginPage({ next: safeNext(url.searchParams.get("next")), message: "Please sign in again." });
      }
      return loginPage({ next: safeNext(url.searchParams.get("next")) });
    }

    const cookie = readCookie(request, COOKIE);
    if (!(await sessionIsValid(cookie, user, pass))) {
      if (!isRead) return new Response("Sign in first.", { status: 401, headers: NO_INDEX });
      const back = encodeURIComponent(path + url.search);
      return redirect(`/login?next=${back}${cookie ? "&expired=1" : ""}`);
    }

    const response = await env.ASSETS.fetch(request);
    const out = new Response(response.body, response);
    out.headers.set("Cache-Control", "no-store");
    out.headers.set("X-Robots-Tag", "noindex, nofollow");
    return out;
  },
};
