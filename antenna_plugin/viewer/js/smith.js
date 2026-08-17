// ---------- Smith chart (vizSmith) ----------
// Sequential blue ramp, dark -> light for the dark surface: low frequency is
// the dark end. Sequential, not categorical: the locus is one series and the
// colour carries where along the sweep a point sits.
const vizSmithRamp =
    ['#184f95', '#256abf', '#3987e5', '#6da7ec', '#9ec5f4', '#cde2fb'];
function vizRampAt(ramp, t) {
  const u = Math.min(1, Math.max(0, t)) * (ramp.length - 1);
  const k = Math.min(ramp.length - 2, Math.floor(u)), q = u - k;
  const ch = (h, i) => parseInt(h.substr(1 + 2 * i, 2), 16);
  const m = i => Math.round(ch(ramp[k], i) +
                            (ch(ramp[k + 1], i) - ch(ramp[k], i)) * q);
  return `rgb(${m(0)},${m(1)},${m(2)})`;
}
// A chart that will not be drawn, said out loud. Neither half of this is
// optional: the canvas would otherwise be an empty box that looks like a
// styling bug, and the console line is what a developer handed a bad dump
// actually reads.
function vizSmithRefuse(id, cv, out, why) {
  console.warn('vizSmith(%s): %s', id, why);
  const dpr = devicePixelRatio;
  const W = cv.clientWidth * dpr, H = cv.clientHeight * dpr;
  cv.width = W; cv.height = H;
  const ctx = cv.getContext('2d');
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = VIZ_INK3;
  ctx.font = `${12 * dpr}px ${VIZ_MONO}`;
  ctx.textAlign = 'center';
  ctx.fillText('no Smith chart', W / 2, H / 2);
  // The sentence goes in the read-out, which is a DOM element and so can wrap;
  // canvas text cannot, and this panel is ~390 px wide.
  if (out) out.textContent = why;
}
function vizSmith(id, imp, opts = {}) {
  const cv = document.getElementById(id);
  if (!cv || !imp || !imp.f || imp.f.length < 2) return;
  const out = opts.readout ? document.getElementById(opts.readout) : null;

  // The reference impedance is required and is never guessed. Every point on
  // a Smith chart is a reflection coefficient measured against it, so a chart
  // drawn against a reference nobody chose is wrong in a way that still looks
  // entirely plausible -- 75 Ohm data on a 50 Ohm chart is a picture of a
  // mismatch that is not there. That is the one failure worth refusing over,
  // so a missing reference is reported rather than defaulted.
  //
  // null is the dump's spelling for "no finite reference exists": the legacy
  // ideal source (`port_resistance: inf`), against which every impedance
  // reflects completely. A locus for one is a picture of the reference rather
  // than of the load -- every sample on the rim, whatever the load did -- so
  // that too is said in words instead of drawn.
  const z0 = opts.zref;
  if (z0 === null)
    return vizSmithRefuse(
        id, cv, out,
        'This run drove an ideal source (port_resistance: inf), which has no ' +
        'finite reference impedance: every impedance reflects off it ' +
        'completely, so there is no match to plot.');
  if (!Number.isFinite(z0) || z0 <= 0)
    return vizSmithRefuse(
        id, cv, out,
        'No reference impedance was recorded for this run, and one is not ' +
        'assumed: without it there is nothing to measure a reflection ' +
        'against.');

  const dpr = devicePixelRatio;
  const W = cv.clientWidth * dpr, H = cv.clientHeight * dpr;
  cv.width = W; cv.height = H;
  const ctx = cv.getContext('2d');
  const f = imp.f, n = f.length;

  // Gamma = (z - 1)/(z + 1) with z = (R + jX)/z0, once per sample.
  const gx = new Array(n), gy = new Array(n);
  for (let i = 0; i < n; i++) {
    const r = imp.R[i] / z0, x = imp.X[i] / z0;
    const den = (r + 1) * (r + 1) + x * x;
    gx[i] = (r * r - 1 + x * x) / den;
    gy[i] = 2 * x / den;
  }
  const BAND = 26 * dpr;   // the frequency strip along the bottom
  const PAD = 20 * dpr;    // room outside the rim for the reactance labels
  const cx = W / 2, cy = (H - BAND) / 2;
  const rad = Math.min(W, H - BAND) / 2 - PAD;
  const PX = i => cx + rad * gx[i], PY = i => cy - rad * gy[i];
  const onChart = i => gx[i] * gx[i] + gy[i] * gy[i] <= 1.0001;
  const font = px => `${px * dpr}px ${VIZ_MONO}`;
  const ohm = v => Math.abs(v) >= 100 ? v.toFixed(0) : v.toPrecision(3);

  // Constant-resistance circles, constant-reactance arcs, the VSWR wash and
  // the axis labels -- everything that does not depend on the data.
  function chrome() {
    ctx.lineWidth = dpr;
    ctx.save();
    ctx.beginPath(); ctx.arc(cx, cy, rad, 0, 2 * Math.PI); ctx.clip();
    ctx.strokeStyle = VIZ_LINE;
    for (const r of [0.2, 0.5, 2, 5]) {
      ctx.beginPath();
      ctx.arc(cx + rad * r / (1 + r), cy, rad / (1 + r), 0, 2 * Math.PI);
      ctx.stroke();
    }
    for (const x of [0.2, 0.5, 1, 2, 5])
      for (const sg of [1, -1]) {
        ctx.beginPath();
        ctx.arc(cx + rad, cy - sg * rad / x, rad / x, 0, 2 * Math.PI);
        ctx.stroke();
      }
    // The two curves the eye anchors on: r = 1 (through the centre, the
    // matched resistance) and x = 0 (the real axis).
    ctx.strokeStyle = VIZ_LINE2;
    ctx.beginPath(); ctx.arc(cx + rad / 2, cy, rad / 2, 0, 2 * Math.PI);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(cx - rad, cy); ctx.lineTo(cx + rad, cy); ctx.stroke();
    ctx.restore();

    // VSWR <= 2 is |Gamma| <= 1/3: the one region worth marking, as a wash.
    // A touch lighter than the frequency-band wash on the plots -- it sits on
    // the densest part of the grid, where the fainter value disappeared.
    ctx.fillStyle = 'rgba(255,255,255,0.10)';
    ctx.beginPath(); ctx.arc(cx, cy, rad / 3, 0, 2 * Math.PI); ctx.fill();
    ctx.strokeStyle = VIZ_LINE2;
    ctx.beginPath(); ctx.arc(cx, cy, rad, 0, 2 * Math.PI); ctx.stroke();

    // Normalized resistance along the real axis; reactance out on the rim,
    // where z = jx lands (Gamma = (jx - 1)/(jx + 1)).
    ctx.fillStyle = VIZ_INK3; ctx.font = font(9.5);
    ctx.textAlign = 'center';
    for (const r of [0.2, 0.5, 1, 2, 5])
      ctx.fillText(String(r), cx + rad * (r - 1) / (r + 1), cy + 12 * dpr);
    ctx.textAlign = 'left';
    ctx.fillText('0', cx - rad + 3 * dpr, cy - 5 * dpr);
    ctx.textAlign = 'right';
    ctx.fillText('∞', cx + rad - 3 * dpr, cy - 5 * dpr);
    ctx.textAlign = 'center';
    for (const x of [0.5, 1, 2])
      for (const sg of [1, -1]) {
        const den = 1 + x * x, rr = rad + 11 * dpr;
        ctx.fillText((sg > 0 ? 'j' : '−j') + x,
                     cx + rr * (x * x - 1) / den,
                     cy - rr * sg * 2 * x / den + 3.5 * dpr);
      }
  }

  // The frequency key for the locus colour.
  function strip() {
    const bw = 0.44 * W, bx = (W - bw) / 2, by = H - 14 * dpr, bh = 5 * dpr;
    const g = ctx.createLinearGradient(bx, 0, bx + bw, 0);
    vizSmithRamp.forEach(
        (c, i) => g.addColorStop(i / (vizSmithRamp.length - 1), c));
    ctx.fillStyle = g;
    ctx.fillRect(bx, by, bw, bh);
    ctx.fillStyle = VIZ_INK3; ctx.font = font(10);
    ctx.textAlign = 'right';
    ctx.fillText(vizFmt(f[0]), bx - 6 * dpr, by + bh);
    ctx.textAlign = 'left';
    ctx.fillText(vizFmt(f[n - 1]) + ' GHz', bx + bw + 6 * dpr, by + bh);
  }

  // The locus, clipped to the chart: a sample outside |Gamma| = 1 is not a
  // place on a Smith chart (a short record can put one there), so it is left
  // off rather than drawn across the page. The read-out still reports it.
  function locus() {
    ctx.save();
    ctx.beginPath(); ctx.arc(cx, cy, rad, 0, 2 * Math.PI); ctx.clip();
    ctx.lineWidth = 2 * dpr; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
    for (let i = 1; i < n; i++) {
      ctx.strokeStyle = vizRampAt(vizSmithRamp, (i - 0.5) / (n - 1));
      ctx.beginPath();
      ctx.moveTo(PX(i - 1), PY(i - 1));
      ctx.lineTo(PX(i), PY(i));
      ctx.stroke();
    }
    ctx.restore();
  }

  // A marker carries a 2px ring in the surface colour, so it stays legible
  // where it sits on the locus it marks.
  function dot(i, solid) {
    if (!onChart(i)) return;
    ctx.beginPath();
    ctx.arc(PX(i), PY(i), (solid ? 5 : 4.5) * dpr, 0, 2 * Math.PI);
    ctx.lineWidth = 2 * dpr;
    if (solid) {
      ctx.fillStyle = VIZ_INK; ctx.fill();
      ctx.strokeStyle = VIZ_PLOT;
    } else {
      ctx.strokeStyle = VIZ_INK;
    }
    ctx.stroke();
  }

  const markIdx = (opts.markF >= f[0] && opts.markF <= f[n - 1])
      ? vizNearest(f, opts.markF) : null;

  // The read-out: one line of text, not a floating tooltip -- in a column
  // this narrow a box would cover the chart it describes. It rests on the
  // marked frequency, so nothing here is gated behind a hover.
  function say(i) {
    if (!out) return;
    if (i === null) { out.textContent = '—'; return; }
    const g = Math.hypot(gx[i], gy[i]);
    const s11 = imp.S11 ? imp.S11[i] : 20 * Math.log10(Math.max(g, 1e-12));
    const vswr = imp.VSWR ? imp.VSWR[i] : (1 + g) / Math.max(1e-12, 1 - g);
    out.textContent =
        `${vizFmt(f[i])} GHz · Z = ${ohm(imp.R[i])} ` +
        `${imp.X[i] < 0 ? '−' : '+'} j${ohm(Math.abs(imp.X[i]))} Ω` +
        ` · |Γ| ${g.toFixed(3)} · VSWR ${vswr.toFixed(2)}` +
        ` · |S11| ${s11.toFixed(1)} dB`;
  }

  function render(hover) {
    ctx.clearRect(0, 0, W, H);
    chrome();
    locus();
    if (markIdx !== null) {
      dot(markIdx, false);
      if (onChart(markIdx)) {
        // Direct label on the one marked point, flipped to whichever side of
        // the marker has room for it and set on a patch of the surface: the
        // grid is dense here and a label may land anywhere on it, so the
        // label carries its own background rather than an outline.
        const left = PX(markIdx) > cx;
        const txt = vizFmt(f[markIdx]) + ' GHz';
        const tx = PX(markIdx) + (left ? -9 : 9) * dpr;
        const ty = PY(markIdx) - 7 * dpr;
        ctx.font = font(10);
        const tw = ctx.measureText(txt).width;
        ctx.fillStyle = 'rgba(16,16,16,0.82)';
        ctx.fillRect(left ? tx - tw - 4 * dpr : tx - 4 * dpr, ty - 11 * dpr,
                     tw + 8 * dpr, 15 * dpr);
        ctx.fillStyle = VIZ_INK2;
        ctx.textAlign = left ? 'right' : 'left';
        ctx.fillText(txt, tx, ty);
      }
    }
    if (hover !== null) dot(hover, true);
    strip();
    say(hover === null ? markIdx : hover);
  }

  // Cursor group member: an f the sweep does not cover just falls back to
  // rest, exactly as a linked vizPlot does.
  const showAt = x => render(
      x === null || x < f[0] || x > f[n - 1] ? null : vizNearest(f, x));
  const linked = vizLinkRegister(opts.link, id, showAt);
  const moveTo = x => {
    if (linked) for (const fn of linked.values()) fn(x);
    else showAt(x);
  };

  // Hovering the chart drives the same group. The locus is a curve, not a
  // column, so the pointer only has to be *nearest* a sample rather than on
  // it -- within a finger's width, else the cursor clears.
  cv.onpointermove = e => {
    const rect = cv.getBoundingClientRect();
    const mx = (e.clientX - rect.left) * dpr;
    const my = (e.clientY - rect.top) * dpr;
    const reach = 34 * dpr;
    let best = null, bd = reach * reach;
    for (let i = 0; i < n; i++) {
      if (!onChart(i)) continue;
      const dx = PX(i) - mx, dy = PY(i) - my, d = dx * dx + dy * dy;
      if (d < bd) { bd = d; best = i; }
    }
    moveTo(best === null ? null : f[best]);
  };
  cv.onpointerleave = () => moveTo(null);
  render(null);
}
