# Vendored front-end assets

`htmx.min.js` is fetched here at image build time (`deploy/Dockerfile`) or by
`python manage.py vendor_assets` — it is not committed, so this repo carries no
third-party minified blob and no build step.

Every screen works without it. HTMX only saves a page reload: each `hx-get`
sits on a form that also submits normally, and each `hx-post` view answers a
plain form post with a redirect. If the file is missing the app degrades to
full page loads and nothing else changes.
