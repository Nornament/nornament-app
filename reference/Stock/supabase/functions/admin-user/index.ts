// ─────────────────────────────────────────────────────────────────────────────
// admin-user — creates a login and the app record behind it, in one step.
//
// Why this exists: a login lives in auth.users and a user lives in
// app.app_user, and creating one without the other produces someone who can
// type a correct password and still arrive as nobody. Making the login needs
// the service key, which must never be in the HTML, so it happens here.
//
// Permission is checked twice on purpose. This function asks the database who
// the caller is using the CALLER'S token, and the database refuses again
// inside upsert_app_user. Neither check depends on the other being right.
// ─────────────────────────────────────────────────────────────────────────────
const SUPABASE_URL = Deno.env.get("SUPABASE_URL")!;
const ANON         = Deno.env.get("SUPABASE_ANON_KEY") ?? "";
const SERVICE      = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";

const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, content-type, apikey",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status, headers: { ...cors, "Content-Type": "application/json" },
  });

/** A password nobody has to think up, and nobody will reuse from another system. */
function makePassword() {
  const words = ["amber","topaz","jasper","opal","coral","onyx","pearl","zircon",
                 "garnet","citrine","beryl","spinel"];
  const b = new Uint32Array(3); crypto.getRandomValues(b);
  return words[b[0] % words.length] + "-" + words[b[1] % words.length] + "-" +
         String(1000 + (b[2] % 9000));
}

async function callerIsAdmin(auth: string) {
  const r = await fetch(`${SUPABASE_URL}/rest/v1/me?select=role_code`, {
    headers: { Authorization: auth, apikey: ANON, "Accept-Profile": "api" },
  });
  if (!r.ok) return false;
  const rows = await r.json();
  return Array.isArray(rows) && rows[0]?.role_code === "ADMIN";
}

/** Run an api RPC as the caller, so the database's own rules still apply. */
async function rpcAsCaller(auth: string, fn: string, payload: unknown) {
  const r = await fetch(`${SUPABASE_URL}/rest/v1/rpc/${fn}`, {
    method: "POST",
    headers: {
      Authorization: auth, apikey: ANON, "Content-Type": "application/json",
      "Content-Profile": "api", "Accept-Profile": "api",
    },
    body: JSON.stringify({ p: payload }),
  });
  const text = await r.text();
  let body: any; try { body = text ? JSON.parse(text) : null; } catch { body = text; }
  if (!r.ok) throw new Error(body?.message ?? `database refused (${r.status})`);
  return body;
}

async function findLogin(email: string) {
  const r = await fetch(
    `${SUPABASE_URL}/auth/v1/admin/users?filter=${encodeURIComponent(email)}`,
    { headers: { apikey: SERVICE, Authorization: `Bearer ${SERVICE}` } });
  if (!r.ok) return null;
  const d = await r.json();
  const list = d?.users ?? [];
  return list.find((u: any) => String(u.email).toLowerCase() === email) ?? null;
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  if (req.method !== "POST") return json({ error: "POST only" }, 405);
  if (!SERVICE) return json({ error: "SUPABASE_SERVICE_ROLE_KEY is not available to this function." }, 503);

  const auth = req.headers.get("Authorization") ?? "";
  if (!auth.startsWith("Bearer ")) return json({ error: "Sign in first." }, 401);
  if (!(await callerIsAdmin(auth)))
    return json({ error: "Only an admin can manage users." }, 403);

  let body: any;
  try { body = await req.json(); } catch { return json({ error: "Expected JSON." }, 400); }
  const action = String(body?.action ?? "create");

  try {
    // ── create the login (if needed) and the app record, together ──────────
    if (action === "create") {
      const email = String(body.email ?? "").trim().toLowerCase();
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email))
        return json({ error: "A working email address is required — it is what they sign in with." }, 400);

      const password = String(body.password ?? "").trim() || makePassword();
      if (password.length < 8)
        return json({ error: "Password must be at least 8 characters." }, 400);

      let login = await findLogin(email);
      let created_login = false;

      if (!login) {
        const r = await fetch(`${SUPABASE_URL}/auth/v1/admin/users`, {
          method: "POST",
          headers: { apikey: SERVICE, Authorization: `Bearer ${SERVICE}`,
                     "Content-Type": "application/json" },
          body: JSON.stringify({ email, password, email_confirm: true }),
        });
        const d = await r.json();
        if (!r.ok) return json({ error: d?.msg ?? d?.error_description ?? `Could not create the login (${r.status}).` }, 400);
        login = d; created_login = true;
      }

      // The app record. The database checks admin again and validates the
      // role and location itself — this call can still fail, and should.
      const saved = await rpcAsCaller(auth, "upsert_app_user", {
        username:      body.username,
        full_name:     body.full_name,
        email,
        role_code:     body.role_code,
        home_location: body.home_location ?? null,
        all_locations: !!body.all_locations,
      });

      return json({ ...saved, email, created_login,
        password: created_login ? password : null,
        note: created_login
          ? "Login created. Give them this password — it is shown once."
          : "That email already had a login; it is now linked to this user." });
    }

    // ── attach an app record to a login that already exists ────────────────
    if (action === "adopt") {
      const saved = await rpcAsCaller(auth, "upsert_app_user", {
        username:      body.username,
        full_name:     body.full_name,
        email:         String(body.email ?? "").trim().toLowerCase(),
        role_code:     body.role_code,
        home_location: body.home_location ?? null,
        all_locations: !!body.all_locations,
      });
      return json(saved);
    }

    // ── new password for someone who has forgotten theirs ──────────────────
    if (action === "reset_password") {
      const email = String(body.email ?? "").trim().toLowerCase();
      const login = await findLogin(email);
      if (!login) return json({ error: `No login for ${email}.` }, 404);
      const password = String(body.password ?? "").trim() || makePassword();
      if (password.length < 8)
        return json({ error: "Password must be at least 8 characters." }, 400);
      const r = await fetch(`${SUPABASE_URL}/auth/v1/admin/users/${login.id}`, {
        method: "PUT",
        headers: { apikey: SERVICE, Authorization: `Bearer ${SERVICE}`,
                   "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        return json({ error: d?.msg ?? `Could not change the password (${r.status}).` }, 400);
      }
      return json({ ok: true, email, password,
                    note: "Password changed. It is shown once." });
    }

    return json({ error: `Unknown action "${action}".` }, 400);
  } catch (e) {
    return json({ error: String((e as Error).message ?? e) }, 400);
  }
});
