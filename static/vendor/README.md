# Vendored front-end assets

`htmx.min.js` is committed — htmx 2.0.4, byte-identical to
`unpkg.com/htmx.org@2.0.4/dist/htmx.min.js`
(sha256 `e209dda5c8235479f3166defc7750e1dbcd5a5c1808b7792fc2e6733768fb447`).
It used to be fetched at image build like the rest, and a build that could not
reach unpkg shipped an app where nothing live-updating worked and no log line
said why. 50KB in the repo is the cheaper failure.

`pdf.min.js` and `pdf.worker.min.js` are still fetched at image build time
(`deploy/Dockerfile`) or by `python manage.py vendor_assets`. They are 1.4MB
together and their absence costs exactly one button.

To update htmx: `curl -o static/vendor/htmx.min.js https://unpkg.com/htmx.org@<version>/dist/htmx.min.js`,
check the diff is a version bump, commit it.

Every screen works without HTMX. It only saves a page reload: each `hx-get`
sits on a form that also submits normally, and each `hx-post` view answers a
plain form post with a redirect. If the file is missing the app degrades to
full page loads and nothing else changes.

pdf.js powers one shortcut: "read this invoice" on a customer's Purchases tab,
which fills in the Add Purchase form. Without it that button reports it cannot
read the file and the form is typed in by hand, which is what it was before.
