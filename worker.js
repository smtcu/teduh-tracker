/**
 * Password gate for the TEDUH competitor tracker.
 *
 * Every request passes through here first -- the dashboard, the spreadsheets and
 * the CSV downloads -- so nothing is reachable without signing in.
 *
 * The username and password are read from Cloudflare's dashboard
 * (Settings -> Variables and Secrets) and are never stored in this repository.
 */

const REALM = "TEDUH Tracker";

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

function askForPassword() {
  return new Response("Sign in to view the TEDUH tracker.", {
    status: 401,
    headers: {
      "WWW-Authenticate": `Basic realm="${REALM}", charset="UTF-8"`,
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}

export default {
  async fetch(request, env) {
    const user = env.SITE_USER;
    const pass = env.SITE_PASSWORD;

    // Fail closed: if no credentials are configured, let nobody in rather than everybody.
    if (!user || !pass) {
      return new Response(
        "This site is not configured yet. Add SITE_USER and SITE_PASSWORD in the Cloudflare dashboard.",
        { status: 503, headers: { "Cache-Control": "no-store" } }
      );
    }

    const header = request.headers.get("Authorization") || "";
    if (!header.startsWith("Basic ")) return askForPassword();

    let decoded;
    try {
      decoded = atob(header.slice(6));
    } catch {
      return askForPassword();
    }

    const split = decoded.indexOf(":");
    if (split < 0) return askForPassword();

    // Both checks always run, so a wrong username and a wrong password cost the same time.
    const userOk = safeEqual(decoded.slice(0, split), user);
    const passOk = safeEqual(decoded.slice(split + 1), pass);
    if (!userOk || !passOk) return askForPassword();

    const response = await env.ASSETS.fetch(request);
    const out = new Response(response.body, response);
    out.headers.set("Cache-Control", "no-store");
    out.headers.set("X-Robots-Tag", "noindex, nofollow");
    return out;
  },
};
