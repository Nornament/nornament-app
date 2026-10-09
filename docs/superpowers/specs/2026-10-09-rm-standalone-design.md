# RM (Stones & Diamonds) as standalone software — design

## What RM is, and what it is not

**RM is the Stones & Diamonds module**: everything under `/inventory/` in
nornament-app — stone batches and pouches, diamonds, purchases, job work,
movements, splits and merges, price lists, stock takes, lookbooks, its
importers and its settings. Its Django app happens to be named `inventory`;
it is reached from the "Stones" sidebar link.

**Not RM, and untouched by this change:** the Stock app (finished pieces, BOMs,
materials, the stock app's own `MaterialInventory` "material inventory",
rate charts, scenarios, reports, the IVY importer, the photo queue), the CRM,
mediahub, the legacy folders, and every screen outside `/inventory/`.

## Owner's rulings (2026-10-09)

- **Fully separate**: its own git repo, Dokploy app, domain, Postgres database
  and logins. Nothing shared at runtime with nornament-app.
- **Start fresh**: no data moves. RM starts empty; stock is imported again with
  RM's own importers. Customer and vendor lists start **blank** — nothing copied.
- **Removed from nornament-app in the same change.**
- **Two roles**: Admin (everything) and Staff.
- **Repo**: `~/Desktop/Tech/nornament/nornament-rm`, private GitHub repo
  `Nornament/nornament-rm` (created only after the owner confirms).
- **Storage**: the existing bucket and keys, under an `rm/` key prefix.
- **Approach**: lift and shift — move the app across nearly verbatim and give
  it small RM-owned replacements for what it borrows.

## The standalone app: `nornament-rm`

The pouch page's **✉ Enquire** button opened a CRM enquiry; with no CRM it is
removed. Clients still enquire from a lookbook (WhatsApp / email), unchanged.

Same stack as nornament-app: Django 5.2, Postgres, gunicorn, whitenoise,
openpyxl, Pillow, boto3; deployed with Dokploy from `deploy/`.

| Folder | Holds |
|---|---|
| `config/` | env-driven settings, URLs, `/healthz`, the public `/lookbook/<token>/` routes |
| `accounts/` | the user model, the two roles, login, forced password change, the Users screen |
| `parties/` | RM's own `Customer` and `Vendor` (suppliers and karigars), and the Customers screen |
| `core/` | what `inventory` borrowed from stock and mediahub, cut to what it uses |
| `inventory/` | the module itself, as it is today |
| `deploy/` | Dockerfile, entrypoint (migrate → collectstatic → gunicorn), compose (web, db, nightly backup), deploy doc |

### What `inventory` borrowed, and its replacement

| Today (nornament-app) | In RM |
|---|---|
| `stock.services.ServiceError`, `require`, `log` | `core.services` |
| `stock.models.ActivityLog`, `ImportBatch` | `core.models` (same fields inventory reads) |
| `stock.masking.mask`, `allowed` | `core.masking`, keeping only the field rules inventory uses |
| `stock.enums.MediaKind` | `core.enums` |
| `stock.views._store_workbook`, `_batch_workbook` | `core.workbooks` (stream to the bucket, local-disk cache) |
| `mediahub.models.MediaAsset`, `storage`, `attach_uploads` | `core.media` — keys start `rm/` |
| `stock.models.Vendor` | `parties.Vendor`: code, name, city, terms, is_active |
| `crm.models.Customer` | `parties.Customer`: customer_code (generated), name, phone, city |
| `crm.templatetags.crm_extras.inr` | `inventory_extras` gets its own `inr` |
| `accounts.*` capabilities, roles, context processor | RM's `accounts` |

`inventory`'s code changes only in its imports. Its migrations are replaced by
one fresh `0001_initial`: the app starts empty, so there is no history to keep.

### Roles and rights

The existing permission names stay, so every `require(...)` and `caps.*` check
in inventory works unchanged.

| Right | Admin | Staff |
|---|---|---|
| `inv_move` — sales, memos, returns, losses, samples, transfers, recounts, stock takes | ✓ | ✓ |
| `inv_assort` — split, merge, assort diamonds | ✓ | ✓ |
| `view_sale` — sale/list prices, the selling price list, and building and sharing lookbooks (lookbooks are gated on it today) | ✓ | ✓ |
| `inv_masters` — imports, pouch details, prices, photos, settings | ✓ | |
| `inv_purchase` — purchases | ✓ | |
| `inv_job` — job work with karigars | ✓ | |
| `view_cost`, `view_vendor`, `view_margin` | ✓ | |
| Users screen; editing/deactivating customers; vendors (on diamonds Settings → Suppliers) | ✓ | |
| Listing and adding customers | ✓ | ✓ |

Staff never sees cost, vendor or karigar names, or margin. The per-role
rights editor on the diamonds Settings page is removed: with two fixed roles
there is nothing to edit. The Django admin is superuser-only, as in
nornament-app.

### Customers and vendors

Both start empty.

- **Vendors** (suppliers and karigars share one list, as today) are edited
  where inventory already edits them: diamonds Settings → Suppliers (code,
  name, city, terms). No second vendor screen is built.
- **Customers** get a Customers screen (list with search, add, edit,
  deactivate). Staff may list and add — a movement that needs a customer
  (sale, memo, sales return) links to "+ New customer" and comes back to the
  form; editing and deactivating are Admin's.

### Look and feel

The existing inventory shell (`inventory_base.html`, `inventory.css`,
`_preloader.html`). The rail footer keeps the user and Sign out and loses the
Stock and CRM links. Login and password-change pages are RM's own, in the
same shell.

## Removal from nornament-app (same change)

Removed:

- the `inventory` app, `templates/inventory_base.html`,
  `static/css/inventory.css`, the `/lookbook/…` routes in `config/urls.py`;
- the "Stones" links in `stock/templates/stock/_nav.html` and
  `templates/crm_base.html`; `inventory.css` from the asset-version hash;
- the five rights `inv_masters`, `inv_purchase`, `inv_job`, `inv_assort`,
  `inv_move` from `accounts.capabilities` and the `Capability` permissions,
  and their row in the Settings → Permissions matrix;
- the Karigar desk role: `KARIGAR` in `ROLE_TABS` and `ROLE_GROUPS`,
  `KarigarDeskMiddleware`, and the stock dashboard's redirect to the shelf.

Migrations, in order:

1. delete the inventory photo rows (`MediaAsset` with `scope='pouch'`) and the
   stones/diamonds import batches (`ImportBatch.source` in `STONES`,
   `DIAMONDS`). Bucket files are left in place — harmless, and recoverable;
2. drop the 16 `inv_*` tables (the inventory app's migrations are unapplied
   and the app removed — done as one `RunSQL` drop in an `accounts` or `stock`
   migration so it runs once the app's code is gone);
3. remove the five permissions; deactivate users whose only group is
   `KARIGAR` (locally: `qa_karigar`), then delete the group;
4. delete what Django keeps about the removed app: its `django_migrations`
   rows, its content types and their model permissions.

Unchanged: everything in "Not RM" above. Stock's own "Karigar / workshop"
field on job cards is a stock `Vendor` and stays.

Consequences the owner accepted: lookbook links already sent to clients stop
working; Karigar-desk logins in nornament-app are deactivated.

## Testing

- **RM**: the inventory suite (62 files) comes across with its imports
  repointed; fixtures build RM's own users, customers and vendors. New tests:
  Staff sees no cost, vendor or margin on every screen the masking walk covers;
  Staff is refused purchase, job work, imports and settings; a photo's key
  starts `rm/`; the Customers and Vendors screens add and edit; a fresh
  database migrates and boots.
- **nornament-app**: no URL in the `inventory` namespace resolves; no `inv_*`
  table or permission remains; no `KARIGAR` group; a `KARIGAR`-only user is
  inactive after migrating; the full suite passes.
- **End to end, locally**: RM against its own empty database and the fake S3 —
  import the owner's stones and diamonds workbooks, post a purchase, record a
  sale to a new customer, build and open a lookbook — as Admin and as Staff.

## Deployment

1. Create the GitHub repo `Nornament/nornament-rm` (owner confirms first) and
   push.
2. In Dokploy, create the RM app from that repo's compose, its own Postgres
   volume, the same `MEDIA_*` bucket settings, a new `DJANGO_SECRET_KEY`, and
   a domain (e.g. `rm.<your domain>`). Create the first superuser from the web
   container's terminal.
3. Push nornament-app's removal to `main`. Stones disappears from
   nornament-app on that deploy, so RM goes live first or at the same time.

## Out of scope

Moving existing stones/diamonds data; syncing customers or vendors with
nornament-app; any link between RM stones and finished pieces; changes to the
Stock app or CRM beyond the removal list above.
