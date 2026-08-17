// Panels the page reveals only when the run carries what they show. A render
// starts by putting every one of them back out of sight, so a run without a
// polarization ellipse or a copper stack can never inherit the previous one's.
const OPTIONAL = ['icbar', 'icbarmax', 'icbarmin', 'icbartitle',
                  'jcbar', 'jcbarmax', 'jcbarmin', 'jcbartitle',
                  'polsec', 'isec', 'layersec', 'patColorRow', 'verdicts'];
// The directivity scale. Unlike the panels above it belongs to every report,
// so it is not optional -- but it reads in dBi off one particular pattern, and
// a run with no pattern must not be left wearing the last one's numbers.
const PATTERN_BAR = ['colorbar', 'cbmax', 'cbmin', 'cbtitle'];

// The scene, built on the first render and kept: a page browsing a set of runs
// redraws into `content` alone, so the viewpoint the reader set carries from
// one run to the next instead of snapping back with every step.
let SCENE = null, CONTENT = null;

function vizReportPage() {
const {THREE, OrbitControls} = window;

if (!SCENE) {
  SCENE = vizScene3d(THREE, OrbitControls, document.getElementById('view3d'));
  CONTENT = new THREE.Group();
  SCENE.group.add(CONTENT);
}
const group = CONTENT;
vizClearGroup(CONTENT);
vizRenderReset();
for (const id of OPTIONAL) document.getElementById(id).style.display = 'none';
for (const id of PATTERN_BAR) document.getElementById(id).style.display = '';
document.getElementById('layerToggles').innerHTML = '';
document.getElementById('runline').innerHTML = '';

const S = window.FDTD.s;
// Without a pattern there is no report to draw -- a run of a set that failed,
// or one stopped before its first far-field transform.
if (!S.pattern) {
  const meta = window.FDTD.meta;
  for (const id of PATTERN_BAR) document.getElementById(id).style.display = 'none';
  return vizRenderEmpty(
      'This run has no results' +
      (meta && meta.error ? `:<br>${vizEsc(meta.error)}`
                          : ' (it may have stopped before solving).'));
}
const DATA = {
  pattern: S.pattern,
  // No stand-in for a missing reference impedance: a dump with no geometry
  // section recorded none, and undefined is what says so. A number here would
  // be a reference nobody measured against (see vizSmith, which refuses one).
  zref: S.geometry ? S.geometry.zref : undefined,
  wires: S.geometry && S.geometry.wires ? S.geometry.wires : [],
  board: S.geometry ? S.geometry.board : null,
  wireCurrent: S.current || null,
  metrics: S.metrics || {},
  impedance: S.impedance || {f: [], R: [], X: [], S11: [], VSWR: []},
  run: S.run || null,
};
const DB_RANGE = 30;

// ---------- 3D view (everything this run draws goes into `group`) ----------
// Radiation pattern surface.
const {nTheta, nPhi, dbi, dMax} = DATA.pattern;
const dMin = dMax - DB_RANGE;
// Polarization sense colormap: diverging red (RHCP) - gray (linear) -
// blue (LHCP), saturating at +-POL_RANGE dB circular ratio.
const POL_RANGE = 20;
const POL_RH = new THREE.Color('#e66767');
const POL_MID = new THREE.Color('#9a9a94');
const POL_LH = new THREE.Color('#3987e5');
const polColor = (circDb, out) => {
  const t = Math.min(1, Math.max(-1, circDb / POL_RANGE));
  return out.copy(POL_MID).lerp(t > 0 ? POL_RH : POL_LH, Math.abs(t));
};
const pos = [], col = [], colPol = [], idx = [];
const c = new THREE.Color();
const circ = DATA.pattern.circ;
for (let i = 0; i < nTheta; i++) {
  const th = Math.PI * i / (nTheta - 1);
  for (let j = 0; j < nPhi; j++) {
    const ph = 2 * Math.PI * j / nPhi;
    const t = Math.min(1, Math.max(0, (dbi[i * nPhi + j] - dMin) / DB_RANGE));
    const r = 0.03 + 0.97 * t;
    pos.push(r * Math.sin(th) * Math.cos(ph),
             r * Math.sin(th) * Math.sin(ph),
             r * Math.cos(th));
    c.setHSL(0.7 * (1 - t), 1.0, 0.5);
    col.push(c.r, c.g, c.b);
    if (circ) {
      polColor(circ[i * nPhi + j], c);
      colPol.push(c.r, c.g, c.b);
    }
  }
}
for (let i = 0; i < nTheta - 1; i++) {
  for (let j = 0; j < nPhi; j++) {
    const j2 = (j + 1) % nPhi;
    const a = i * nPhi + j, b = (i + 1) * nPhi + j;
    const d = i * nPhi + j2, e = (i + 1) * nPhi + j2;
    idx.push(a, b, d, d, b, e);
  }
}
const geo = new THREE.BufferGeometry();
geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
const colDirAttr = new THREE.Float32BufferAttribute(col, 3);
const colPolAttr = circ ? new THREE.Float32BufferAttribute(colPol, 3) : null;
geo.setAttribute('color', colDirAttr);
geo.setIndex(idx);
geo.computeVertexNormals();
const patternMesh = new THREE.Mesh(geo, new THREE.MeshPhongMaterial({
  vertexColors: true, side: THREE.DoubleSide,
  transparent: true, opacity: 0.92, shininess: 30
}));
group.add(patternMesh);

// Pattern visibility toggle. Sync to the checkbox on load too, since a
// browser may restore an unchecked box across reloads while the mesh
// defaults to visible.
const patToggleEl = document.getElementById('patToggle');
const applyPatternVis = () => {
  patternMesh.visible = patToggleEl.checked;
  const vis = patToggleEl.checked ? '' : 'hidden';
  for (const id of ['colorbar','cbmax','cbmin','cbtitle'])
    document.getElementById(id).style.visibility = vis;
};
patToggleEl.onchange = applyPatternVis;
applyPatternVis();

// Antenna geometry, scaled so its largest extent reaches 0.7 scene units.
let ext = 0;
for (const w of DATA.wires) {
  for (const v of [w.x0, w.y0, w.z0, w.x1, w.y1, w.z1])
    ext = Math.max(ext, Math.abs(v));
}
if (DATA.board) {
  for (const v of [DATA.board.x0, DATA.board.y0, DATA.board.x1,
                   DATA.board.y1, DATA.board.z0, DATA.board.z1])
    ext = Math.max(ext, Math.abs(v));
}
const s = ext > 0 ? 0.7 / ext : 1;
const wireMat = new THREE.MeshPhongMaterial({color: 0xdddddd, shininess: 80});
for (const w of DATA.wires) {
  const p0 = new THREE.Vector3(w.x0 * s, w.y0 * s, w.z0 * s);
  const p1 = new THREE.Vector3(w.x1 * s, w.y1 * s, w.z1 * s);
  const dir = p1.clone().sub(p0);
  const rad = Math.max(w.r * s, 0.01);
  const cyl = new THREE.Mesh(
      new THREE.CylinderGeometry(rad, rad, dir.length(), 16), wireMat);
  cyl.position.copy(p0).add(p1).multiplyScalar(0.5);
  cyl.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0),
                                    dir.normalize());
  group.add(cyl);
}

// Wire current overlay: one fatter cylinder per sampled segment, colored
// by normalized |I| with the pattern's hue ramp.
if (DATA.wireCurrent) {
  const wc = DATA.wireCurrent;
  let rad = 0.01;
  for (const w of DATA.wires) rad = Math.max(rad, w.r * s);
  rad *= 1.6;
  for (let q = 0; q < wc.mag.length; q++) {
    const mat = new THREE.MeshPhongMaterial({shininess: 30});
    mat.color.setHSL(0.7 * (1 - wc.mag[q]), 1.0, 0.5);
    const p0 = new THREE.Vector3(wc.segs[6*q] * s, wc.segs[6*q+1] * s,
                                 wc.segs[6*q+2] * s);
    const p1 = new THREE.Vector3(wc.segs[6*q+3] * s, wc.segs[6*q+4] * s,
                                 wc.segs[6*q+5] * s);
    const dir = p1.clone().sub(p0);
    const cyl = new THREE.Mesh(
        new THREE.CylinderGeometry(rad, rad, dir.length(), 12), mat);
    cyl.position.copy(p0).add(p1).multiplyScalar(0.5);
    cyl.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0),
                                      dir.normalize());
    group.add(cyl);
  }
  // Wire current colorbar
  const stops = [];
  for (let k = 0; k <= 10; k++) {
    const t = 1 - k / 10;  // 1 = peak, 0 = zero
    stops.push(`hsl(${252 * (1 - t)},100%,50%) ${k * 10}%`);
  }
  document.getElementById('icbar').style.display = '';
  document.getElementById('icbar').style.background =
      `linear-gradient(${stops.join(',')})`;
  document.getElementById('icbarmax').style.display = '';
  document.getElementById('icbarmax').textContent = '100%';
  document.getElementById('icbarmin').style.display = '';
  document.getElementById('icbarmin').textContent = '0%';
  document.getElementById('icbartitle').style.display = '';
}

// PCB board (orientation aid): a translucent FR-4 substrate slab with each
// copper layer represented by its |Js| surface-current pattern at its true
// height, at the same scale as the antenna model. The stack is thin relative
// to the board, so the layers render nearly coincident (true to scale).
// Slab, heatmaps, layer/substrate toggles and the |Js| colorbar come from
// the shared vizBoard3d.
if (DATA.board) vizBoard3d(THREE, group, DATA.board, s, DB_RANGE);

// Colorbar: HSL ramp for directivity, the diverging sense map for
// polarization; swapped together with the surface colors.
function setPatternColor(mode) {
  const cb = document.getElementById('colorbar');
  if (mode === 'pol' && colPolAttr) {
    geo.setAttribute('color', colPolAttr);
    cb.style.background =
        `linear-gradient(${POL_RH.getStyle()},${POL_MID.getStyle()},` +
        `${POL_LH.getStyle()})`;
    document.getElementById('cbmax').textContent = 'RHCP';
    document.getElementById('cbmin').textContent = 'LHCP';
    document.getElementById('cbtitle').textContent =
        'Polarization sense (gray = linear)';
  } else {
    geo.setAttribute('color', colDirAttr);
    const stops = [];
    for (let k = 0; k <= 10; k++) {
      const t = 1 - k / 10;
      stops.push(`hsl(${252 * (1 - t)},100%,50%) ${k * 10}%`);
    }
    cb.style.background = `linear-gradient(${stops.join(',')})`;
    document.getElementById('cbmax').textContent = dMax.toFixed(1) + ' dBi';
    document.getElementById('cbmin').textContent =
        (dMax - DB_RANGE).toFixed(1) + ' dBi';
    document.getElementById('cbtitle').textContent = 'Directivity';
  }
}
setPatternColor('dir');
if (colPolAttr) {
  document.getElementById('patColorRow').style.display = 'flex';
  for (const r of document.querySelectorAll('input[name="patColor"]'))
    r.onchange = () => setPatternColor(r.value);
}

// ---------- 2D plots (vizPlot from the shared library) ----------
// The impedance, return-loss and VSWR panels are three views of the same
// sweep, so they share one cursor (opts.link): hovering any of them reads
// all three out at that frequency at once.
const imp = DATA.impedance;
if (imp.f.length) {
  const zMag = imp.R.map((r, i) => Math.hypot(r, imp.X[i]));
  // Series wear the theme's categorical slots in their fixed order (VIZ_SERIES,
  // ReportCommon): three-series panel takes slots 1-3, a lone series takes
  // slot 1 -- its identity comes from the panel's own heading, not its hue.
  vizPlot('zplot', imp.f,
          [{ys: imp.R, color: VIZ_SERIES[0], label: 'R [Ω]'},
           {ys: imp.X, color: VIZ_SERIES[1], label: 'X [Ω]'},
           {ys: zMag, color: VIZ_SERIES[2], label: '|Z| [Ω]'}],
          {xlabel: 'f [GHz]', link: 'f'});
  // What the reflection was measured against, spelled for a label. The two
  // non-numeric cases are the same two vizSmith refuses to draw for, and the
  // curve is still plotted in both -- the solver computed it (against an
  // infinite reference it is 0 dB everywhere, which is the honest answer), so
  // what this has to get right is not claiming a reference that is not there.
  const zrefLabel = DATA.zref > 0 ? `${DATA.zref} Ω`
                  : DATA.zref === null ? 'an ideal source'
                                       : 'an unrecorded reference';
  vizPlot('splot', imp.f,
          [{ys: imp.S11, color: VIZ_SERIES[0],
            label: `|S11| vs ${zrefLabel} [dB]`}],
          {xlabel: 'f [GHz]', link: 'f'});
  if (imp.VSWR && imp.VSWR.length)
    vizPlot('vswr', imp.f,
            [{ys: imp.VSWR, color: VIZ_SERIES[0], label: 'VSWR'}],
            {xlabel: 'f [GHz]', link: 'f'});
  // The same sweep as a locus (vizSmith, js/smith.js), in the same cursor
  // group: it reads the impedance series as it stands, so its |S11| and VSWR
  // read-outs are the plotted numbers rather than a second derivation.
  vizSmith('smith', imp, {zref: DATA.zref, markF: DATA.pattern.freqGHz,
                          link: 'f', readout: 'smithout'});
}

// Antenna metrics
{
  const m = DATA.metrics;
  // One gain, the one everyone quotes: IEEE gain, D * eta_rad, per unit
  // power accepted at the port. Realized gain (the same figure per unit
  // *offered* power) is deliberately not shown beside it -- two numbers
  // both called gain, 0.15 dB apart, cost more in confusion than the second
  // one is worth. It is one line of arithmetic off the budget below:
  // realized = gain + 10 log10(1 - reflected).
  // Every figure is a row: name on the left, value ranged right in the mono
  // face, so the column reads as a table of one measurement per line rather
  // than a paragraph of bolded labels.
  const row = (k, v) => `<div class="kv"><span>${k}</span><b>${v}</b></div>`;
  let html = row('Gain', `${m.gain.toFixed(2)} dBi`) +
             row('F/B ratio', `${m.fbRatio.toFixed(1)} dB`);
  if (m.pol) {
    const p = m.pol;
    const sense = p.arDb > 20
        ? `Linear (${p.coIsTheta ? '&theta;' : '&phi;'}, tilt ${p.tiltDeg.toFixed(0)}&deg;)`
        : p.arDb < 3
        ? (p.circDb > 0 ? 'RHCP' : 'LHCP')
        : `${p.circDb > 0 ? 'Right' : 'Left'}-hand elliptical, ` +
          `tilt ${p.tiltDeg.toFixed(0)}&deg;`;
    html += row('Polarization', `${sense} at ` +
                `(&theta;=${p.theta.toFixed(0)}&deg;, &phi;=${p.phi.toFixed(0)}&deg;)`) +
            row('Axial ratio',
                `${p.arDb >= 60 ? '&ge;60' : p.arDb.toFixed(1)} dB`) +
            row(`Cross-pol (${p.coIsTheta ? '&phi;' : '&theta;'})`,
                `${p.xpolDb >= 60 ? '&ge;60' : p.xpolDb.toFixed(1)} dB ` +
                'below co-pol');
  }
  if (m.bwSpan) {
    html += row('Bandwidth (-10 dB)',
                `${(m.bwF2 - m.bwF1).toFixed(0)} MHz ` +
                `(${m.bwSpan.toFixed(1)}% @ ${m.bwFc.toFixed(0)} MHz)`);
  }
  // Figures of merit contributed by other modules (HtmlReport::addMetric).
  // An entry naming a section joins that section's block, under one heading
  // and in the order added; an entry without one stays a plain row. Each
  // carries its own label and preformatted text, so nothing here knows what
  // any of them mean -- no section is named or seeded here.
  const sections = new Map();
  for (const x of m.extra || []) {
    if (!x.section) { html += row(x.label, x.text); continue; }
    if (!sections.has(x.section)) sections.set(x.section, []);
    sections.get(x.section).push(x);
  }
  // Optional visual panels this build carries (viz::reportPanelJs, spliced
  // above this script and registered on window.vizPanels). A panel that
  // names a section *owns* it: it draws those rows itself, so they drop out
  // of the text list below -- which is how a module can replace its rows
  // with a chart without the page knowing one exists.
  const panels = window.vizPanels || [];
  const claimed = new Set(panels.map(p => p.section).filter(Boolean));
  for (const [name, rows] of sections) {
    if (claimed.has(name) || !rows.length) continue;
    html += `<div class="kv-sec">${name}</div>`;
    for (const r of rows) html += row(r.label, r.text);
  }
  const metricsEl = document.getElementById('metrics');
  metricsEl.innerHTML = html;
  // Each panel builds its own DOM around the metrics block it sits with; it
  // gets its own section's rows ready-grouped, so it never walks the dump.
  for (const p of panels)
    p.render({data: DATA, metrics: m, anchor: metricsEl,
              rows: sections.get(p.section) || []});
}

// Principal-plane polar plots: E-plane (phi=0) and H-plane (theta=90)
if (DATA.metrics.ePlane && DATA.metrics.ePlane.length > 0) {
  const cv = document.getElementById('planes');
  const dpr = devicePixelRatio, W = cv.clientWidth * dpr, H = cv.clientHeight * dpr;
  cv.width = W; cv.height = H;
  const ctx = cv.getContext('2d');

  // Side-by-side polar plots: E-plane on left, H-plane on right.
  // `cross` (optional) is the cross-pol cut, dashed, on the same scale.
  const cw = W / 2, ch = H;
  const drawPolar = (xOff, angles, vals, title, cross) => {
    const cx = xOff + cw / 2, cy = ch / 2;
    const maxVal = Math.max(...vals);
    const scale = Math.min(cw, ch) / 2 * 0.4;

    // Polar grid: concentric circles and radial lines
    ctx.strokeStyle = VIZ_GRID; ctx.lineWidth = dpr;
    for (let r = 1; r <= 3; r++) {
      ctx.beginPath();
      ctx.arc(cx, cy, scale * r / 3, 0, 2 * Math.PI);
      ctx.stroke();
    }
    for (let a = 0; a < 360; a += 30) {
      const rad = a * Math.PI / 180;
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(cx + scale * Math.cos(rad), cy - scale * Math.sin(rad));
      ctx.stroke();
    }

    // A directivity curve over a 30 dB range below maxVal; the pen lifts
    // where the curve drops off scale.
    const drawCurve = ys => {
      ctx.beginPath();
      let pen = false;
      for (let i = 0; i < angles.length; i++) {
        const a = angles[i] * Math.PI / 180;
        const r = scale * (ys[i] - (maxVal - 30)) / 30;
        if (r < 0) { pen = false; continue; }
        const x = cx + r * Math.cos(a), y = cy - r * Math.sin(a);
        if (pen) ctx.lineTo(x, y); else ctx.moveTo(x, y);
        pen = true;
      }
      ctx.stroke();
    };
    ctx.strokeStyle = VIZ_SERIES[0]; ctx.lineWidth = 2 * dpr;
    drawCurve(vals);
    if (cross && cross.length === angles.length) {
      ctx.strokeStyle = VIZ_SERIES[1]; ctx.lineWidth = 1.5 * dpr;
      ctx.setLineDash([4 * dpr, 4 * dpr]);
      drawCurve(cross);
      ctx.setLineDash([]);
    }

    // Title
    ctx.fillStyle = VIZ_INK2; ctx.font = `${10.5 * dpr}px ${VIZ_MONO}`;
    ctx.textAlign = 'center';
    ctx.fillText(title, xOff + cw / 2, 14 * dpr);
  };

  const pol = DATA.metrics.pol;
  if (DATA.metrics.ePlane) {
    const angles = Array.from({length: DATA.metrics.ePlane.length},
                               (_, i) => i * 180 / (DATA.metrics.ePlane.length - 1));
    drawPolar(0, angles, DATA.metrics.ePlane, 'E-plane (φ=0°)',
              pol && pol.ePlaneX);
  }
  if (DATA.metrics.hPlane) {
    const angles = Array.from({length: DATA.metrics.hPlane.length},
                               (_, i) => i * 360 / DATA.metrics.hPlane.length);
    drawPolar(cw, angles, DATA.metrics.hPlane, 'H-plane (θ=90°)',
              pol && pol.hPlaneX);
  }
  if (pol) {
    ctx.fillStyle = VIZ_INK3; ctx.font = `${10 * dpr}px ${VIZ_MONO}`;
    ctx.textAlign = 'center';
    ctx.fillText('solid: total · dashed: cross-pol '
                 + (pol.coIsTheta ? '(φ)' : '(θ)'), W / 2, H - 6 * dpr);
  }
}

// Polarization ellipse at the beam peak: axes are theta-hat (right) and
// phi-hat (up), major axis normalized; shape = axial ratio, orientation
// = tilt, arrow = rotation sense.
if (DATA.metrics.pol) {
  document.getElementById('polsec').style.display = '';
  const p = DATA.metrics.pol;
  const cv = document.getElementById('polplot');
  const dpr = devicePixelRatio;
  const W = cv.clientWidth * dpr, H = cv.clientHeight * dpr;
  cv.width = W; cv.height = H;
  const ctx = cv.getContext('2d');
  const cx = W / 2, cy = H / 2;
  const scale = Math.min(W, H) / 2 * 0.78;

  // Axes.
  ctx.strokeStyle = VIZ_GRID; ctx.lineWidth = dpr;
  ctx.beginPath();
  ctx.moveTo(cx - scale * 1.15, cy); ctx.lineTo(cx + scale * 1.15, cy);
  ctx.moveTo(cx, cy - scale * 1.15); ctx.lineTo(cx, cy + scale * 1.15);
  ctx.stroke();
  ctx.fillStyle = VIZ_INK3; ctx.font = `${11 * dpr}px ${VIZ_MONO}`;
  ctx.textAlign = 'left';
  ctx.fillText('θ', cx + scale * 1.15 - 8 * dpr, cy + 14 * dpr);
  ctx.fillText('φ', cx + 6 * dpr, cy - scale * 1.15 + 10 * dpr);

  // Ellipse: semi-major 1, semi-minor 1/AR, rotated by the tilt.
  // ell(psi) traces counterclockwise (theta-hat toward phi-hat), the
  // right-hand sense; canvas y points down, hence cy - y.
  const b = Math.pow(10, -p.arDb / 20);
  const tau = p.tiltDeg * Math.PI / 180;
  const ell = psi => {
    const x = Math.cos(psi) * Math.cos(tau) - b * Math.sin(psi) * Math.sin(tau);
    const y = Math.cos(psi) * Math.sin(tau) + b * Math.sin(psi) * Math.cos(tau);
    return [cx + scale * x, cy - scale * y];
  };
  ctx.strokeStyle = VIZ_SERIES[0]; ctx.lineWidth = 2 * dpr;
  ctx.beginPath();
  for (let n = 0; n <= 180; n++) {
    const [x, y] = ell(n * Math.PI / 90);
    if (n === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // Rotation-sense arrowheads (meaningless for a linear state).
  if (p.arDb < 20) {
    const dir = p.circDb > 0 ? 1 : -1;
    ctx.fillStyle = VIZ_SERIES[0];
    for (const psi0 of [0.35 * Math.PI, 1.35 * Math.PI]) {
      const [x0, y0] = ell(psi0);
      const [x1, y1] = ell(psi0 + dir * 0.02);
      const a = Math.atan2(y1 - y0, x1 - x0), s = 7 * dpr;
      ctx.beginPath();
      ctx.moveTo(x1 + s * Math.cos(a), y1 + s * Math.sin(a));
      ctx.lineTo(x1 + s * Math.cos(a + 2.6), y1 + s * Math.sin(a + 2.6));
      ctx.lineTo(x1 + s * Math.cos(a - 2.6), y1 + s * Math.sin(a - 2.6));
      ctx.fill();
    }
  }

  // Caption.
  ctx.fillStyle = VIZ_INK3; ctx.font = `${10 * dpr}px ${VIZ_MONO}`;
  ctx.textAlign = 'center';
  const sense = p.arDb > 20 ? 'linear'
              : (p.circDb > 0 ? 'right-hand' : 'left-hand') +
                (p.arDb < 3 ? ' circular' : ' elliptical');
  ctx.fillText(`${sense} · AR ${p.arDb >= 60 ? '≥60' : p.arDb.toFixed(1)} dB · ` +
               `tilt ${p.tiltDeg.toFixed(0)}° · ` +
               `at (θ=${p.theta.toFixed(0)}°, φ=${p.phi.toFixed(0)}°)`,
               W / 2, H - 6 * dpr);
}

if (DATA.wireCurrent) {
  document.getElementById('isec').style.display = '';
  vizPlot('iplot', DATA.wireCurrent.pos,
          [{ys: DATA.wireCurrent.mag.map(v => 100 * v), color: VIZ_SERIES[0],
            label: '|I| [% of max]'}],
          {xlabel: 'position [mm]'});
}

// ---------- summary ----------
// The four numbers a reader opens the page for, as stat tiles (vizCard) --
// the one place on the page where the figures are the layout rather than
// sentences carrying them.
const cards = [vizCard(DATA.pattern.freqGHz.toFixed(2), 'GHz',
                       'Pattern frequency'),
               vizCard(dMax.toFixed(2), 'dBi', 'Peak directivity')];
if (imp.f.length) {
  let bi = 0;
  imp.S11.forEach((v, i) => { if (v < imp.S11[bi]) bi = i; });
  cards.push(vizCard(imp.S11[bi].toFixed(1), 'dB', 'Best match'),
             vizCard(imp.f[bi].toFixed(2), 'GHz', 'Best match at frequency'));
}
document.getElementById('summary').innerHTML = cards.join('');
// How much simulated time these results cover, and how far the ports had
// rung down when they were read (vizRunLine, shared with the filter report).
if (DATA.run)
  document.getElementById('runline').innerHTML = vizRunLine(DATA.run);

// ---------- how it measured up ----------
// The verdicts come with the run, already scored (js/verdicts.js says why they
// are never worked out here): from the sidecar beside a single run's dump, or
// from the manifest entry of one run of a set. A set is the exception -- the
// switcher is already showing the selected run's verdicts beside its row, and
// the same table twice on one page would only make the reader check whether
// they agree.
const meta = window.FDTD.meta;
if (!window.FDTD.scan && meta && meta.props && meta.props.length) {
  document.getElementById('verdicts').style.display = '';
  // The target itself is the run's own text (an application's name and the
  // spec it implies), so it goes in escaped rather than as markup; the glyph
  // beside it is the worst of the verdicts below.
  document.getElementById('verdictline').innerHTML =
      FDTDVerdicts.overall(meta) + ' ' + vizEsc(meta.target || '');
  document.getElementById('verdicttable').innerHTML =
      FDTDVerdicts.table(meta.props);
}

// ---------- group labels ----------
// Each .grp label heads the run of panels between it and the next label, so
// it is only meaningful while something in that run is on screen: a wire
// report hides the copper layers, a PCB report the wire current, and either
// would leave an empty heading behind. Done here, after every panel above has
// settled its own visibility, and by walking the DOM rather than by naming
// sections -- a panel added later joins a group by position alone.
for (const g of document.querySelectorAll('#side .grp')) {
  let shown = false;
  for (let el = g.nextElementSibling; el && !el.classList.contains('grp');
       el = el.nextElementSibling)
    if (el.style.display !== 'none') shown = true;
  g.style.display = shown ? '' : 'none';
}

// Pattern size slider. Assigned, not added: a page stepping through a set of
// runs renders more than once, and a listener added each time would leave the
// previous run's mesh being scaled by this run's slider.
const patScaleEl = document.getElementById('patScale');
patScaleEl.oninput = function() {
  const v = parseFloat(this.value);
  patternMesh.scale.setScalar(v);
  document.getElementById('patScaleVal').textContent = v.toFixed(2) + '\xd7';
};
patternMesh.scale.setScalar(parseFloat(patScaleEl.value));
}

FDTDViewer.boot({
  data: ['pcb_data.js', 'report.js'],
  meta: 'run_verdicts.js',
  main: vizReportPage,
});
