# Publishing without the zip — one setup, then never again

Four minutes of your time, once. After this I push changes straight to
stock.nornament.com and you do nothing.

---

## 1. Make the token

**https://dash.cloudflare.com/profile/api-tokens** → **Create Token** →
**Create Custom Token** (scroll past the templates).

- Name: `nornament-deploy`
- Permissions — exactly one line:

  | | | |
  |---|---|---|
  | **Account** | **Cloudflare Pages** | **Edit** |

- Account Resources: **Include → your account**
- Nothing else. No Zone permissions, no R2, no DNS.

Continue → Create Token. **Copy it now — it is shown once.**

### What this token can and cannot do

It can create deployments on your Pages projects, and read their settings.
That is the entire blast radius. If it leaked tomorrow, someone could publish
a different page at stock.nornament.com — bad, and instantly reversible from
Pages → Deployments → Rollback. It **cannot** read your database, touch R2 or
your photos, change DNS, see billing, or create other tokens.

Compare that to an "Edit Cloudflare Workers" or Global API Key, either of which
would have done the job and also handed over the whole account. Do not use
those, even if a guide tells you to.

## 2. Paste it into Supabase — not into chat

**https://supabase.com/dashboard/project/uygvzdgdtohqlsaiawxs/functions/secrets**

Use the *"paste key-value pairs"* box:

```
CF_API_TOKEN=<the token you just copied>
CF_ACCOUNT_ID=56deee6b737f4d7028180a83b3046fa0
CF_PAGES_PROJECT=nornament-stock
```

`CF_ACCOUNT_ID` is already filled in above — it is the same hex string that
appears in your R2 endpoint, and it is not a secret.

Check `CF_PAGES_PROJECT` matches the project name in **Workers & Pages**. If
your project is called something else, put that instead.

Press **Save**. Then tell me it is done.

**Do not paste the token into this chat.** Not because I would misuse it, but
because a chat transcript is a long-lived copy of it in a place neither of us
controls, and a secret's safety is mostly about how few copies exist.

---

## 3. What happens after

I call an admin-only function called `deploy-site`, which:

1. asks Cloudflare for a short-lived upload token scoped to that one project
2. hashes the files and asks which ones Cloudflare does not already hold
3. uploads only those — an unchanged 600 KB page is not re-sent
4. creates the deployment

Live in about thirty seconds. Cloudflare keeps every previous deployment, so
**Pages → Deployments → Rollback** undoes a bad one in a click. That is your
safety net, and it is better than the one you have now.

The function refuses to deploy anything that does not contain an `index.html`,
because that would take the site down rather than update it.

---

## Two honest caveats

**The upload sequence is not officially documented.** It is what Cloudflare's
own `wrangler` tool does internally. Cloudflare could change it without notice.
If that happens the function starts failing with a clear error and you fall
back to the dashboard drag-and-drop — nothing is lost, nothing is stuck.

**This gives you no diff history.** You will not be able to see *what* changed
between two versions, only that a new one went out and when. If that turns out
to matter — and on a system that prices your stock, it might — the answer is a
GitHub repo connected to Pages, which keeps every version and shows you the
changes before they go live. Say the word and I will set it up alongside this;
the two do not conflict.

---

## Why not just give me the token each session?

Because this sandbox is wiped when the session ends. A token I hold dies with
it, so you would be pasting it again every single time — which is barely better
than the drag-and-drop it replaces. Supabase's secret store is the only place
in this system that persists, which is why it goes there.
