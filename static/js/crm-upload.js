/* Photo upload for both halves of the app: presign → PUT → confirm, the same
   three mediahub calls, so every new photo lands in object storage rather than
   in a database column. Scope comes off the input, so the CRM's entities and a
   stock piece use the same code path. No framework — the page reloads on
   success, which is what every other write here does. */
(function () {
  const csrf = () => (document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/) || [])[1] || '';

  async function upload(file, scope, entityId, say, kind) {
    say('Uploading ' + file.name + '…');
    const reserve = await fetch('/media/presign/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
      body: JSON.stringify({
        scope: scope, entity_id: entityId, file_name: file.name,
        mime_type: file.type, bytes: file.size,
        /* The stock media tab names the kind itself — a graph and a job card
           are both a JPEG and the content type cannot tell them apart. Only
           when nobody said is it guessed from the type. */
        kind: kind || (file.type.startsWith('video') ? 'VIDEO' : file.type.startsWith('image') ? 'PHOTO' : 'DOCUMENT')
      })
    });
    if (!reserve.ok) throw new Error((await reserve.json()).error || 'could not reserve an upload');
    const slot = await reserve.json();

    if (slot.direct) {
      const put = await fetch(slot.url, { method: 'PUT', headers: { 'Content-Type': file.type }, body: file });
      if (!put.ok) throw new Error('the storage bucket rejected the file');
    } else {
      const body = new FormData();
      body.append('file', file);
      const put = await fetch(slot.url, { method: 'POST', headers: { 'X-CSRFToken': csrf() }, body: body });
      if (!put.ok) throw new Error('the upload did not go through');
    }

    const done = await fetch('/media/confirm/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
      body: JSON.stringify({ media_id: slot.media_id })
    });
    if (!done.ok) throw new Error((await done.json()).error || 'the file did not land in the bucket');
  }

  /* the share-target page needs the same three calls for a File it pulled out
     of a cache rather than off an <input> */
  window.nornamentUpload = upload;

  document.addEventListener('change', async function (event) {
    const input = event.target.closest('[data-upload-scope]');
    if (!input || !input.files.length) return;
    const status = input.closest('label').parentNode.querySelector('[data-upload-status]');
    const say = (text) => { if (status) status.textContent = text; };
    try {
      for (const file of input.files) {
        await upload(file, input.dataset.uploadScope, input.dataset.uploadId, say);
      }
      location.reload();
    } catch (error) {
      say(error.message);
      input.value = '';
    }
  });

  /* The stock media tab uploads from a modal rather than a drop zone: the kind
     is a choice, not something a file extension can answer, so the form asks
     for it first and the picked option carries its own scope — a CAD file
     belongs to the design, a photograph to the one piece. */
  document.addEventListener('submit', async function (event) {
    const form = event.target.closest('[data-upload-form]');
    if (!form) return;
    event.preventDefault();
    const picked = form.querySelector('[name="kind"]')?.selectedOptions?.[0];
    const kind = picked ? picked.value : form.dataset.kind;
    const scope = picked ? picked.dataset.scope : form.dataset.scope;
    const entityId = picked ? picked.dataset.entity : form.dataset.entity;
    const files = form.querySelector('input[type="file"]').files;
    const status = form.querySelector('[data-upload-status]');
    const say = (text) => { if (status) status.textContent = text; };
    if (!files.length) return say('Choose a file first.');
    const submit = form.querySelector('button.primary');
    if (submit) submit.disabled = true;
    try {
      for (const file of files) await upload(file, scope, entityId, say, kind);
      location.reload();
    } catch (error) {
      say(error.message);
      if (submit) submit.disabled = false;
    }
  });

  /* "+ Add photographs" on a section opens the same modal with that kind
     already picked — the section heading is the choice. */
  document.addEventListener('click', function (event) {
    const tile = event.target.closest('[data-add-media]');
    if (!tile) return;
    const dialog = document.getElementById('uploaddlg');
    if (!dialog) return;
    dialog.querySelector('[name="kind"]').value = tile.dataset.addMedia;
    dialog.querySelector('[name="kind"]').dispatchEvent(new Event('change', { bubbles: true }));
    dialog.showModal();
  });

  /* the accept list and the note follow whatever kind is picked */
  document.addEventListener('change', function (event) {
    const select = event.target.closest('#uploaddlg [name="kind"]');
    if (!select) return;
    const option = select.selectedOptions[0];
    const form = select.closest('form');
    form.querySelector('input[type="file"]').accept = option.dataset.accept || '';
    const note = form.querySelector('#uploadnote');
    if (note) note.textContent = option.dataset.note || '';
  });

  document.addEventListener('click', async function (event) {
    const button = event.target.closest('[data-detach]');
    if (!button) return;
    event.preventDefault();
    if (!confirm('Remove this file? The object stays in the bucket; the row stops showing.')) return;
    const response = await fetch(button.dataset.detach, { method: 'POST', headers: { 'X-CSRFToken': csrf() } });
    if (response.ok) location.reload();
    else alert('Could not remove that photo.');
  });
})();
