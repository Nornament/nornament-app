// Nornament CRM — Service Worker
// Caches the app shell for offline use. API calls (Supabase) always go to network.
// Also receives photos shared into the app (e.g. WhatsApp → Share → Nornament).

const CACHE = 'nornament-v2';
const SHELL = [
  './nornament-crm.html',
  './manifest.json',
  './icon-192.png',
  './icon-512.png',
];

// Install: cache app shell
self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(SHELL)).catch(() => {})
  );
  self.skipWaiting();
});

// Activate: clean old caches
self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE && k !== 'nornament-share').map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Convert a shared file blob to a data URL (no FileReader in SW)
const blobToDataURL = async b => {
  const buf = await b.arrayBuffer();
  const bytes = new Uint8Array(buf);
  let s = '';
  for (let i = 0; i < bytes.length; i += 0x8000) {
    s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  }
  return 'data:' + (b.type || 'image/jpeg') + ';base64,' + btoa(s);
};

// Fetch: share-target POST, network-first for Supabase, cache-first for shell
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // Web Share Target: stash shared files, then open the app
  if (e.request.method === 'POST' && url.pathname.endsWith('/share-target')) {
    e.respondWith((async () => {
      try {
        const fd = await e.request.formData();
        const files = fd.getAll('media').filter(f => f && f.size);
        const payload = [];
        for (const f of files.slice(0, 10)) {
          payload.push({name: f.name, type: f.type, data: await blobToDataURL(f)});
        }
        const cache = await caches.open('nornament-share');
        await cache.put('shared-files', new Response(JSON.stringify(payload), {headers: {'Content-Type': 'application/json'}}));
      } catch (err) {}
      return Response.redirect('./nornament-crm.html?shared=1', 303);
    })());
    return;
  }

  if (e.request.method !== 'GET') return;

  // Always network for Supabase / CDN calls
  if (url.hostname.includes('supabase.co') || url.hostname.includes('unpkg.com') || url.hostname.includes('cdnjs') || url.hostname.includes('cdn.jsdelivr') || url.hostname.includes('fonts.g')) {
    e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
    return;
  }

  // Cache-first for app shell, refresh in background
  e.respondWith(
    caches.match(e.request).then(cached => {
      const net = fetch(e.request).then(res => {
        if (res && res.status === 200) {
          const clone = res.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
        }
        return res;
      }).catch(() => cached || caches.match('./nornament-crm.html'));
      return cached || net;
    })
  );
});
