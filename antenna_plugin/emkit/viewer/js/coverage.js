
function vizGridCoverage(THREE, ctx) {
  const {entries, group, mid, wid, data} = ctx;
  const layers = data.coverage;
  if (!layers || !layers.length) return;
  const [nx, ny] = data.n;

  // Node line a, index i, in scene units.
  const node = (a, i, n) => i < n ? mid(a, i) - wid(a, i) / 2
                                  : mid(a, n - 1) + wid(a, n - 1) / 2;
  // A bar's width across the axis it does not run along: a fraction of the
  // thinnest cell it touches, so it reads as a line on the node line rather
  // than as another cell.
  const thin = (a, i, n) => 0.22 * Math.min(wid(a, Math.min(i, n - 1)),
                                            wid(a, Math.max(i - 1, 0)));

  // Everything here is FLAT and UNLIT, and both halves of that are decisions.
  //
  // Flat: coverage is a property of the sheet plane, so a rectangle lying in
  // it is the shape of the thing. A box would also cost six times the
  // triangles of a quad for a thickness that means nothing.
  //
  // Unlit (MeshBasicMaterial, not Phong): the colour IS the number here, and a
  // lit surface shades by orientation -- an Ex bar and an Ey bar present
  // different faces to the light, so the same fraction came out two different
  // colours depending on which way the edge ran. Basic renders the fraction
  // and nothing else.
  //
  // polygonOffset, because a foil's sheet quads lie in this exact plane and in
  // this exact colour: without it the two surfaces z-fight and the edges
  // flicker in and out of the copper they are drawn on. Pulling the bars a
  // depth unit forward keeps them geometrically where they belong and visibly
  // on top, which is the whole point of drawing them over the cells.
  const flat = () => new THREE.MeshBasicMaterial({
    color: 0xffffff, transparent: true, opacity: 0.85, depthWrite: false,
    side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -1,
    polygonOffsetUnits: -1
  });

  // One instanced quad per edge, laid on its node line at the foil's own z
  // plane, in the foil's colour dimmed by its fraction: a fully covered edge
  // is exactly the copper's colour, a sliver fades toward the background.
  // Colour rather than length: the fraction says how much of the edge is
  // copper and nothing about where along it, and drawing a short bar would
  // invent the half the number does not carry -- which is exactly the thing a
  // bridge across a clearance is made of.
  function bars(L, color) {
    const n = L.ei.length;
    const zc = node(2, L.sheet, data.n[2]);
    const mesh = new THREE.InstancedMesh(
        new THREE.PlaneGeometry(1, 1), flat(), n);
    const m = new THREE.Matrix4(), pos = new THREE.Vector3();
    const scl = new THREE.Vector3(), rot = new THREE.Quaternion();
    const base = new THREE.Color(color), col = new THREE.Color();
    for (let q = 0; q < n; q++) {
      const i = L.ei[q], j = L.ej[q], a = L.ea[q], f = L.eq[q] / 255;
      const along = a === 0 ? 0 : 1;              // the axis the edge runs on
      const cross = a === 0 ? 1 : 0;
      const ci = a === 0 ? i : j;                 // cell index along it
      const nj = a === 0 ? j : i;                 // node index across it
      const p = [0, 0, zc], s = [0, 0, 1];        // z: a quad has no thickness
      p[along] = mid(along, ci);
      s[along] = wid(along, ci);
      p[cross] = node(cross, nj, cross === 0 ? nx : ny);
      s[cross] = thin(cross, nj, cross === 0 ? nx : ny);
      pos.set(p[0], p[1], p[2]);
      scl.set(s[0], s[1], s[2]);
      m.compose(pos, rot, scl);
      mesh.setMatrixAt(q, m);
      // Floored well above black: the weakest edges still conduct, and an
      // edge that faded all the way out would say "no metal here", which is
      // the one thing the number never means.
      mesh.setColorAt(q, col.copy(base).multiplyScalar(0.3 + 0.7 * f));
    }
    group.add(mesh);
    return mesh;
  }

  for (const L of layers) {
    // The metal group this foil's edges belong to, matched by the label the
    // overlay was built with (`cells` is what marks an entry as one made of
    // cells -- see GridTemplate). Missing only if the foil drew no cell at
    // all, which a foil made entirely of sub-cell copper can manage; then the
    // edges are the only picture of it there is, and get their own row.
    const host = entries.find(e => e.label === L.label && e.cells);
    const color = host ? host.color : vizToken('--s3', '#199e70');
    // Normally the edges join the foil they belong to, because a reader
    // looking at "Metal: CuTop" wants all of that metal in one row. A row of
    // their own -- unticked, built only if asked for -- is for whoever is
    // reading the edges THEMSELVES rather than the board, and it is that
    // reader who says so: window.FDTD_SPLIT_OVERLAYS is set by whatever they
    // loaded (?with=, js/dump.js), never by anything here.
    if (window.FDTD_SPLIT_OVERLAYS) {
      const e = {label: L.label + ' edges (conformal)', color,
                 section: 'sim', count: L.ei.length, objects: [],
                 hidden: true};
      e.build = () => { e.objects = [bars(L, color)]; };
      entries.push(e);
    } else if (host) {
      host.objects.push(bars(L, color));
    } else {
      entries.push({label: L.label + ' (conformal)', color, section: 'sim',
                    count: L.ei.length, objects: [bars(L, color)]});
    }
  }
}
(window.FDTD_OVERLAYS ||= []).push(vizGridCoverage);
