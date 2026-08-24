# CORS on the bucket — one paste, 30 seconds

I could not do this from the server. Explanation below, but the action is:

**R2 → `nornament-media` → Settings → CORS Policy → Edit → paste → Save**

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

Two origins because Pages keeps `nornament-stock.pages.dev` alive alongside the
custom domain, and a browser sitting on either one has to be able to talk to R2.
If you drop the pages.dev origin, uploads still work from stock.nornament.com —
you just lose the fallback URL.

Nothing else in this list is optional:

- **PUT** is the upload. Without it the team can browse photos and not add any.
- **ETag** is how the browser confirms the bytes that landed match the bytes it
  sent. Without it an upload can half-fail silently.

## Why the server could not set it

I added an admin-only `set_cors` action to the `media-url` function (deployed,
version 5) and called it with a real admin login. R2 answered:

```
403 AccessDenied
```

The R2 token in your Supabase secrets is scoped **Object Read & Write**. That
covers reading and writing files, which is all the app does day to day. It does
not cover changing the bucket's own configuration — CORS is a bucket setting,
not an object.

The alternative was to ask you for an **Admin Read & Write** token instead. I
did not, and would push back if you offered: that token can delete the entire
bucket, and it would then live permanently in the function's secrets to save you
one paste, once. The blast radius is not worth it.

The `set_cors` / `get_cors` actions stay in the function. They cost nothing, they
refuse anyone who is not an admin, and they will start working the day the token
scope changes — if it ever does.

## Proving it took

There is no way to read the policy back with the current token — `get_cors` gets
the same 403. So the test is the real one: sign in at stock.nornament.com, open
a piece, Media tab, upload one photo. If it lands and then displays, CORS is
correct. If the upload stalls at 0% or the console says the fetch was blocked,
the paste did not save — the dashboard is quiet about a malformed JSON array.
