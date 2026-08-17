// The theme's tokens, resolved once for the canvas code (which cannot use
// var()): read through vizToken, so these are the theme's values and not a
// second copy of them.
const VIZ_MONO = vizToken('--font-mono', 'monospace');
const VIZ_INK = vizToken('--ink', '#f0f0f0');
const VIZ_INK2 = vizToken('--ink-2', '#c3c2b7');
const VIZ_INK3 = vizToken('--ink-3', '#898781');
const VIZ_LINE = vizToken('--line', '#2c2c2a');
const VIZ_LINE2 = vizToken('--line-2', '#383835');
const VIZ_GRID = vizToken('--grid', 'rgba(255,255,255,.07)');
const VIZ_PLOT = vizToken('--plot', '#101010');
const VIZ_SERIES = [1, 2, 3, 4, 5, 6].map(i => vizToken('--s' + i, '#3987e5'));
function vizTicks(a, b, n) {
  const raw = (b - a) / n;
  const p = Math.pow(10, Math.floor(Math.log10(raw)));
  let step = 10 * p;
  for (const m of [1, 2, 2.5, 5, 10]) if (raw <= m * p) { step = m * p; break; }
  const t = [];
  for (let v = Math.ceil(a / step) * step; v <= b + 1e-12; v += step) t.push(v);
  return t;
}
function vizFmt(v) {
  if (v === 0) return '0';
  const a = Math.abs(v);
  if (a >= 1e5) return v.toExponential(1);
  const s = a >= 100 ? v.toFixed(0) : v.toPrecision(3);
  return s.indexOf('.') < 0 ? s : s.replace(/0+$/, '').replace(/\.$/, '');
}
// One-line summary of the "run" series (RunSeries.hpp): how much simulated
// time the results cover, the ring-down level reached, and -- highlighted --
// whether the record is partial (a mid-run sample or an interrupted solve).
function vizRunLine(r) {
  let s = `Simulated: <b class="num">${r.timeNs.toFixed(2)} ns</b>` +
          ` of ${r.plannedTimeNs.toFixed(2)} ns` +
          ` (${r.steps} / ${r.plannedSteps} steps)`;
  if (r.ringDownDb !== null && r.ringDownDb !== undefined)
    s += ` &middot; ring-down <b class="num">${r.ringDownDb.toFixed(1)} dB</b>`;
  if (r.partial)
    s += ` &middot; <b class="warn">${r.sample > 0
              ? 'live sample #' + r.sample + ', run still going'
              : 'interrupted'}</b>`;
  return s;
}
// Nearest index of x in the ascending array xs (binary search).
function vizNearest(xs, x) {
  let lo = 0, hi = xs.length - 1;
  if (x <= xs[0]) return 0;
  if (x >= xs[hi]) return hi;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (xs[mid] < x) lo = mid; else hi = mid;
  }
  return (x - xs[lo] < xs[hi] - x) ? lo : hi;
}
// Linked cursors. Plots built with the same opts.link key share one x
// cursor: hovering any of them draws the crosshair, the per-series
// markers and the tooltip on every plot in the group at that same x --
// each snapped to its own sample grid, so the plots need not share an
// x array, only its meaning (e.g. all the frequency-domain panels of a
// report). A member whose x range does not cover the cursor just
// clears. Keyed by canvas id, so re-plotting an id (resize, reload)
// replaces its entry instead of leaving a stale canvas in the group.
const vizLinkGroups = new Map();
function vizLinkRegister(key, id, showAt) {
  if (!key) return null;
  let g = vizLinkGroups.get(key);
  if (!g) { g = new Map(); vizLinkGroups.set(key, g); }
  g.set(id, showAt);
  return g;
}
function vizPlot(id, xs, series, opts = {}) {
  const cv = document.getElementById(id);
  const dpr = devicePixelRatio;
  const W = cv.clientWidth * dpr, H = cv.clientHeight * dpr;
  cv.width = W; cv.height = H;
  const ctx = cv.getContext('2d');
  const fontN = `${10.5 * dpr}px ${VIZ_MONO}`;
  const fontB = `500 ${10.5 * dpr}px ${VIZ_MONO}`;
  ctx.font = fontN;
  let y0 = opts.ymin ?? Infinity, y1 = opts.ymax ?? -Infinity;
  for (const sr of series)
    for (const v of sr.ys) {
      if (opts.ymin === undefined) y0 = Math.min(y0, v);
      if (opts.ymax === undefined) y1 = Math.max(y1, v);
    }
  if (opts.yfloor !== undefined) y0 = Math.max(y0, opts.yfloor);
  const pad = 0.08 * (y1 - y0) + 1e-12;
  if (opts.ymin === undefined) y0 -= pad;
  if (opts.ymax === undefined) y1 += pad;
  const xmin = xs[0], xmax = xs[xs.length - 1];
  const ml = (opts.ylabel ? 62 : 50) * dpr, mr = 8 * dpr;
  const mt = 8 * dpr, mb = 30 * dpr;
  const X = x => ml + (x - xmin) / (xmax - xmin) * (W - ml - mr);
  const Y = y => H - mb - (y - y0) / (y1 - y0) * (H - mt - mb);
  // The x-axis unit, pulled out of "f [GHz]"-style labels for the tooltip.
  const unitM = opts.xlabel && opts.xlabel.match(/\[(.*)\]/);
  const unit = unitM ? unitM[1] : '';

  function render(hoverIdx) {
    ctx.clearRect(0, 0, W, H);
    if (opts.band) {
      const b0 = X(Math.max(opts.band[0], xmin));
      const b1 = X(Math.min(opts.band[1], xmax));
      ctx.fillStyle = 'rgba(255,255,255,0.055)';
      ctx.fillRect(b0, mt, b1 - b0, H - mt - mb);
    }
    ctx.strokeStyle = VIZ_GRID; ctx.fillStyle = VIZ_INK3; ctx.lineWidth = dpr;
    ctx.font = fontN;
    for (const x of vizTicks(xmin, xmax, 6)) {
      ctx.beginPath(); ctx.moveTo(X(x), mt); ctx.lineTo(X(x), H - mb); ctx.stroke();
      ctx.textAlign = 'center';
      ctx.fillText(vizFmt(x), X(x), H - mb + 14 * dpr);
    }
    for (const y of vizTicks(y0, y1, 5)) {
      ctx.beginPath(); ctx.moveTo(ml, Y(y)); ctx.lineTo(W - mr, Y(y)); ctx.stroke();
      ctx.textAlign = 'right';
      ctx.fillText(vizFmt(y), ml - 5 * dpr, Y(y) + 4 * dpr);
    }
    for (const sr of series) {
      ctx.strokeStyle = sr.color; ctx.lineWidth = 1.6 * dpr;
      ctx.setLineDash(sr.dash ? [5 * dpr, 4 * dpr] : []);
      ctx.beginPath();
      xs.forEach((x, i) => {
        const y = Math.min(Math.max(sr.ys[i], y0), y1);
        i ? ctx.lineTo(X(x), Y(y)) : ctx.moveTo(X(x), Y(y));
      });
      ctx.stroke();
    }
    ctx.setLineDash([]);
    let lx = ml + 8 * dpr;
    ctx.textAlign = 'left';
    for (const sr of series) {
      ctx.strokeStyle = sr.color; ctx.lineWidth = 2.5 * dpr;
      if (sr.dash) ctx.setLineDash([4 * dpr, 3 * dpr]);
      ctx.beginPath();
      ctx.moveTo(lx, mt + 10 * dpr); ctx.lineTo(lx + 14 * dpr, mt + 10 * dpr);
      ctx.stroke(); ctx.setLineDash([]);
      ctx.fillStyle = VIZ_INK2;
      ctx.fillText(sr.label, lx + 18 * dpr, mt + 14 * dpr);
      lx += 18 * dpr + ctx.measureText(sr.label).width + 14 * dpr;
    }
    ctx.fillStyle = VIZ_INK3;
    if (opts.xlabel) {
      ctx.textAlign = 'center';
      ctx.fillText(opts.xlabel, ml + (W - ml - mr) / 2, H - 6 * dpr);
    }
    if (opts.ylabel) {
      ctx.save(); ctx.translate(12 * dpr, mt + (H - mt - mb) / 2);
      ctx.rotate(-Math.PI / 2); ctx.textAlign = 'center';
      ctx.fillText(opts.ylabel, 0, 0); ctx.restore();
    }
    if (hoverIdx === null || hoverIdx === undefined) return;

    // Crosshair, snapped to the nearest sampled x.
    const hx = X(xs[hoverIdx]);
    ctx.strokeStyle = 'rgba(255,255,255,.26)'; ctx.lineWidth = dpr;
    ctx.setLineDash([3 * dpr, 3 * dpr]);
    ctx.beginPath(); ctx.moveTo(hx, mt); ctx.lineTo(hx, H - mb); ctx.stroke();
    ctx.setLineDash([]);

    // A marker on each series at the snapped point.
    for (const sr of series) {
      const y = Math.min(Math.max(sr.ys[hoverIdx], y0), y1);
      ctx.beginPath();
      ctx.arc(hx, Y(y), 3 * dpr, 0, 2 * Math.PI);
      ctx.fillStyle = sr.color; ctx.fill();
      ctx.strokeStyle = VIZ_PLOT; ctx.lineWidth = 2 * dpr; ctx.stroke();
    }

    // Tooltip: x value first, then every series' value at that x, key'd by
    // a short stroke of its color; values lead (bright/bold), labels
    // follow (muted) since the reader already has the series in view.
    const lineH = 15 * dpr, padX = 8 * dpr, padY = 7 * dpr;
    const header = vizFmt(xs[hoverIdx]) + (unit ? ' ' + unit : '');
    ctx.font = fontB;
    let boxW = ctx.measureText(header).width;
    ctx.font = fontN;
    for (const sr of series) {
      const w = 18 * dpr + ctx.measureText(sr.label).width + 10 * dpr +
                (() => { ctx.font = fontB;
                         const vw = ctx.measureText(vizFmt(sr.ys[hoverIdx])).width;
                         ctx.font = fontN; return vw; })();
      boxW = Math.max(boxW, w);
    }
    boxW += 2 * padX;
    const boxH = padY * 2 + lineH * (1 + series.length);
    let bx = hx + 10 * dpr;
    if (bx + boxW > W - mr) bx = hx - 10 * dpr - boxW;
    bx = Math.max(ml, Math.min(bx, W - mr - boxW));
    const by = mt + 4 * dpr;

    ctx.fillStyle = 'rgba(13,13,12,.95)';
    ctx.strokeStyle = VIZ_LINE; ctx.lineWidth = dpr;
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(bx, by, boxW, boxH, 5 * dpr);
    else ctx.rect(bx, by, boxW, boxH);
    ctx.fill(); ctx.stroke();

    ctx.textAlign = 'left';
    ctx.font = fontB; ctx.fillStyle = VIZ_INK;
    ctx.fillText(header, bx + padX, by + padY + lineH - 4 * dpr);
    series.forEach((sr, k) => {
      const ly = by + padY + lineH * (k + 2) - 4 * dpr;
      ctx.strokeStyle = sr.color; ctx.lineWidth = 2.5 * dpr;
      ctx.beginPath();
      ctx.moveTo(bx + padX, ly - 4 * dpr);
      ctx.lineTo(bx + padX + 14 * dpr, ly - 4 * dpr);
      ctx.stroke();
      ctx.font = fontN; ctx.fillStyle = VIZ_INK3; ctx.textAlign = 'left';
      ctx.fillText(sr.label, bx + padX + 18 * dpr, ly);
      ctx.font = fontB; ctx.fillStyle = VIZ_INK; ctx.textAlign = 'right';
      ctx.fillText(vizFmt(sr.ys[hoverIdx]), bx + boxW - padX, ly);
    });
  }
  // Put the cursor at data x (null clears it) -- also what the link group
  // calls on its members, hence the range test: a linked plot ignores an
  // x it does not cover rather than pinning the cursor to an end sample.
  const showAt = x =>
      render(x === null || x < xmin || x > xmax ? null : vizNearest(xs, x));
  const linked = vizLinkRegister(opts.link, id, showAt);
  const moveTo = x => {
    if (linked) for (const fn of linked.values()) fn(x);
    else showAt(x);
  };
  showAt(null);

  cv.onpointermove = e => {
    const rect = cv.getBoundingClientRect();
    const mx = (e.clientX - rect.left) * dpr;
    if (mx < ml || mx > W - mr) { moveTo(null); return; }
    moveTo(xmin + (mx - ml) / (W - ml - mr) * (xmax - xmin));
  };
  cv.onpointerleave = () => moveTo(null);
}
