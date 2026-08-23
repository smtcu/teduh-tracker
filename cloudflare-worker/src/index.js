export default {
  // Runs on the Cron Trigger defined in wrangler.toml.
  async scheduled(event, env, ctx) {
    ctx.waitUntil(dispatchWorkflow(env));
  },

  // Cron Triggers can also be fired manually while testing, via
  // `npx wrangler dev --test-scheduled` + a request to /__scheduled.
  // A normal visit to the Worker's URL does nothing on purpose.
  async fetch(request, env, ctx) {
    return new Response(
      "This Worker only responds to its Cron Trigger. Nothing to see here.",
      { status: 200 }
    );
  },
};

async function dispatchWorkflow(env) {
  const url = `https://api.github.com/repos/${env.GH_OWNER}/${env.GH_REPO}/actions/workflows/${env.GH_WORKFLOW_FILE}/dispatches`;

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
