/* Photo upload for both halves of the app: presign → PUT → confirm, the same
   three mediahub calls, so every new photo lands in object storage rather than
   in a database column. Scope comes off the input, so the CRM's entities and a
   stock piece use the same code path. No framework — the page reloads on
   success, which is what every other write here does. */
(function () {
  const csrf = () => (document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/) || [])[1] || '';

  async function upload(file, scope, entityId, say) {
    say('Uploading ' + file.name + '…');
    const reserve = await fetch('/media/presign/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
      body: JSON.stringify({
        scope: scope, entity_id: entityId, file_name: file.name,
        mime_type: file.type, bytes: file.size,
        kind: file.type.startsWith('video') ? 'VIDEO' : file.type.startsWith('image') ? 'PHOTO' : 'DOCUMENT'
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

  document.addEventListener('click', async function (event) {
    const button = event.target.closest('[data-detach]');
    if (!button) return;
    event.preventDefault();
    if (!confirm('Remove this photo?')) return;
    const response = await fetch(button.dataset.detach, { method: 'POST', headers: { 'X-CSRFToken': csrf() } });
    if (response.ok) location.reload();
    else alert('Could not remove that photo.');
  });
})();
