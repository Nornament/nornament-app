// deploy-site — publishes the app to Cloudflare Pages without anybody
// downloading a zip and dragging it into a dashboard.
//
// Why here and not from a laptop or a build sandbox: the Cloudflare token has
// to live somewhere permanent, and Supabase's secret store is the only
// permanent place this system already has. The token never reaches a browser,
// never appears in a chat transcript, and is scoped to Pages alone — it cannot
// touch R2, DNS, the database, or anything else on the account.
//
// The upload sequence below is Cloudflare's Direct Upload flow. It is what
// wrangler does internally and is NOT in the public API documentation, so it
// is the part of this file most likely to break on a Cloudflare change. If it
// ever does, the dashboard drag-and-drop still works and nothing is lost.
//
// Secrets required:
//   CF_API_TOKEN     — Account → Cloudflare Pages → Edit
//   CF_ACCOUNT_ID    — the hex string in your R2 endpoint
//   CF_PAGES_PROJECT — defaults to nornament-stock
import { blake3 } from "npm:@noble/hashes@1.4.0/blake3";
import { bytesToHex } from "npm:@noble/hashes@1.4.0/utils";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const ANON         = Deno.env.get("SUPABASE_ANON_KEY") ?? "";
const CF_TOKEN     = Deno.env.get("CF_API_TOKEN") ?? "";
const CF_ACCOUNT   = Deno.env.get("CF_ACCOUNT_ID") ?? "";
const CF_PROJECT   = Deno.env.get("CF_PAGES_PROJECT") ?? "nornament-stock";

const API = "https://api.cloudflare.com/client/v4";

const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, content-type, apikey",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status, headers: { ...cors, "Content-Type": "application/json" },
  });

const MIME: Record<string, string> = {
  html: "text/html", js: "application/javascript", css: "text/css",
  json: "application/json", svg: "image/svg+xml", png: "image/png",
  jpg: "image/jpeg", jpeg: "image/jpeg", webp: "image/webp",
  ico: "image/x-icon", txt: "text/plain", xml: "application/xml",
  woff2: "font/woff2", map: "application/json",
};

/** Cloudflare keys an asset by blake3(base64 body + bare extension), 32 hex chars. */
function assetHash(base64Body: string, ext: string) {
  return bytesToHex(blake3(new TextEncoder().encode(base64Body + ext))).slice(0, 32);
}

async function callerIsAdmin(auth: string) {
  const r = await fetch(`${SUPABASE_URL}/rest/v1/me?select=role_code`, {
    headers: { Authorization: auth, apikey: ANON, "Accept-Profile": "api" },
  });
  if (!r.ok) return false;
  const rows = await r.json();
  return Array.isArray(rows) && rows[0]?.role_code === "ADMIN";
}

const cf = (path: string, init: RequestInit = {}) =>
  fetch(`${API}${path}`, {
    ...init,
    headers: { Authorization: `Bearer ${CF_TOKEN}`, ...(init.headers ?? {}) },
  });

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  if (req.method !== "POST") return json({ error: "POST only" }, 405);

  const missing = Object.entries({ CF_API_TOKEN: CF_TOKEN, CF_ACCOUNT_ID: CF_ACCOUNT })
    .filter(([, v]) => !v).map(([k]) => k);
  if (missing.length)
    return json({ error: `Not configured yet. Missing secret(s): ${missing.join(", ")}. ` +
      `Add them in Supabase → Edge Functions → Secrets.` }, 503);

  const auth = req.headers.get("Authorization") ?? "";
  if (!auth.startsWith("Bearer ")) return json({ error: "Sign in first." }, 401);
  if (!(await callerIsAdmin(auth)))
    return json({ error: "Only an admin can publish the site." }, 403);

  let body: any;
  try { body = await req.json(); } catch { return json({ error: "Expected JSON." }, 400); }
  const action = String(body?.action ?? "deploy");

  try {
    // ── what is live right now ────────────────────────────────────────────
    if (action === "status") {
      const r = await cf(`/accounts/${CF_ACCOUNT}/pages/projects/${CF_PROJECT}`);
      const d = await r.json();
      if (!r.ok) return json({ error: d?.errors?.[0]?.message ?? `Cloudflare said ${r.status}.` }, 400);
      const p = d.result;
      return json({ ok: true, project: p.name, subdomain: p.subdomain,
        domains: p.domains,
        latest: p.latest_deployment ? {
          id: p.latest_deployment.id,
          created_on: p.latest_deployment.created_on,
          url: p.latest_deployment.url,
          status: p.latest_deployment.latest_stage?.status,
        } : null });
    }

    if (action !== "deploy") return json({ error: `Unknown action "${action}".` }, 400);

    // files: { "index.html": "<base64>", ... }  — base64 so binary works too
    const files: Record<string, string> = body.files ?? {};
    const names = Object.keys(files);
    if (!names.length) return json({ error: "files{} is required." }, 400);
    if (!names.includes("index.html"))
      return json({ error: "Refusing to deploy without an index.html — that would take the site down." }, 400);

    // _headers and _redirects are configuration, not assets. Cloudflare wants
    // them as form fields on the deployment, not in the manifest; sent as
    // assets they would be served as downloadable files and silently ignored.
    const CONFIG = new Set(["_headers", "_redirects", "_routes.json", "_worker.js"]);

    const assets: { name: string; b64: string; hash: string; ct: string }[] = [];
    for (const name of names) {
      if (CONFIG.has(name)) continue;
      const b64 = files[name];
      const ext = name.includes(".") ? name.split(".").pop()!.toLowerCase() : "";
      assets.push({ name, b64, hash: assetHash(b64, ext), ct: MIME[ext] ?? "application/octet-stream" });
    }

    // 1. a short-lived token that is only good for uploading to this project
    const tr = await cf(`/accounts/${CF_ACCOUNT}/pages/projects/${CF_PROJECT}/upload-token`);
    const td = await tr.json();
    if (!tr.ok || !td?.result?.jwt)
      return json({ error: td?.errors?.[0]?.message ??
        `Could not get an upload token (${tr.status}). Check the project name "${CF_PROJECT}" and that the token has Pages → Edit.` }, 400);
    const jwt = td.result.jwt as string;

    const upl = (p: string, payload: unknown) =>
      fetch(`${API}${p}`, { method: "POST",
        headers: { Authorization: `Bearer ${jwt}`, "Content-Type": "application/json" },
        body: JSON.stringify(payload) });

    // 2. ask which of these files Cloudflare does not already hold. A 600 KB
    //    page that has not changed is then not uploaded at all.
    const cm = await upl("/pages/assets/check-missing", { hashes: assets.map(a => a.hash) });
    const cmd = await cm.json();
    if (!cm.ok) return json({ error: cmd?.errors?.[0]?.message ?? `check-missing failed (${cm.status}).` }, 400);
    const need = new Set<string>(cmd.result ?? assets.map(a => a.hash));

    // 3. upload only those
    const toSend = assets.filter(a => need.has(a.hash));
    for (let i = 0; i < toSend.length; i += 5) {
      const batch = toSend.slice(i, i + 5).map(a => ({
        key: a.hash, value: a.b64, base64: true,
        metadata: { contentType: a.ct },
      }));
      const up = await upl("/pages/assets/upload", batch);
      if (!up.ok) {
        const e = await up.text();
        return json({ error: `Upload failed (${up.status}): ${e.slice(0, 300)}` }, 400);
      }
    }

    // 4. mark every hash as in use, so a file that was already there is not
    //    garbage-collected out from under this deployment
    await upl("/pages/assets/upsert-hashes", { hashes: assets.map(a => a.hash) });

    // 5. create the deployment from the manifest
    const manifest: Record<string, string> = {};
    for (const a of assets) manifest["/" + a.name.replace(/^\/+/, "")] = a.hash;

    const form = new FormData();
    form.append("manifest", JSON.stringify(manifest));
    for (const c of CONFIG) {
      if (files[c] != null) {
        const text = new TextDecoder().decode(
          Uint8Array.from(atob(files[c]), ch => ch.charCodeAt(0)));
        form.append(c, text);
      }
    }

    const dep = await cf(`/accounts/${CF_ACCOUNT}/pages/projects/${CF_PROJECT}/deployments`,
                         { method: "POST", body: form });
    const dd = await dep.json();
    if (!dep.ok)
      return json({ error: dd?.errors?.[0]?.message ?? `Deployment failed (${dep.status}).`,
                    detail: JSON.stringify(dd?.errors ?? {}).slice(0, 400) }, 400);

    return json({ ok: true,
      deployment_id: dd.result?.id,
      url: dd.result?.url,
      aliases: dd.result?.aliases ?? [],
      uploaded: toSend.length,
      unchanged: assets.length - toSend.length,
      files: assets.map(a => a.name),
      note: "Live within about half a minute. Cloudflare keeps every previous " +
            "deployment — roll back from Pages → Deployments if this one is wrong." });
  } catch (e) {
    return json({ error: String((e as Error).message ?? e) }, 400);
  }
});
