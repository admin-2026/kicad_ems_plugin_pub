
// ---------- Donut chart (vizDonut) ----------
// vizDonut(rows, opts) -> {el, mount()}
//   rows: [{label, lead, note, value}] -- `value` sizes the slice, `lead` is
//         the figure shown for it, `note` an optional aside beside the label.
//   opts: {slots, size, caption, ariaLabel, tailLabel}
// The caller inserts `el` and then calls mount(): text has no measurable
// length until it is in the document, and the centre read-out is fitted.
// The theme's categorical slots, in their documented order (vizToken reads
// them off the stylesheet, so the ring, the plots and the grid viewer cannot
// end up with three different blues).
const vizDonutSlots =
    [1, 2, 3, 4, 5, 6].map(i => vizToken('--s' + i, '#3987e5'));
const vizDonutCss = `
.vz-donut{margin:0;padding:14px 12px 10px;background:var(--plot);
          border:1px solid var(--line);border-radius:8px}
.vz-donut-fig{display:block;margin:0 auto}
.vz-donut-seg{cursor:default;
              transition:stroke-width .12s ease,opacity .12s ease,
                         stroke-dasharray .6s cubic-bezier(.32,.72,.3,1)}
.vz-donut-val{font:500 40px var(--font-mono);fill:var(--ink);
               letter-spacing:-.02em}
.vz-donut-cap{font:10px var(--font-ui);fill:var(--ink-3);
               letter-spacing:.1em;text-transform:uppercase}
.vz-donut-rows{font-size:12px;line-height:1.5;margin-top:4px}
.vz-donut-row{display:flex;align-items:center;gap:8px;padding:4px 6px;
              border-radius:4px;transition:background .12s ease;outline:none}
.vz-donut-row.on{background:rgba(255,255,255,.05)}
.vz-donut-row:focus-visible{outline:1px solid var(--accent);outline-offset:-1px}
.vz-donut-key{width:10px;height:10px;border-radius:3px;flex:none;
              transition:transform .12s ease}
.vz-donut-row.on .vz-donut-key{transform:scale(1.3)}
.vz-donut-name{color:var(--ink-2)}
.vz-donut-note{color:var(--ink-3)}
.vz-donut-share{margin-left:auto;color:var(--ink);
                font-family:var(--font-mono);
                font-variant-numeric:tabular-nums}
@media (prefers-reduced-motion:reduce){
  .vz-donut-seg{transition:stroke-width .12s ease,opacity .12s ease}
}
`;
function vizDonutStyle() {
  if (document.getElementById('vz-donut-css')) return;
  const style = document.createElement('style');
  style.id = 'vz-donut-css';
  style.textContent = vizDonutCss;
  document.head.appendChild(style);
}
function vizDonutSvg(tag, attrs) {
  const n = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const k in attrs) n.setAttribute(k, attrs[k]);
  return n;
}
// Rows as the ring needs them: shares clamped at zero, and any tail beyond
// the palette folded into one slice (never a generated hue). The folded
// slice's own figure is written from the shares it swallowed.
function vizDonutFold(rows, max, total, tailLabel) {
  const out = rows.map(x => ({label: String(x.label || ''),
                              lead: String(x.lead || ''),
                              note: String(x.note || ''),
                              value: Math.max(0, +x.value || 0)}));
  if (out.length <= max) return out;
  const tail = out.splice(max - 1);
  const sum = tail.reduce((a, x) => a + x.value, 0);
  out.push({label: `${tailLabel} (${tail.length})`, note: '', value: sum,
            lead: total > 0 ? (100 * sum / total).toFixed(1) + '%' : ''});
  return out;
}
function vizDonut(rows, opts = {}) {
  vizDonutStyle();
  const slots = opts.slots || vizDonutSlots;
  const size = opts.size || 236, mid = size / 2;
  const sw = 26, rad = mid - sw / 2 - 10, circ = 2 * Math.PI * rad;
  const gap = 2, hole = 2 * (rad - sw / 2) - 14;
  const total = rows.reduce((a, x) => a + Math.max(0, +x.value || 0), 0);
  const data = vizDonutFold(rows, slots.length, total,
                            opts.tailLabel || 'other');

  const el = document.createElement('figure');
  el.className = 'vz-donut';
  const fig = vizDonutSvg('svg', {
      class: 'vz-donut-fig', width: size, height: size,
      viewBox: `0 0 ${size} ${size}`, role: 'img'});
  fig.setAttribute('aria-label', (opts.ariaLabel || 'Shares') + ': ' +
      data.map(d => `${d.label} ${d.lead}`).join(', '));

  // One <circle> per slice, dashed to its own arc. No track behind them: the
  // ring closes at 100% by construction, so anything a track would show
  // through is the 2 px separation, which should be the card and not a band.
  let at = 0;  // where the previous slices left off, in turns
  const segs = data.map((d, i) => {
    const frac = total > 0 ? d.value / total : 0;
    const seg = vizDonutSvg('circle', {
        class: 'vz-donut-seg', cx: mid, cy: mid, r: rad, fill: 'none',
        stroke: slots[i], 'stroke-width': sw,
        'stroke-dasharray': `0 ${circ}`,
        'stroke-dashoffset': -(at * circ + gap / 2),
        transform: `rotate(-90 ${mid} ${mid})`});
    const title = vizDonutSvg('title', {});
    title.textContent = d.note ? `${d.label}: ${d.lead} ${d.note}`
                               : `${d.label}: ${d.lead}`;
    seg.appendChild(title);
    seg.__len = Math.max(0, frac * circ - gap);
    fig.appendChild(seg);
    at += frac;
    return seg;
  });
  const val = vizDonutSvg('text', {class: 'vz-donut-val', x: mid, y: mid - 2,
                                   'text-anchor': 'middle'});
  const cap = vizDonutSvg('text', {class: 'vz-donut-cap', x: mid, y: mid + 20,
                                   'text-anchor': 'middle'});
  fig.appendChild(val);
  fig.appendChild(cap);
  el.appendChild(fig);

  // The legend: every share in text, so the chart is readable without colour
  // and without hovering. Labels come from the caller, so they go in as text.
  const list = document.createElement('div');
  list.className = 'vz-donut-rows';
  const items = data.map((d, i) => {
    const item = document.createElement('div');
    item.className = 'vz-donut-row';
    item.tabIndex = 0;
    const key = document.createElement('span');
    key.className = 'vz-donut-key';
    key.style.background = slots[i];
    key.style.opacity = d.value > 0 ? 1 : 0.35;
    const name = document.createElement('span');
    name.className = 'vz-donut-name';
    name.textContent = d.label;
    item.appendChild(key);
    item.appendChild(name);
    if (d.note) {
      const n = document.createElement('span');
      n.className = 'vz-donut-note';
      n.textContent = d.note;
      item.appendChild(n);
    }
    const share = document.createElement('span');
    share.className = 'vz-donut-share';
    share.textContent = d.lead;
    item.appendChild(share);
    list.appendChild(item);
    return item;
  });
  el.appendChild(list);

  // Text set inside the ring, shrunk if the caller's own wording is longer
  // than the hole: a label is never clipped and never crosses the ring.
  function fit(node, text, px) {
    node.style.fontSize = px + 'px';
    node.textContent = text;
    const w = node.getComputedTextLength();
    if (w > hole) node.style.fontSize = Math.max(8, px * hole / w) + 'px';
  }
  const restIdx = Math.min(opts.restIndex || 0, data.length - 1);
  function readout(k) {
    fit(val, data[k].lead, 40);
    fit(cap, k === restIdx && opts.caption ? opts.caption : data[k].label, 11);
  }
  // Hovering or focusing either a slice or its legend row lifts both and
  // moves the centre read-out onto it; at rest the centre is the headline
  // row, which is why the chart needs no floating tooltip.
  function show(k) {
    readout(k);
    segs.forEach((s, i) => {
      s.setAttribute('stroke-width', i === k ? sw + 6 : sw);
      s.style.opacity = i === k ? 1 : 0.45;
    });
    items.forEach((it, i) => it.classList.toggle('on', i === k));
  }
  function rest() {
    readout(restIdx);
    segs.forEach(s => {
      s.setAttribute('stroke-width', sw);
      s.style.opacity = 1;
    });
    items.forEach(it => it.classList.remove('on'));
  }
  data.forEach((d, i) => {
    const on = () => show(i), off = () => rest();
    for (const node of [segs[i], items[i]]) {
      node.addEventListener('pointerenter', on);
      node.addEventListener('pointerleave', off);
    }
    items[i].addEventListener('focus', on);
    items[i].addEventListener('blur', off);
  });

  // Once in the document: fit the read-out (which has to measure text) and
  // let the slices grow into place from nothing, unless the reader asked for
  // no motion -- the CSS transition is what animates, so that setting alone
  // decides it.
  function mount() {
    rest();
    requestAnimationFrame(() => {
      for (const s of segs)
        s.setAttribute('stroke-dasharray', `${s.__len} ${circ - s.__len}`);
    });
  }
  return {el: el, mount: mount, show: show, rest: rest};
}

const PB_SECTION = "Power budget";

// ---------- Power budget donut (fdtd::efficiency) ----------
// One page panel (src/report/ReportPanels.hpp), drawn with vizDonut.
(function () {
const CSS = `
.pb-sub{font-size:12px;color:var(--ink-3);line-height:1.55;margin:-2px 0 8px}
`;

// A row's headline figure is its text up to the first space ("3.3%" out of
// "3.3% (|S11| -14.8 dB)"); the rest rides beside the label as a note. Both
// come from the one string the dump carries, so the ring, the legend and the
// data file can never disagree over a rounding.
const lead = t => String(t).split(/\s+/)[0];
const note = t => String(t).slice(lead(t).length).trim();

function render(ctx) {
  const rows = (ctx.rows || []).map(r => ({
      label: r.label || r.key || '',
      lead: lead(r.text || ''),
      note: note(r.text || ''),
      value: Math.max(0, +r.value || 0)}));
  if (!rows.length) return;

  if (!document.getElementById('pb-css')) {
    const style = document.createElement('style');
    style.id = 'pb-css';
    style.textContent = CSS;
    document.head.appendChild(style);
  }

  // .vizpanel is how a panel says "I mounted this": the page takes every one
  // away before it renders again (vizRenderReset), so stepping through a set
  // of runs replaces this donut rather than stacking another under it.
  const wrap = document.createElement('div');
  wrap.className = 'vizpanel';
  const h = document.createElement('h2');
  h.textContent = 'Power budget';
  const sub = document.createElement('div');
  sub.className = 'pb-sub';
  sub.innerHTML = 'Shares of P<sub>avail</sub>, the power a matched source ' +
                  'offers the antenna: they sum to 100%. The radiated share ' +
                  'is the antenna&rsquo;s total efficiency.';
  wrap.appendChild(h);
  wrap.appendChild(sub);

  // Row 0 -- radiated, the row the module adds first -- is the headline the
  // ring's centre rests on, under the name the page gives it.
  const donut = vizDonut(rows, {ariaLabel: 'Power budget', restIndex: 0,
                                caption: 'total efficiency',
                                tailLabel: 'other channels'});
  wrap.appendChild(donut.el);
  ctx.anchor.insertAdjacentElement('afterend', wrap);
  donut.mount();
}

(window.vizPanels = window.vizPanels || []).push({section: PB_SECTION,
                                                 render: render});
})();
