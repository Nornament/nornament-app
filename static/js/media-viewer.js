/* The media viewer: a modal gallery, not a bare presigned URL in a new tab.
   A signed link opened in a blank tab loses the filename, the reference and
   every other file on the piece, and leaves whoever opened it on a page that
   is not the app. This keeps them here and lets them walk the set.

   Everything it needs is on the tiles (`[data-view-url]`), in page order, so
   the gallery is whatever the screen is already showing — no second list to
   keep in step with the first.

   The markup is a fixed skeleton in the template and this only ever sets
   `src`, `href` and `textContent` on it. Nothing here builds HTML from a
   filename: whoever uploads a file names it, so a filename is untrusted text,
   and an innerHTML that interpolated one would run it. */
(function () {
  let set = [];
  let at = 0;

  const box = () => document.getElementById('viewerdlg');
  const part = (name) => box().querySelector(`[data-v="${name}"]`);

  function draw() {
    const tile = set[at];
    if (!tile || !box()) return;
    const as = tile.dataset.viewAs;

    for (const name of ['video', 'image', 'pdf', 'none']) {
      const el = part(name);
      const showing = name === as || (name === 'none' && !['video', 'image', 'pdf'].includes(as));
      // clearing src first stops a video playing on into the next item
      if (el.tagName !== 'DIV') el.src = showing ? tile.dataset.viewUrl : '';
      el.hidden = !showing;
    }
    part('ext').textContent = tile.dataset.viewExt || 'FILE';
    part('name').textContent = tile.dataset.viewName || '';
    part('meta').textContent =
      (tile.dataset.viewMeta || '') + (set.length > 1 ? ` · ${at + 1} of ${set.length}` : '');
    part('save').href = tile.dataset.viewSave;
    for (const nav of box().querySelectorAll('[data-vgo]')) nav.hidden = set.length < 2;
    if (!box().open) box().showModal();
  }

  function go(step) {
    if (set.length < 2) return;
    at = (at + step + set.length) % set.length;
    draw();
  }

  document.addEventListener('click', function (event) {
    const open = event.target.closest('[data-view-open]');
    if (open) {
      const tile = open.closest('[data-view-url]');
      if (!tile || !box()) return;
      event.preventDefault();
      watchClose();
      set = [...document.querySelectorAll('[data-view-url]')];
      at = Math.max(0, set.indexOf(tile));
      draw();
      return;
    }
    const step = event.target.closest('[data-vgo]');
    if (step) return go(Number(step.dataset.vgo));
    if (event.target.closest('[data-vclose]')) box().close();
  });

  /* A <video> left with a src keeps playing behind a closed dialog, and the
     dialog can be closed three ways — the button, Esc, or the backdrop. The
     `close` event is the obvious hook and did not fire reliably here, so watch
     the one thing all three genuinely do: drop the `open` attribute. */
  function watchClose() {
    const el = box();
    if (!el || el.dataset.watched) return;
    el.dataset.watched = '1';
    new MutationObserver(() => {
      if (el.open) return;
      for (const name of ['video', 'image', 'pdf']) el.querySelector(`[data-v="${name}"]`).src = '';
    }).observe(el, { attributes: true, attributeFilter: ['open'] });
  }

  document.addEventListener('keydown', function (event) {
    if (!box() || !box().open) return;
    if (event.key === 'ArrowLeft') { event.preventDefault(); go(-1); }
    if (event.key === 'ArrowRight') { event.preventDefault(); go(1); }
  });
})();
