// The scene, built on the first render and kept: a page browsing a set of runs
// redraws into `content` alone, so the viewpoint the reader set carries from
// one run to the next instead of snapping back with every step.
let SCENE = null, CONTENT = null;

// The legend's sections, in the order they read: what the LAYOUT draws, what
// THIS RUN added to it, and what belongs to the SIMULATION rather than to the
// board. A dump names each group's section by key (GridDump::kBoard and its
// neighbours); the headings and this order are the page's own, so rewording a
// section is a change here and nowhere else.
//
// Sorting the list is all this does -- every group still gets its row, and the
// order inside a section is the order the run added them, which is physical
// (substrate, then the foils top to bottom, then the drills).
const SECTIONS = [
  ['board', 'On the board'],
  ['added', 'Added by this run'],
  ['sim', 'Simulation & checks'],
];
// Where a group with no section of its own goes: an overlay that predates
// them, a key this page does not know. Never dropped -- the last section is
// the page's own furniture (the feed, the absorber, the checks), which is
// where an unplaced group is least likely to be mistaken for the board.
const OTHER_SECTION = 'sim';

function vizGridPage() {
const {THREE, OrbitControls} = window;

if (!SCENE) {
  // Shared three.js scaffolding: renderer, KiCad orbit controls, lights, the
  // z-up group, coordinate axes, and the resize + render loop.
  SCENE = vizScene3d(THREE, OrbitControls, document.getElementById('view3d'));
  CONTENT = new THREE.Group();
  SCENE.group.add(CONTENT);
}
const {camera, renderer} = SCENE;
const group = CONTENT;
vizClearGroup(CONTENT);
vizRenderReset();
document.getElementById('groups').innerHTML = '';

const DATA = window.FDTD.s.grid;
if (!DATA) {
  const meta = window.FDTD.meta;
  return vizRenderEmpty(
      'This run has no grid data' +
      (meta && meta.error ? `:<br>${vizEsc(meta.error)}`
                          : ' (it may have stopped before meshing).'));
}

const [nx, ny, nz] = DATA.n;
const N = [DATA.x, DATA.y, DATA.z];  // node coordinates per axis [m]
const span = N.map(a => a[a.length - 1] - a[0]);
const L = Math.max(...span);
const s = 2.0 / L;
// Scaled center offset per axis; cell centers/sizes come from the nodes,
// so graded (sub-gridded) axes render with their true cell sizes.
const C = N.map(a => 0.5 * (a[0] + a[a.length - 1]) * s);
const mid = (a, i) => 0.5 * (N[a][i] + N[a][i + 1]) * s - C[a];
const wid = (a, i) => (N[a][i + 1] - N[a][i]) * s;

// Domain outline.
{
  const g = new THREE.EdgesGeometry(
      new THREE.BoxGeometry(span[0] * s, span[1] * s, span[2] * s));
  group.add(new THREE.LineSegments(g, new THREE.LineBasicMaterial(
      {color: new THREE.Color(vizToken('--ink-3', '#898781')),
       transparent: true, opacity: 0.35})));
}

// The theme's categorical slots, in their fixed order (vizToken reads them
// off the stylesheet, so this page and the report cannot drift apart).
const PALETTE = [1, 2, 3, 4, 5, 6].map(i => vizToken('--s' + i, '#3987e5'));
let paletteIdx = 0;
const entries = [];  // {label, color, count, objects}

// Transparent instanced cubes for one cell group, scaled per instance to
// each cell's true size. `sheet` (a z node index) marks a zero-thickness
// foil: the metal physically sits on that node plane -- the bottom face
// of the drawn cells -- so a near-opaque quad per cell is added there in
// the same color to pinpoint it inside the translucent boxes. `opacity`
// defaults to what a material group is drawn at; a group that fills a
// volume rather than tracing a feature wants far less of it.
function addCells(cells, color, sheet, opacity = 0.45) {
  const n = cells.length / 3;
  const geo = new THREE.BoxGeometry(1, 1, 1);
  const mat = new THREE.MeshPhongMaterial({
    color, transparent: true, opacity, depthWrite: false
  });
  const mesh = new THREE.InstancedMesh(geo, mat, n);
  const m = new THREE.Matrix4();
  const pos = new THREE.Vector3(), scl = new THREE.Vector3();
  const rot = new THREE.Quaternion();
  for (let q = 0; q < n; q++) {
    const [i, j, k] = [cells[3 * q], cells[3 * q + 1], cells[3 * q + 2]];
    pos.set(mid(0, i), mid(1, j), mid(2, k));
    scl.set(wid(0, i) * 0.92, wid(1, j) * 0.92, wid(2, k) * 0.92);
    m.compose(pos, rot, scl);
    mesh.setMatrixAt(q, m);
  }
  group.add(mesh);
  const objects = [mesh];
  if (sheet !== undefined) {
    const pmat = new THREE.MeshPhongMaterial({
      color, transparent: true, opacity: 0.9, side: THREE.DoubleSide,
      depthWrite: false
    });
    const pmesh = new THREE.InstancedMesh(
        new THREE.PlaneGeometry(1, 1), pmat, n);
    const zc = N[2][sheet] * s - C[2];
    for (let q = 0; q < n; q++) {
      const [i, j] = [cells[3 * q], cells[3 * q + 1]];
      pos.set(mid(0, i), mid(1, j), zc);
      scl.set(wid(0, i) * 0.92, wid(1, j) * 0.92, 1);
      m.compose(pos, rot, scl);
      pmesh.setMatrixAt(q, m);
    }
    group.add(pmesh);
    objects.push(pmesh);
  }
  return objects;
}

// The three adaptive bands are one ordered quantity -- distance from the feed
// in cell-size steps -- so they wear one hue getting darker outward (the
// theme's sequential blue), not three unrelated colours. Everything else that
// is named takes a fixed slot; the rest take the categorical order in turn.
for (const g of DATA.groups) {
  if (!g.cells.length) continue;
  const color = g.label === 'PEC' ? '#d8d8e0'
              // A raster short is a STATUS, not a series -- the copper the
              // model fuses and the drawing does not -- so it takes the
              // theme's warning slot and nothing else ever does.
              : g.label === 'Shorted (raster)'
                  ? vizToken('--warning', '#fab219')
              : g.label === 'Vias' ? PALETTE[3]
              // Pinned off the warning slot next door to it: synthetic copper
              // wants attention, a short wants alarm, and two ambers side by
              // side in the legend say neither.
              : g.label === 'Auto-ground (synthetic)' ? PALETTE[4]
              : g.label === 'Antenna area (adaptive)' ? '#9ec5f4'
              : g.label === 'Transition (adaptive)' ? '#5598e7'
              : g.label === 'Outer (adaptive)' ? '#256abf'
              : PALETTE[paletteIdx++ % PALETTE.length];
  // `cells` rides along (by reference, not copied) to mark the entry as one
  // made of cells and to map an instance back to its index -- the measure tool
  // picks off it; nothing else reads it.
  // A handful of cells on a board of thousands: drawn near-opaque, or the
  // thing the group exists to show is a faint smudge inside the pour it sits
  // in. Everything else keeps the material opacity.
  const opacity = g.label === 'Shorted (raster)' ? 0.95 : 0.45;
  entries.push({label: g.label, color, count: g.cells.length / 3,
                cells: g.cells, note: g.note, props: g.props,
                section: g.section,
                objects: addCells(g.cells, color, g.sheet, opacity)});
}

// Feed: a solid red cube at the driven edge plus a red arrow along the feed
// axis. The single feed cell is tiny at domain scale, so the arrow (sized to
// the domain, centered on the edge) is what makes the location and direction
// legible.
if (DATA.feed) {
  const f = DATA.feed;
  // The feed indices are a cell along the feed axis (the gap cell the edge
  // bridges) but nodes on the other two axes (the edge's own lattice
  // lines): center those on the node coordinate -- treating them as cells
  // would shift the marker half a cell off the driven edge (see
  // docs/finding-feed-cube-viewer-offset.md).
  const fi = [f.i, f.j, f.k];
  const node = (a, i) => N[a][i] * s - C[a];
  const nodeW = (a, i) =>
      Math.min(wid(a, Math.max(0, i - 1)), wid(a, Math.min(i, N[a].length - 2)));
  const ctr = a => a === f.axis ? mid(a, fi[a]) : node(a, fi[a]);
  const ext = a => a === f.axis ? wid(a, fi[a]) : nodeW(a, fi[a]);
  const fp = new THREE.Vector3(ctr(0), ctr(1), ctr(2));
  // Solid opaque cube straddling the driven edge.
  const FEED_COLOR = vizToken('--ax-x', '#e66767');
  const cube = new THREE.Mesh(
      new THREE.BoxGeometry(ext(0), ext(1), ext(2)),
      new THREE.MeshPhongMaterial({color: new THREE.Color(FEED_COLOR)}));
  cube.position.copy(fp);
  group.add(cube);
  // Transparent red arrow: cylinder stem + cone head, centred on the edge,
  // pointing along the feed axis.  Built from explicit meshes so stem
  // thickness, head size, and opacity are all controllable.
  const sgn = f.sign < 0 ? -1 : 1;  // feed direction's sign along the axis
  const dir = new THREE.Vector3(
      f.axis === 0 ? sgn : 0, f.axis === 1 ? sgn : 0, f.axis === 2 ? sgn : 0);
  const arrowMat = new THREE.MeshPhongMaterial({
      color: new THREE.Color(FEED_COLOR), transparent: true, opacity: 0.65,
      depthWrite: false, shininess: 40});
  const q = new THREE.Quaternion().setFromUnitVectors(
      new THREE.Vector3(0, 1, 0), dir);
  const L = 0.25, hh = 0.09, hr = 0.038, sr = 0.015;
  const stemLen = L - hh;
  // Stem centre is offset back by hh/2 so the tip of the cone lands at L/2.
  const stem = new THREE.Mesh(
      new THREE.CylinderGeometry(sr, sr, stemLen, 12), arrowMat);
  stem.position.copy(fp).addScaledVector(dir, -hh / 2);
  stem.quaternion.copy(q);
  group.add(stem);
  const head = new THREE.Mesh(
      new THREE.ConeGeometry(hr, hh, 12), arrowMat);
  head.position.copy(fp).addScaledVector(dir, L / 2 - hh / 2);
  head.quaternion.copy(q);
  group.add(head);
  entries.push({label: 'Feed cell', color: FEED_COLOR, section: 'sim',
                count: '1', objects: [cube]});
  entries.push({label: 'Feed direction', color: FEED_COLOR, section: 'sim',
                count: ['x', 'y', 'z'][f.axis] + ' axis',
                objects: [stem, head]});
}

// CPML region as six non-overlapping translucent slabs.
if (DATA.pml > 0) {
  const t = DATA.pml;
  const slabs = [
    [0, nx, 0, ny, 0, t], [0, nx, 0, ny, nz - t, nz],
    [0, nx, 0, t, t, nz - t], [0, nx, ny - t, ny, t, nz - t],
    [0, t, t, ny - t, t, nz - t], [nx - t, nx, t, ny - t, t, nz - t],
  ];
  const pmlColor = vizToken('--accent', '#3987e5');
  const mat = new THREE.MeshBasicMaterial({
    // Fainter than the old slate blue it replaces: the theme's blue is the
    // more saturated colour, and six slabs of it would tint the whole domain.
    color: new THREE.Color(pmlColor), transparent: true, opacity: 0.055,
    depthWrite: false
  });
  const objects = slabs.map(([i0, i1, j0, j1, k0, k1]) => {
    const box = new THREE.Mesh(new THREE.BoxGeometry(
        (N[0][i1] - N[0][i0]) * s, (N[1][j1] - N[1][j0]) * s,
        (N[2][k1] - N[2][k0]) * s), mat);
    box.position.set(0.5 * (N[0][i0] + N[0][i1]) * s - C[0],
                     0.5 * (N[1][j0] + N[1][j1]) * s - C[1],
                     0.5 * (N[2][k0] + N[2][k1]) * s - C[2]);
    group.add(box);
    return box;
  });
  entries.push({label: 'CPML region', color: pmlColor, section: 'sim',
                count: `${t} cells`, objects});
}

// Anything spliced into this page beyond the template itself: a build's
// debugging tools, an overlay drawing a payload section of its own. Each
// fragment pushes one function onto window.FDTD_OVERLAYS as it loads, and
// this is the one place the page calls them -- so adding an overlay is adding
// a fragment, never another guarded call site here, and a page that carries
// none iterates an empty list. It runs before the panel below so an overlay's
// groups get their checkbox like any other.
for (const fn of (window.FDTD_OVERLAYS || []))
  fn(THREE, {camera, renderer, group, entries, N, mid, wid,
             data: DATA, addCells});

// Checkbox panel. Beyond label/color/count/objects, an entry may carry:
//   hidden   start unticked -- for a group that would bury the board if it
//            came up shown
//   build()  make its objects, called once, the first time it is ticked, so
//            a group nobody asks for costs the page nothing
//   section  which part of the list it belongs to (SECTIONS above)
//   note     what the group means: a "?" on the row opening the text under
//            it (GridDump::addCellGroup). Any overlay can set one too
//   props    what it is made of: an "i" on the row opening a property list,
//            [{k, v}, ...], both halves preformatted by whoever wrote them
const list = document.getElementById('groups');

// One disclosure at the end of a row: a button, and the box it opens directly
// under that row. Both buttons on a row are this -- the reason and the
// material are the same gesture -- and `fill` is the only difference between
// them.
function disclosure(row, glyph, title, fill) {
  const box = document.createElement('div');
  box.className = 'rowbox';
  fill(box);
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'rowbtn';
  button.textContent = glyph;
  button.title = title;
  button.setAttribute('aria-expanded', 'false');
  button.onclick = ev => {
    // The row is a <label>, so a click anywhere in it toggles the group's
    // checkbox. Asking about a group must not switch it off.
    ev.preventDefault();
    ev.stopPropagation();
    button.setAttribute('aria-expanded', box.classList.toggle('open'));
  };
  row.append(button);
  list.appendChild(box);
}

function addRow(e) {
  const row = document.createElement('label');
  row.className = 'togglerow';
  const cb = document.createElement('input');
  cb.type = 'checkbox';
  cb.checked = !e.hidden;
  if (e.hidden) e.objects.forEach(o => o.visible = false);
  cb.onchange = () => {
    if (cb.checked && e.build) { e.build(); e.build = null; }
    e.objects.forEach(o => o.visible = cb.checked);
  };
  const sw = document.createElement('span');
  sw.className = 'swatch';
  sw.style.background = e.color;
  const name = document.createElement('span');
  name.textContent = e.label;
  // The count rides right, in the mono face: down a list of groups the
  // figures line up in a column instead of trailing each label.
  const n = document.createElement('span');
  n.className = 'n';
  n.textContent = e.count;
  row.append(cb, sw, name, n);
  list.appendChild(row);
  // Everything below is TEXT, never innerHTML: it is written by the run, and
  // a board's layer name or material could otherwise reach the page as markup.
  if (e.props && e.props.length)
    disclosure(row, 'i', 'What this group is made of', box => {
      for (const p of e.props) {
        const kv = document.createElement('div');
        kv.className = 'kv';
        const k = document.createElement('span');
        k.textContent = p.k;
        const v = document.createElement('b');
        v.textContent = p.v;
        kv.append(k, v);
        box.appendChild(kv);
      }
    });
  if (e.note)
    disclosure(row, '?', 'What this group means', box => {
      for (const para of e.note.split('\n\n')) {
        const p = document.createElement('p');
        p.textContent = para;
        box.appendChild(p);
      }
    });
}

// Sorted into the sections above, each under its heading. A dump whose groups
// name no section at all -- one written before there were any -- keeps the
// flat list it was made for rather than being filed under headings that would
// be guesses. That question is asked of the DUMP's groups and not of the
// entries: the feed and the absorber below are this page's own and always know
// where they go, so they would answer it for every dump ever written.
const known = new Set(SECTIONS.map(([key]) => key));
if (!DATA.groups.some(g => known.has(g.section))) {
  entries.forEach(e => addRow(e));
} else {
  for (const [key, heading] of SECTIONS) {
    const rows = entries.filter(
        e => (known.has(e.section) ? e.section : OTHER_SECTION) === key);
    if (!rows.length) continue;
    const h = document.createElement('div');
    h.className = 'grpsec';
    h.textContent = heading;
    list.appendChild(h);
    rows.forEach(e => addRow(e));
  }
}

const sizes = a => {
  let lo = Infinity, hi = 0;
  for (let i = 0; i + 1 < N[a].length; i++) {
    const w = N[a][i + 1] - N[a][i];
    lo = Math.min(lo, w); hi = Math.max(hi, w);
  }
  return hi - lo < 1e-4 * hi ? `${(hi * 1e3).toFixed(2)}`
      : `${(lo * 1e3).toFixed(3)}&ndash;${(hi * 1e3).toFixed(2)}`;
};
// The mesh in three figures, as stat tiles (vizCard): what it spans, what it
// resolves, and how much of it is boundary.
document.getElementById('summary').innerHTML =
    vizCard(`${nx}&times;${ny}&times;${nz}`, '', 'Domain (cells)') +
    vizCard(`${sizes(0)} &times; ${sizes(1)} &times; ${sizes(2)}`, 'mm',
            'Cell size') +
    vizCard(DATA.pml, 'cells', 'CPML on every face');
}

FDTDViewer.boot({
  data: ['pcb_grid.js', 'filter_grid.js', 'grid.js'],
  debug: {dir: 'js/debug', when: 'grid.debug'},
  main: vizGridPage,
});
