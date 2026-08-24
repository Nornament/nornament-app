// ─────────────────────────────────────────────────────────────────────────────
// media-url — hands the browser a short-lived link to Cloudflare R2.
//
// Why this exists: uploading straight to R2 needs a signing key, and a key
// inside an HTML file on a showroom laptop is a published key. So the key
// lives here, in Supabase's secret store, and never leaves the server.
//
// Permission is not decided here either. Every request is passed through to
// the database using the caller's own token, so the same rules that govern
// the rest of the app govern uploads: a Sales login cannot reserve media
// because api.reserve_media refuses it, not because this file says so.
//
// Secrets required (Project Settings → Edge Functions → Secrets):
//   R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET
// ─────────────────────────────────────────────────────────────────────────────
import { AwsClient } from "npm:aws4fetch@1.0.20";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const ACCOUNT_ID   = Deno.env.get("R2_ACCOUNT_ID") ?? "";
const ACCESS_KEY   = Deno.env.get("R2_ACCESS_KEY_ID") ?? "";
const SECRET_KEY   = Deno.env.get("R2_SECRET_ACCESS_KEY") ?? "";
const BUCKET       = Deno.env.get("R2_BUCKET") ?? "";

const UPLOAD_TTL = 60 * 30;   // half an hour: a 200 MB TIFF on shop wifi is slow
const READ_TTL   = 60 * 60;   // an hour is plenty for looking at a catalogue

const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, content-type, apikey",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { ...cors, "Content-Type": "application/json" },
  });

function missingSecrets(): string[] {
  return Object.entries({ R2_ACCOUNT_ID: ACCOUNT_ID, R2_ACCESS_KEY_ID: ACCESS_KEY,
                          R2_SECRET_ACCESS_KEY: SECRET_KEY, R2_BUCKET: BUCKET })
    .filter(([, v]) => !v).map(([k]) => k);
}

/** Ask the database, as the caller, not as ourselves. */
async function rpc(auth: string, fn: string, payload: unknown) {
  const r = await fetch(`${SUPABASE_URL}/rest/v1/rpc/${fn}`, {
    method: "POST",
    headers: {
      Authorization: auth,
      apikey: Deno.env.get("SUPABASE_ANON_KEY") ?? "",
      "Content-Type": "application/json",
      "Content-Profile": "api",
      "Accept-Profile": "api",
    },
    body: JSON.stringify({ p: payload }),
  });
  const text = await r.text();
  let body: any; try { body = text ? JSON.parse(text) : null; } catch { body = text; }
  if (!r.ok) throw new Error(body?.message ?? `database refused (${r.status})`);
  return body;
}

/** Is this storage key one the caller is allowed to see? api.media decides.
 *  Returns the row, not a boolean: the mime type is needed to decide whether
 *  a browser will draw the file or silently download it. */
async function mediaRow(auth: string, key: string): Promise<any | null> {
  const url = `${SUPABASE_URL}/rest/v1/media?storage_key=eq.${encodeURIComponent(key)}` +
              `&select=media_ref,mime_type,file_name&limit=1`;
  const r = await fetch(url, {
    headers: {
      Authorization: auth,
      apikey: Deno.env.get("SUPABASE_ANON_KEY") ?? "",
      "Accept-Profile": "api",
    },
  });
  if (!r.ok) return null;
  const rows = await r.json();
  return Array.isArray(rows) && rows.length ? rows[0] : null;
}
const mayRead = async (auth: string, key: string) => !!(await mediaRow(auth, key));

/* R2 serves whatever content type was set when the object was PUT, and a
   browser that gets application/octet-stream downloads instead of showing.
   Overriding both headers on the signed link makes "view" mean view. */
const EXT_MIME: Record<string, string> = {
  jpg:"image/jpeg", jpeg:"image/jpeg", png:"image/png", webp:"image/webp",
  gif:"image/gif", avif:"image/avif", svg:"image/svg+xml",
  mp4:"video/mp4", webm:"video/webm", mov:"video/quicktime", m4v:"video/mp4",
  pdf:"application/pdf",
};
function inlineType(key: string, mime?: string | null) {
  const ext = (key.split(".").pop() ?? "").toLowerCase();
  return EXT_MIME[ext] ?? (mime && mime !== "application/octet-stream" ? mime : null);
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  if (req.method !== "POST") return json({ error: "POST only" }, 405);

  const gaps = missingSecrets();
  if (gaps.length) {
    // Report which R2-ish names ARE visible (names only, never values), so a
    // secret saved under a slightly different name is obvious instead of
    // looking identical to one that was never saved.
    const seen: string[] = [];
    for (const n of ["R2_ACCOUNT_ID","R2_ACCESS_KEY_ID","R2_SECRET_ACCESS_KEY","R2_BUCKET",
                     "R2_ACCOUNTID","R2_ACCESS_KEY","R2_SECRET_KEY","R2_SECRET",
                     "R2_BUCKET_NAME","CLOUDFLARE_ACCOUNT_ID","R2_TOKEN","R2_ENDPOINT"]) {
      if (Deno.env.get(n)) seen.push(n);
    }
    return json({ error:
      `Cloudflare R2 is not configured yet. Missing secret${gaps.length > 1 ? "s" : ""}: ` +
      gaps.join(", ") + ". Add them in Supabase → Project Settings → Edge Functions → Secrets.",
      secrets_this_function_can_see: seen }, 503);
  }

  const auth = req.headers.get("Authorization") ?? "";
  if (!auth.startsWith("Bearer ")) return json({ error: "Sign in first." }, 401);

  let body: any;
  try { body = await req.json(); } catch { return json({ error: "Expected JSON." }, 400); }
  const action = String(body?.action ?? "upload");

  const r2 = new AwsClient({
    accessKeyId: ACCESS_KEY,
    secretAccessKey: SECRET_KEY,
    service: "s3",
    region: "auto",
  });
  const base = `https://${ACCOUNT_ID}.r2.cloudflarestorage.com/${BUCKET}`;

  try {
    // ── ask the database for a reference and a key, then sign a PUT to it ──
    if (action === "upload") {
      const reserved = await rpc(auth, "reserve_media", {
        jewel_code: body.jewel_code ?? null,
        style_code: body.style_code ?? null,
        kind:       body.kind ?? "PHOTO",
        view_angle: body.view_angle ?? null,
        file_name:  body.file_name ?? null,
        mime_type:  body.mime_type ?? null,
        bytes:      body.bytes ?? null,
        caption:    body.caption ?? null,
        derivative_of:   body.derivative_of ?? null,
        derivative_kind: body.derivative_kind ?? null,
      });
      const key = reserved.storage_key as string;
      const signed = await r2.sign(
        new Request(`${base}/${encodeURI(key)}?X-Amz-Expires=${UPLOAD_TTL}`, { method: "PUT" }),
        { aws: { signQuery: true } },
      );
      return json({ ...reserved, upload_url: signed.url, expires_in: UPLOAD_TTL });
    }

    // ── a link to look at a file that is already there ──
    // ── a link that saves the file rather than opening it ──
    // Works the same on a phone and a laptop: R2 returns the object with a
    // Content-Disposition of "attachment", so the browser saves it under the
    // original name instead of trying to display a 200 MB TIFF.
    if (action === "download") {
      const key = String(body.storage_key ?? "");
      if (!key) return json({ error: "storage_key is required." }, 400);
      if (!(await mayRead(auth, key)))
        return json({ error: "That file is not yours to see." }, 403);
      const name = String(body.file_name ?? key.split("/").pop() ?? "download")
        .replace(/[^\w.\- ]+/g, "_");
      const u = new URL(`${base}/${encodeURI(key)}`);
      u.searchParams.set("X-Amz-Expires", String(READ_TTL));
      u.searchParams.set("response-content-disposition",
                         `attachment; filename="${name}"`);
      const signed = await r2.sign(new Request(u, { method: "GET" }),
                                   { aws: { signQuery: true } });
      return json({ storage_key: key, url: signed.url, file_name: name,
                    expires_in: READ_TTL });
    }

    if (action === "get") {
      const key = String(body.storage_key ?? "");
      if (!key) return json({ error: "storage_key is required." }, 400);
      const row = await mediaRow(auth, key);
      if (!row) return json({ error: "That file is not yours to see." }, 403);
      const u = new URL(`${base}/${encodeURI(key)}`);
      u.searchParams.set("X-Amz-Expires", String(READ_TTL));
      const ct = inlineType(key, row.mime_type);
      if (ct) {
        u.searchParams.set("response-content-type", ct);
        u.searchParams.set("response-content-disposition", "inline");
      }
      const signed = await r2.sign(new Request(u, { method: "GET" }),
                                   { aws: { signQuery: true } });
      return json({ storage_key: key, url: signed.url, content_type: ct,
                    expires_in: READ_TTL });
    }

    // ── several at once, so a grid of thumbnails is one round trip ──
    if (action === "get_many") {
      const keys: string[] = Array.isArray(body.storage_keys) ? body.storage_keys.slice(0, 400) : [];
      const out: Record<string, string> = {};
      for (const key of keys) {
        if (!key) continue;
        const row = await mediaRow(auth, key);
        if (!row) continue;
        const u = new URL(`${base}/${encodeURI(key)}`);
        u.searchParams.set("X-Amz-Expires", String(READ_TTL));
        const ct = inlineType(key, row.mime_type);
        if (ct) {
          u.searchParams.set("response-content-type", ct);
          u.searchParams.set("response-content-disposition", "inline");
        }
        const signed = await r2.sign(new Request(u, { method: "GET" }),
                                     { aws: { signQuery: true } });
        out[key] = signed.url;
      }
      return json({ urls: out, expires_in: READ_TTL });
    }

    // ── the browser reports the upload finished ──
    // ── set the bucket's CORS policy (admin only) ──
    // R2 implements PutBucketCors on the S3 API, and this function already holds
    // the signing key, so the policy can be set from here instead of by hand.
    // The caller must be an admin of THIS application, checked against the
    // database with their own token — not merely someone who can reach the URL.
    if (action === "set_cors") {
      const meR = await fetch(`${SUPABASE_URL}/rest/v1/me?select=role_code`, {
        headers: { Authorization: auth, apikey: Deno.env.get("SUPABASE_ANON_KEY") ?? "",
                   "Accept-Profile": "api" },
      });
      const me = meR.ok ? await meR.json() : [];
      if (!Array.isArray(me) || me[0]?.role_code !== "ADMIN")
        return json({ error: "Only an admin can change the bucket policy." }, 403);

      const origins: string[] = Array.isArray(body.origins) && body.origins.length
        ? body.origins : [];
      if (!origins.length) return json({ error: "origins[] is required." }, 400);
      const esc = (t: string) => t.replace(/[<>&"']/g, c =>
        ({ "<":"&lt;", ">":"&gt;", "&":"&amp;", '"':"&quot;", "'":"&apos;" }[c] as string));
      const xml =
        `<CORSConfiguration><CORSRule>` +
        origins.map(o => `<AllowedOrigin>${esc(String(o))}</AllowedOrigin>`).join("") +
        `<AllowedMethod>GET</AllowedMethod><AllowedMethod>PUT</AllowedMethod>` +
        `<AllowedMethod>HEAD</AllowedMethod><AllowedHeader>*</AllowedHeader>` +
        `<ExposeHeader>ETag</ExposeHeader><MaxAgeSeconds>3600</MaxAgeSeconds>` +
        `</CORSRule></CORSConfiguration>`;
      const put = await r2.fetch(`${base}?cors`, {
        method: "PUT", body: xml, headers: { "Content-Type": "application/xml" },
      });
      const text = await put.text();
      return json({ ok: put.ok, status: put.status, origins,
                    detail: text.slice(0, 400) || "(empty response)" }, put.ok ? 200 : 400);
    }

    if (action === "get_cors") {
      const g = await r2.fetch(`${base}?cors`, { method: "GET" });
      return json({ status: g.status, policy: (await g.text()).slice(0, 2000) });
    }

    if (action === "confirm") {
      const res = await rpc(auth, "confirm_media", {
        media_ref: body.media_ref, bytes: body.bytes ?? null,
        sha256: body.sha256 ?? null, width: body.width ?? null, height: body.height ?? null,
      });
      return json(res);
    }

    return json({ error: `Unknown action "${action}".` }, 400);
  } catch (e) {
    return json({ error: String((e as Error).message ?? e) }, 400);
  }
});
