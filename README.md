# Nornament

One application for Nornament's jewellery operation: finished-goods stock, costing and margin, plus the customer CRM — on self-hosted Postgres, deployed to a VPS with Dokploy.

**Nothing here is built yet.** This repo currently holds the spec and the two existing apps it is built from.

---

## Read this first

**[`docs/PLAN.md`](docs/PLAN.md)** — the implementation plan. Phases 0–7, with the exact SQL, endpoint signatures, compose config and cutover sequence. Start there; it is the source of truth for what gets built.

---

## What is in here

| Path | What it is |
|---|---|
| `docs/PLAN.md` | The plan. Read before writing anything. |
| `reference/Stock/` | The existing stock app — one HTML file, 53 Postgres migrations, 3 Deno edge functions. **The migrations and the edge-function contracts are the real spec**; the plan repeatedly points at specific files here. |
| `reference/CRM/` | The existing CRM — one HTML file, React 18 UMD, 6 JSONB tables. |

`reference/` is input, not output. Both directories are copies with their git history stripped — the originals are at `github.com/Nornament/Stock` and `github.com/Nornament/CRM`. Delete `reference/` once Phase 1 has moved what it needs.

## What gets built (per the plan)

```
web/        the merged frontend — shell + two panes + one session.js
api/        FastAPI sidecar: auth, admin, media presigning, PostgREST proxy
db/         the 53 migrations verbatim, plus 0039 / 0040 / 0041
deploy/     docker-compose.yml, migrate.sh, restore SQL
```

---

## Rules

**Never commit:** the Supabase direct connection string, Contabo S3 keys, the JWT secret, `logins.csv`, or any `.dump`. `.gitignore` covers the obvious shapes, but the real defence is not putting them in a file. Secrets live in Dokploy's Environment tab.

The `anon` publishable key already present in the two HTML files is *not* a secret — it identifies the project and nothing else, and every permission is enforced by row-level security and by capability checks inside the `api` functions.

**Phases 0 and 6 cannot be done by an agent.** Pre-flight needs a live Supabase connection and a Contabo bucket; the cutover needs VPS access and a browser on each device that has ever run the CRM. Everything else — Phases 1–5 and authoring 0041 — is ordinary repo work.

**Preserve the security model.** The stock schema carries 45 RLS policies, 109 `SECURITY DEFINER` functions with `search_path` pinned, 111 capability gates and column-level cost masking. `0013_fix_privilege_escalation.sql` fixes a real `current_user`/`session_user` bug — the plan's risk #1 is re-shipping it by letting PostgREST connect as `postgres`. Read that migration before touching auth.

**There are no tests in either app.** Verification is the checklist at the end of the plan, run by hand.
