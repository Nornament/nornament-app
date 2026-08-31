# Vendored front-end assets

`htmx.min.js`, `pdf.min.js` and `pdf.worker.min.js` are fetched here at image
build time (`deploy/Dockerfile`) or by `python manage.py vendor_assets` — they
are not committed, so this repo carries no third-party minified blob and no
build step.

Every screen works without HTMX. It only saves a page reload: each `hx-get`
sits on a form that also submits normally, and each `hx-post` view answers a
plain form post with a redirect. If the file is missing the app degrades to
full page loads and nothing else changes.

pdf.js powers one shortcut: "read this invoice" on a customer's Purchases tab,
which fills in the Add Purchase form. Without it that button reports it cannot
read the file and the form is typed in by hand, which is what it was before.
