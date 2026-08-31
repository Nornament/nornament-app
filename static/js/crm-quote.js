/* The quote calculator — the legacy jewellery_quote_calculator.html, rebuilt.

   Multi-item, multi-component, every number editable, back-solve to an item
   total or to the grand total. It runs in the browser because a quote is a
   scratchpad: nothing here is saved until you press "Attach to enquiry".

   The one thing it does not do that the legacy did is invent rates. Metal and
   stone rates arrive from the server, off the same MetalPurity and RateChart
   rows the costing screens price against, so 925 silver prices off silver —
   which is the bug the whole rewrite exists to fix. Type over any of them and
   the row shows that it no longer matches the chart. */
(function () {
  const root = document.getElementById('quote-root');
  if (!root) return;

  const RATES = JSON.parse(document.getElementById('quote-rates').textContent);
  const METALS = RATES.metals;          // [{karat, metal_name, sale_rate}]
  const STONES = RATES.stones;          // [{code, name, band, uom, sale_rate}]
  const DEFAULT_MAKING = RATES.default_making || 0;

  const money = (n) => '₹' + Math.round(Number(n) || 0).toLocaleString('en-IN');
  const num = (v) => { const n = parseFloat(v); return Number.isFinite(n) ? n : 0; };
  const uid = () => 'c' + Math.random().toString(36).slice(2, 9);

  let items = [];

  /* ── the model ───────────────────────────────────────────────────────── */
  function metalRate(karat) {
    const hit = METALS.find((m) => m.karat === karat);
    return hit ? hit.sale_rate : 0;
  }

  function stoneRate(code, band) {
    const hit = STONES.find((s) => s.code === code && (s.band || '') === (band || ''))
      || STONES.find((s) => s.code === code);
    return hit ? hit.sale_rate : 0;
  }

  function chartRateFor(component) {
    if (component.kind === 'metal') return metalRate(component.karat);
    if (component.kind === 'stone') return stoneRate(component.code, component.band);
    return null;
  }

  function newItem() {
    return { id: uid(), name: 'Item ' + (items.length + 1), code: '', makingRate: DEFAULT_MAKING, components: [] };
  }

  function newComponent(kind) {
    if (kind === 'metal') {
      const first = METALS[0] || { karat: '', metal_name: '' };
      return {
        id: uid(), kind: 'metal', karat: first.karat,
        label: 'Metal (' + first.karat + ')', weight: 0, unit: 'g', rate: metalRate(first.karat)
      };
    }
    if (kind === 'stone') {
      const first = STONES[0] || { code: '', name: 'Stone', band: '', uom: 'ct' };
      return {
        id: uid(), kind: 'stone', code: first.code, band: first.band,
        label: first.name, weight: 0, unit: first.uom || 'ct', rate: stoneRate(first.code, first.band)
      };
    }
    return { id: uid(), kind: 'other', label: 'Other', weight: 1, unit: '', rate: 0 };
  }

  const amountOf = (c) => Math.round(num(c.weight) * num(c.rate));
  const metalGrams = (item) => item.components.filter((c) => c.kind === 'metal')
    .reduce((sum, c) => sum + num(c.weight), 0);
  const makingOf = (item) => Math.round(num(item.makingRate) * metalGrams(item));
  const goodsOf = (item) => item.components.reduce((sum, c) => sum + amountOf(c), 0);
  const totalOf = (item) => goodsOf(item) + makingOf(item);
  const grandTotal = () => items.reduce((sum, item) => sum + totalOf(item), 0);

  /* Rounding moves the making charge, never a stone rate — a stone rate no
     chart agrees with is a quote nobody can reconcile later. Same rule the
     server-side distribute_to_total follows. */
  function solveItem(item, target) {
    const grams = metalGrams(item);
    if (grams <= 0) return false;
    item.makingRate = Math.max(0, (num(target) - goodsOf(item)) / grams);
    return true;
  }

  function solveGrand(target) {
    const spread = num(target) - grandTotal();
    const grams = items.reduce((sum, item) => sum + metalGrams(item), 0);
    if (grams <= 0) return false;
    items.forEach((item) => { item.makingRate = Math.max(0, num(item.makingRate) + spread / grams); });
    return true;
  }

  /* ── rendering ───────────────────────────────────────────────────────── */
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (ch) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
  ));

  function componentRow(item, c) {
    const chart = chartRateFor(c);
    const offChart = chart !== null && Math.abs(chart - num(c.rate)) > 0.5;
    let picker = '';
    if (c.kind === 'metal') {
      picker = '<select data-set="karat" style="width:auto;min-width:150px">'
        + METALS.map((m) => '<option value="' + esc(m.karat) + '"' + (m.karat === c.karat ? ' selected' : '') + '>'
          + esc(m.karat) + ' (' + esc(m.metal_name) + ')</option>').join('') + '</select>';
    } else if (c.kind === 'stone') {
      picker = '<select data-set="stone" style="width:auto;min-width:190px">'
        + STONES.map((s) => {
          const value = s.code + '||' + (s.band || '');
          const selected = s.code === c.code && (s.band || '') === (c.band || '');
          return '<option value="' + esc(value) + '"' + (selected ? ' selected' : '') + '>'
            + esc(s.name) + (s.band ? ' · ' + esc(s.band) : '') + '</option>';
        }).join('') + '</select>';
    } else {
      picker = '<input type="text" data-set="label" value="' + esc(c.label) + '" placeholder="Description">';
    }

    return '<tr data-component="' + c.id + '">'
      + '<td>' + picker + (c.kind !== 'other'
        ? '<div class="sm mu" style="margin-top:3px">' + esc(c.label) + '</div>' : '') + '</td>'
      + '<td class="tr"><input type="number" step="0.001" data-set="weight" value="' + num(c.weight)
        + '" style="width:96px;text-align:right"> <span class="sm mu">' + esc(c.unit) + '</span></td>'
      + '<td class="tr"><input type="number" step="1" data-set="rate" value="' + Math.round(num(c.rate))
        + '" style="width:110px;text-align:right">'
        + (offChart ? '<div class="sm" style="color:var(--warm);margin-top:3px">chart says '
          + money(chart) + ' <button type="button" class="lnk" data-act="reset-rate">use it</button></div>' : '')
      + '</td>'
      + '<td class="tr fw">' + money(amountOf(c)) + '</td>'
      + '<td class="tr"><button type="button" class="BI" data-act="del-component" title="Remove">✕</button></td>'
      + '</tr>';
  }

  function itemCard(item) {
    return '<div class="card mb16" style="padding:0" data-item="' + item.id + '">'
      + '<div class="fl ia jb g8" style="padding:12px 14px;border-bottom:1px solid var(--bdr);flex-wrap:wrap">'
        + '<input type="text" data-set="name" value="' + esc(item.name)
          + '" style="width:auto;flex:1;min-width:160px;font-weight:600" placeholder="Item name">'
        + '<input type="text" data-set="code" value="' + esc(item.code)
          + '" style="width:auto;max-width:150px" placeholder="Code">'
        + '<button type="button" class="btn btn-d btn-sm" data-act="del-item">Delete item</button>'
      + '</div>'
      + '<div style="overflow-x:auto"><table>'
        + '<thead><tr><th>Component</th><th class="tr">Weight</th><th class="tr">Rate</th>'
          + '<th class="tr">Amount</th><th></th></tr></thead>'
        + '<tbody>' + item.components.map((c) => componentRow(item, c)).join('')
          + (item.components.length ? '' : '<tr><td colspan="5"><div class="es"><div class="ei">💎</div>'
            + '<p>No components yet — add metal or a stone below</p></div></td></tr>')
          + '<tr><td>Making Charges<div class="sm mu">' + metalGrams(item).toFixed(3) + ' g × '
            + '<input type="number" step="0.01" data-set="makingRate" value="' + num(item.makingRate).toFixed(2)
            + '" style="width:92px;text-align:right"> /g</div></td>'
            + '<td></td><td></td><td class="tr fw">' + money(makingOf(item)) + '</td><td></td></tr>'
        + '</tbody></table></div>'
      + '<div class="fl ia jb g8" style="padding:10px 14px;background:#FAFAF8;flex-wrap:wrap">'
        + '<div class="fl g8" style="flex-wrap:wrap">'
          + '<button type="button" class="btn btn-s btn-sm" data-act="add-metal">+ Metal</button>'
          + '<button type="button" class="btn btn-s btn-sm" data-act="add-stone">+ Diamond / Stone</button>'
          + '<button type="button" class="btn btn-s btn-sm" data-act="add-other">+ Other</button>'
        + '</div>'
        + '<div class="fl ia g8">'
          + '<span class="sl">Item total</span>'
          + '<input type="number" step="1" data-set="itemTotal" value="' + totalOf(item)
            + '" style="width:130px;text-align:right;font-weight:700" title="Type a target to back-solve the making charge">'
        + '</div>'
      + '</div></div>';
  }

  function render() {
    root.innerHTML = items.length
      ? items.map(itemCard).join('')
      : '<div class="card"><div class="es"><div class="ei">💎</div>'
        + '<p>No items yet — press “+ Add item”, or import a Gati quotation.</p></div></div>';
    document.getElementById('grand-total').textContent = money(grandTotal());
    const target = document.getElementById('grand-target');
    if (document.activeElement !== target) target.value = grandTotal();
    document.getElementById('quote-payload').value = JSON.stringify({ items: items, total: grandTotal() });
    renderPrint();
  }

  function renderPrint() {
    const rows = items.map((item) => {
      const lines = item.components.map((c) => '<tr><td>' + esc(c.label)
        + '</td><td class="tr">' + num(c.weight) + ' ' + esc(c.unit)
        + '</td><td class="tr">' + money(c.rate) + '</td><td class="tr">' + money(amountOf(c)) + '</td></tr>').join('');
      return '<h3>' + esc(item.name) + (item.code ? ' <small>' + esc(item.code) + '</small>' : '') + '</h3>'
        + '<table><thead><tr><th>Component</th><th class="tr">Weight</th><th class="tr">Rate</th>'
        + '<th class="tr">Amount</th></tr></thead><tbody>' + lines
        + '<tr><td>Making charges</td><td class="tr">' + metalGrams(item).toFixed(3) + ' g</td>'
        + '<td class="tr">' + money(item.makingRate) + '/g</td><td class="tr">' + money(makingOf(item)) + '</td></tr>'
        + '<tr><th>Item total</th><th></th><th></th><th class="tr">' + money(totalOf(item)) + '</th></tr>'
        + '</tbody></table>';
    }).join('');
    document.getElementById('print-body').innerHTML = rows
      + '<h2 class="tr" style="margin-top:18px">Grand total ' + money(grandTotal()) + '</h2>';
  }

  /* ── events ──────────────────────────────────────────────────────────── */
  const findItem = (node) => items.find((i) => i.id === node.closest('[data-item]').dataset.item);
  const findComponent = (item, node) => item.components.find((c) => c.id === node.closest('[data-component]').dataset.component);

  root.addEventListener('click', function (event) {
    const button = event.target.closest('[data-act]');
    if (!button) return;
    const item = findItem(button);
    const act = button.dataset.act;
    if (act === 'del-item') items = items.filter((i) => i !== item);
    else if (act === 'add-metal') item.components.push(newComponent('metal'));
    else if (act === 'add-stone') item.components.push(newComponent('stone'));
    else if (act === 'add-other') item.components.push(newComponent('other'));
    else if (act === 'del-component') {
      const component = findComponent(item, button);
      item.components = item.components.filter((c) => c !== component);
    } else if (act === 'reset-rate') {
      const component = findComponent(item, button);
      component.rate = chartRateFor(component);
    }
    render();
  });

  root.addEventListener('change', function (event) {
    const field = event.target.closest('[data-set]');
    if (!field) return;
    const item = findItem(field);
    const key = field.dataset.set;

    if (key === 'name' || key === 'code') { item[key] = field.value; return; }
    if (key === 'makingRate') { item.makingRate = num(field.value); render(); return; }
    if (key === 'itemTotal') {
      if (!solveItem(item, field.value)) alert('Add some metal first — the making charge is what absorbs the rounding.');
      render();
      return;
    }

    const component = findComponent(item, field);
    if (key === 'karat') {
      component.karat = field.value;
      const hit = METALS.find((m) => m.karat === field.value);
      component.label = 'Metal (' + field.value + ')';
      component.rate = hit ? hit.sale_rate : 0;
    } else if (key === 'stone') {
      const [code, band] = field.value.split('||');
      const hit = STONES.find((s) => s.code === code && (s.band || '') === band);
      component.code = code;
      component.band = band;
      component.label = hit ? hit.name : code;
      component.unit = hit ? (hit.uom || 'ct') : 'ct';
      component.rate = hit ? hit.sale_rate : 0;
    } else if (key === 'label') component.label = field.value;
    else if (key === 'weight') component.weight = num(field.value);
    else if (key === 'rate') component.rate = num(field.value);
    render();
  });

  document.getElementById('add-item').addEventListener('click', function () {
    items.push(newItem());
    render();
  });

  document.getElementById('clear-quote').addEventListener('click', function () {
    if (!items.length || confirm('Clear the whole quote?')) { items = []; render(); }
  });

  document.getElementById('grand-target').addEventListener('change', function () {
    if (!solveGrand(this.value)) alert('Add some metal first — the making charge is what absorbs the rounding.');
    render();
  });

  document.getElementById('print-quote').addEventListener('click', () => window.print());

  /* Letterhead: printed as a fixed background behind the quote, with the
     margins the shop's paper needs. The legacy uploaded a PDF; a PNG or JPEG
     of the same sheet prints identically and needs no PDF renderer. */
  const letterhead = document.getElementById('letterhead-file');
  if (letterhead) {
    const apply = () => {
      const sheet = document.getElementById('print-sheet');
      sheet.style.paddingTop = document.getElementById('lh-top').value + 'mm';
      sheet.style.paddingBottom = document.getElementById('lh-bottom').value + 'mm';
      sheet.style.paddingLeft = sheet.style.paddingRight = document.getElementById('lh-side').value + 'mm';
    };
    letterhead.addEventListener('change', function () {
      const file = this.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => {
        document.getElementById('print-sheet').style.backgroundImage = 'url(' + reader.result + ')';
        document.getElementById('letterhead-status').textContent = file.name + ' — shown on the printed sheet.';
      };
      reader.readAsDataURL(file);
    });
    ['lh-top', 'lh-bottom', 'lh-side'].forEach((id) => document.getElementById(id).addEventListener('input', apply));
    apply();
  }

  /* Gati ERP quotation import — the legacy parseGatiText, over pdf.js text. */
  const gati = document.getElementById('gati-file');
  if (gati) {
    gati.addEventListener('change', async function () {
      const file = this.files[0];
      const status = document.getElementById('gati-status');
      if (!file) return;
      status.textContent = 'Reading ' + file.name + '…';
      try {
        if (!window.pdfjsLib) throw new Error('The PDF reader is not installed on this server.');
        pdfjsLib.GlobalWorkerOptions.workerSrc = this.dataset.worker;
        const pdf = await pdfjsLib.getDocument({ data: await file.arrayBuffer() }).promise;
        let text = '';
        for (let page = 1; page <= pdf.numPages; page += 1) {
          const content = await (await pdf.getPage(page)).getTextContent();
          text += content.items.map((i) => i.str).join(' ') + '\n';
        }
        const found = parseGati(text);
        if (!found.length) throw new Error('No priced lines found in that PDF.');
        items = items.concat(found);
        status.textContent = 'Imported ' + found.length + ' item(s) — check every rate before quoting.';
        render();
      } catch (error) {
        status.textContent = error.message;
      }
      this.value = '';
    });
  }

  /* Lines look like "<description> <weight> g <rate> <amount>". Anything it
     cannot read is left out and said so, rather than guessed at. */
  function parseGati(text) {
    const out = [];
    text.split('\n').forEach((line) => {
      const match = line.match(/^(.{4,60}?)\s+([\d.]+)\s*(g|gm|grams?|ct|cts?)\s+([\d,]+(?:\.\d+)?)\s+([\d,]+(?:\.\d+)?)/i);
      if (!match) return;
      const unit = /^c/i.test(match[3]) ? 'ct' : 'g';
      const item = newItem();
      item.name = match[1].trim();
      item.makingRate = 0;
      item.components = [{
        id: uid(),
        kind: unit === 'g' ? 'metal' : 'stone',
        karat: unit === 'g' ? (METALS[0] || {}).karat : undefined,
        label: match[1].trim(),
        weight: parseFloat(match[2]),
        unit: unit,
        rate: parseFloat(match[4].replace(/,/g, ''))
      }];
      out.push(item);
    });
    return out;
  }

  render();
})();
