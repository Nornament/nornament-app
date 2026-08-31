/* The share-target landing page.

   The service worker has already stashed whatever another app shared into the
   'nornament-share' cache. This reads it back, shows it, and attaches it to
   whichever customer is picked — through the same presign/PUT/confirm calls
   every other upload uses. */
(function () {
  const SHARE = 'nornament-share';
  const strip = document.getElementById('share-strip');
  const status = document.getElementById('share-status');
  const picker = document.getElementById('share-picker');
  if (!strip) return;

  let files = [];

  async function load() {
    if (!('caches' in window)) return say('This browser cannot receive shared files.');
    const cache = await caches.open(SHARE);
    const index = await cache.match('/__shared__/index');
    if (!index) return say('Nothing shared. Share a photo to Nornament from another app to land here.');
    const entries = await index.json();
    for (const entry of entries) {
      const hit = await cache.match(entry.key);
      if (!hit) continue;
      const blob = await hit.blob();
      files.push(new File([blob], entry.name, { type: entry.type || blob.type }));
      const img = document.createElement('img');
      img.src = URL.createObjectURL(blob);
      img.alt = entry.name;
      strip.appendChild(img);
    }
    if (!files.length) return say('Nothing shared.');
    say(files.length + ' file' + (files.length === 1 ? '' : 's') + ' ready — pick a customer.');
    picker.hidden = false;
  }

  function say(text) { if (status) status.textContent = text; }

  async function clear() {
    const cache = await caches.open(SHARE);
    for (const key of await cache.keys()) await cache.delete(key);
  }

  picker.addEventListener('click', async function (event) {
    const row = event.target.closest('[data-customer]');
    if (!row || !files.length) return;
    event.preventDefault();
    picker.style.pointerEvents = 'none';
    try {
      for (const file of files) {
        await window.nornamentUpload(file, 'customer', row.dataset.customer, say);
      }
      await clear();
      location = row.href;
    } catch (error) {
      say(error.message);
      picker.style.pointerEvents = '';
    }
  });

  load().catch((error) => say(error.message));
})();
