/* Nornament CRM service worker.

   It exists for one reason the page cannot do itself: the Web Share Target.
   A share POST arrives from another app, so the session cookie is not sent
   (SameSite=Lax drops cookies on a cross-site POST navigation). The worker
   intercepts the POST before it reaches the network, stashes the files in a
   cache, and 303s to a plain GET the browser *will* send the cookie with.

   No app-shell caching: every CRM page is server-rendered per request, so a
   cached copy is a stale copy. Static assets only.  */
const STATIC = 'nornament-static-v1';
const SHARE = 'nornament-share';

self.addEventListener('install', () => self.skipWaiting());

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== STATIC && k !== SHARE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  if (event.request.method === 'POST' && url.pathname.endsWith('/share-target')) {
    event.respondWith((async () => {
      try {
        const form = await event.request.formData();
        const files = form.getAll('media').filter((f) => f && f.size);
        const cache = await caches.open(SHARE);
        const names = [];
        for (const [index, file] of files.slice(0, 10).entries()) {
          const key = '/__shared__/' + index;
          await cache.put(key, new Response(file, { headers: { 'Content-Type': file.type || 'image/jpeg' } }));
          names.push({ key: key, name: file.name || 'shared-' + index + '.jpg', type: file.type || 'image/jpeg' });
        }
        await cache.put('/__shared__/index', new Response(JSON.stringify(names), {
          headers: { 'Content-Type': 'application/json' }
        }));
      } catch (error) {
        /* a share we cannot read is a share the page will report as empty */
      }
      return Response.redirect(new URL('share/', self.registration.scope).pathname, 303);
    })());
    return;
  }

  if (event.request.method !== 'GET' || url.origin !== self.location.origin) return;
  if (!url.pathname.startsWith('/static/')) return;

  event.respondWith(
    caches.match(event.request).then((hit) => hit || fetch(event.request).then((response) => {
      if (response && response.status === 200) {
        const copy = response.clone();
        caches.open(STATIC).then((cache) => cache.put(event.request, copy));
      }
      return response;
    }))
  );
});
