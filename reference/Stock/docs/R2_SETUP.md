# Turning on photo storage — five minutes, once

Everything is built and waiting on one credential. This is the whole job.

---

## 1. Make the token

Open **https://dash.cloudflare.com/?to=/:account/r2/api-tokens**

- **Create Account API token** — not a User API token. If the next page shows you
  one long token string instead of a *pair* of keys, you clicked the wrong one.
- Permission: **Object Read & Write**. Read-only will fail later with a 403 that
  looks like a CORS fault and isn't.
- Scope: **Apply to specific buckets** → `nornament-media`
- Create.

The result page shows **Access Key ID** and **Secret Access Key**.
**The secret is shown once.** Copy both before you leave the page. If you lose
it, delete the token and make another — nothing else breaks.

## 2. Copy the account ID

Cloudflare → **R2** → **Overview**. The **Account ID** is in the right sidebar.
It is the same hex string that appears in your S3 endpoint:

```
https://<THIS_BIT>.r2.cloudflarestorage.com
```

## 3. Paste all four into Supabase

**https://supabase.com/dashboard/project/uygvzdgdtohqlsaiawxs/functions/secrets**

That page has a line reading *"Insert or update multiple secrets at once by
pasting key-value pairs"*. Click the **Name** box and paste this whole block
with your values filled in:

```
R2_ACCOUNT_ID=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET=nornament-media
```

Press **Save**. The table below should change from *"No custom secrets created"*
to four rows with SHA256 digests. That is how you know it took.

## 4. CORS on the bucket

R2 → `nornament-media` → **Settings** → **CORS Policy** → paste:

```json
[
  {
    "AllowedOrigins": [
      "https://stock.nornament.com",
      "https://nornament-stock.pages.dev"
    ],
    "AllowedMethods": ["GET", "PUT", "HEAD"],
    "AllowedHeaders": ["*"],
    "ExposeHeaders": ["ETag"],
    "MaxAgeSeconds": 3600
  }
]
```

Cloudflare's own documentation is blunt about why this is not optional:
*"Without a CORS policy, browser-based uploads and downloads using presigned
URLs will fail, even though the presigned URL itself is valid."*

This has to be done by hand in the dashboard — the R2 token is scoped to objects,
not to bucket settings, so the server gets a 403 trying to set it. See
`R2_CORS.md` for the full reasoning.

---

## Then tell me

I will call the function, which reports back exactly which of the four secrets
it can see, and upload one real photo to one piece. That single test proves the
token is read-write, the CORS policy took, and the signature works.

Do not let the team start uploading until that test passes.

---

## What is already done, so you are not wondering

| | |
|---|---|
| R2 bucket | `nornament-media` created |
| Edge function | `media-url` deployed, version 3 — signs upload, view and download links |
| Database | `reserve_media`, `confirm_media`, `detach_media`, `api.media` |
| App | Media tab on every piece: choose files, thumbnails, download, download all |
| Naming | `24P00088/24P00088__PHOTO__r1__M000123.tif` — the reference is inside the filename, so a renamed file still finds its piece |
| Photos vs CAD | photos attach to the **piece**, CAD and 3DM to the **design** |

The bucket sits in **ENAM**, not APAC — location hints are best effort and
Cloudflare did not honour it on either attempt. It works; uploads from India
just travel further than they needed to. If it turns out to be slow in practice,
the fix for *downloads* is a custom domain on the bucket so Cloudflare caches
near the viewer, and that can be added at any time.

## Still waiting on you elsewhere

The **fixed-amount making charge** needs two small function changes before
"fixed amount" computes anything other than zero. I showed you the SQL a few
messages back and have not run it. Say go whenever.
