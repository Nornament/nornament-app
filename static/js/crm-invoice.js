/* Read an invoice into the Add Purchase form — the legacy InvoiceUploadModal.

   It fills fields in. It never saves: the form still has to be submitted, and
   every value stays editable, because a regex over an OCR'd bill is a guess.

   PDFs use pdf.js, vendored by `manage.py vendor_assets`. Photos use
   tesseract.js, loaded from its CDN on first use exactly as the legacy did —
   it is 3 MB and most invoices arrive as PDFs, so it is not worth vendoring
   until someone actually leans on it. Neither being available costs anything
   but the shortcut. */
(function () {
  const input = document.getElementById('invoice-file');
  const status = document.getElementById('invoice-status');
  const form = document.getElementById('purchase-form');
  if (!input || !form) return;

  const say = (text) => { status.textContent = text; };

  /* the legacy parseInvoiceText, regex for regex */
  function parseInvoiceText(text) {
    const lines = text.split('\n').map((l) => l.trim()).filter(Boolean);
    const amount = text.match(/(?:total|grand total|amount|net amount)[^\d₹]*[₹Rs.]*\s*([\d,]+(?:\.\d{2})?)/i)
      || text.match(/₹\s*([\d,]+(?:\.\d{2})?)/);
    const when = text.match(/(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4})/);
    const invoice = text.match(/(?:invoice|bill|inv|ref)[^\d]*#?\s*([\w\-/]+)/i);
    const description = lines
      .filter((l) => /\d/.test(l) && l.length > 10 && !/invoice|bill|date|total|tax|gst|amount/i.test(l))
      .slice(0, 3).join('; ');
    return {
      amount: amount ? amount[1].replace(/,/g, '') : '',
      date: when ? when[1] : '',
      invoiceNo: invoice ? invoice[1] : '',
      description: description
    };
  }

  /* dd/mm/yyyy and friends -> the yyyy-mm-dd an <input type=date> accepts */
  function isoDate(text) {
    const parts = (text || '').split(/[/\-.]/);
    if (parts.length !== 3) return '';
    let [d, m, y] = parts.map((p) => parseInt(p, 10));
    if (!d || !m || !y) return '';
    if (y < 100) y += 2000;
    if (m > 12) { const swap = d; d = m; m = swap; }   // an mm/dd file
    if (m > 12 || d > 31) return '';
    return y + '-' + String(m).padStart(2, '0') + '-' + String(d).padStart(2, '0');
  }

  function fill(parsed) {
    const set = (name, value) => {
      const field = form.querySelector('[name="' + name + '"]');
      if (field && value) field.value = value;
    };
    set('sold_price', parsed.amount);
    set('sold_on', isoDate(parsed.date));
    set('invoice_no', parsed.invoiceNo);
    set('description', parsed.description);
    if (parsed.invoiceNo) set('remarks', 'Invoice: ' + parsed.invoiceNo);
    const found = ['amount', 'date', 'invoiceNo', 'description'].filter((k) => parsed[k]);
    say(found.length ? 'Read ' + found.length + ' field(s) — check them, then press Add.' : 'Nothing readable — fill it in by hand.');
    document.getElementById('invoice').close();
    /* the form it just filled lives in the Add Purchase sheet, so open that */
    const sheet = document.getElementById('addp');
    if (sheet && !sheet.open) sheet.showModal();
  }

  async function readPdf(file) {
    if (!window.pdfjsLib) throw new Error('The PDF reader is not installed on this server.');
    pdfjsLib.GlobalWorkerOptions.workerSrc = input.dataset.worker;
    const pdf = await pdfjsLib.getDocument({ data: await file.arrayBuffer() }).promise;
    let text = '';
    for (let page = 1; page <= Math.min(pdf.numPages, 3); page += 1) {
      const content = await (await pdf.getPage(page)).getTextContent();
      text += content.items.map((item) => item.str).join(' ') + '\n';
    }
    return text;
  }

  async function readImage(file) {
    if (!window.Tesseract) {
      say('Fetching the text reader (first time only)…');
      await new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = 'https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js';
        script.onload = resolve;
        script.onerror = () => reject(new Error('Could not fetch the text reader — type the bill in instead.'));
        document.head.appendChild(script);
      });
    }
    say('Reading the photo — this takes a few seconds…');
    const worker = await Tesseract.createWorker('eng');
    const url = URL.createObjectURL(file);
    try {
      return (await worker.recognize(url)).data.text;
    } finally {
      await worker.terminate();
      URL.revokeObjectURL(url);
    }
  }

  input.addEventListener('change', async function () {
    const file = this.files[0];
    if (!file) return;
    say('Reading ' + file.name + '…');
    try {
      const text = file.type === 'application/pdf' ? await readPdf(file) : await readImage(file);
      fill(parseInvoiceText(text));
    } catch (error) {
      say(error.message);
    }
    this.value = '';
  });
})();
