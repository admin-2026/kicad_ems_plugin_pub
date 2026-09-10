function vizScene3d(THREE, OrbitControls, view, axisLen = 1.4) {
  const renderer = new THREE.WebGLRenderer({antialias: true});
  renderer.setPixelRatio(devicePixelRatio);
  view.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(vizToken('--bg', '#0d0d0c'));
  const camera = new THREE.PerspectiveCamera(50, 1, 0.01, 100);
  camera.position.set(2.0, 1.4, 2.0);
  const controls = new OrbitControls(camera, renderer.domElement);
  // KiCad-style: left-drag orbits, middle (wheel) drag pans, wheel scroll zooms.
  controls.screenSpacePanning = true;
  controls.mouseButtons.MIDDLE = THREE.MOUSE.PAN;
  scene.add(new THREE.AmbientLight(0xffffff, 0.55));
  const dl = new THREE.DirectionalLight(0xffffff, 1.1);
  dl.position.set(2, 3, 1);
  scene.add(dl);

  // Physics coordinates are right-handed with z up; rotate the group so the
  // physics z-axis points up on screen (three.js y).
  const group = new THREE.Group();
  group.rotation.x = -Math.PI / 2;
  scene.add(group);

  // Coordinate axes (physics frame), in the theme's axis triad -- the same
  // three tokens the legend under the view wears, so the line and its letter
  // cannot end up different reds.
  for (const [x, y, z, tok, fb] of [[axisLen, 0, 0, '--ax-x', '#e66767'],
                                    [0, axisLen, 0, '--ax-y', '#199e70'],
                                    [0, 0, axisLen, '--ax-z', '#3987e5']]) {
    const g = new THREE.BufferGeometry().setFromPoints(
        [new THREE.Vector3(0, 0, 0), new THREE.Vector3(x, y, z)]);
    group.add(new THREE.Line(g, new THREE.LineBasicMaterial(
        {color: new THREE.Color(vizToken(tok, fb))})));
  }

  const resize = () => {
    const w = view.clientWidth, h = view.clientHeight;
    renderer.setSize(w, h);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  };
  addEventListener('resize', resize);
  resize();
  renderer.setAnimationLoop(() => { controls.update(); renderer.render(scene, camera); });
  return {scene, camera, renderer, controls, group};
}

function vizBoard3d(THREE, group, b, s, dbRange) {
  const bw = (b.x1 - b.x0) * s, bh = (b.y1 - b.y0) * s;
  const th = Math.max((b.z1 - b.z0) * s, 1e-4);
  const sub = new THREE.Mesh(
      new THREE.BoxGeometry(bw, bh, th),
      new THREE.MeshPhongMaterial({color: 0x1f6f3a, transparent: true,
          opacity: 0.5, side: THREE.DoubleSide, shininess: 12}));
  sub.position.set(0.5 * (b.x0 + b.x1) * s, 0.5 * (b.y0 + b.y1) * s,
                   0.5 * (b.z0 + b.z1) * s);
  // The slab is the native (unrotated) rectangle; spin it about its own centre
  // (the board z-axis) by the whole-board rotation so it overlays the rotated
  // copper. The |Js| cells arrive already in the rotated frame, so only the
  // slab is turned here.
  sub.rotation.z = (b.rot || 0) * Math.PI / 180;
  group.add(sub);
  // Substrate visibility toggle (synced on load: a browser may restore an
  // unchecked box across reloads while the mesh defaults to visible).
  const subToggleEl = document.getElementById('subToggle');
  if (subToggleEl) {
    const applySubVis = () => { sub.visible = subToggleEl.checked; };
    subToggleEl.onchange = applySubVis;
    applySubVis();
  }
  const off = 0.002 * Math.max(bw, bh) + 1e-4;  // lift off the slab faces
  // Per-layer |Js| pattern handles (null where a layer has no cells); each
  // layer is represented by its surface-current pattern, toggled below.
  const heatMeshes = b.layers.map(() => null);
  const layerEnabled = b.layers.map(() => true);

  // |Js| heatmap: opaque per-cell colors floating just off each layer
  // (away from the board center, so outer layers stay visible from
  // outside). Magnitudes arrive normalized to the all-layer peak; the
  // color maps their dB value over the same dB range as the pattern.
  const zMid = 0.5 * (b.z0 + b.z1);
  b.layers.forEach((layer, li) => {
    const cur = layer.cur || [], n = cur.length / 5;
    if (n === 0) return;
    const mesh = new THREE.InstancedMesh(
        new THREE.PlaneGeometry(1, 1),
        new THREE.MeshBasicMaterial({side: THREE.DoubleSide}), n);
    const m = new THREE.Matrix4(), p = new THREE.Vector3();
    const q = new THREE.Quaternion(), sc = new THREE.Vector3();
    const col = new THREE.Color();
    const zc = layer.z * s + (layer.z >= zMid ? 2 : -2) * off;
    for (let i = 0; i < n; i++) {
      const x0 = cur[5*i], y0 = cur[5*i+1], x1 = cur[5*i+2], y1 = cur[5*i+3];
      p.set(0.5*(x0+x1)*s, 0.5*(y0+y1)*s, zc);
      sc.set(Math.max((x1-x0)*s, 1e-4), Math.max((y1-y0)*s, 1e-4), 1);
      m.compose(p, q, sc);
      mesh.setMatrixAt(i, m);
      const db = 20 * Math.log10(Math.max(cur[5*i+4], 1e-6));
      const t = Math.min(1, Math.max(0, 1 + db / dbRange));
      col.setHSL(0.7 * (1 - t), 1.0, 0.5);
      mesh.setColorAt(i, col);
    }
    heatMeshes[li] = mesh;
    group.add(mesh);
  });
  const hasHeat = heatMeshes.some(o => o);

  // Enabled layer -> its |Js| pattern is shown.
  const applyLayerVis = () => {
    b.layers.forEach((layer, li) => {
      if (heatMeshes[li]) heatMeshes[li].visible = layerEnabled[li];
    });
  };

  // Per-layer on/off checkboxes, labeled by copper-layer name.
  const togglesEl = document.getElementById('layerToggles');
  if (togglesEl) {
    document.getElementById('layersec').style.display = '';
    b.layers.forEach((layer, li) => {
      if (!heatMeshes[li]) return;
      const lab = document.createElement('label');
      lab.className = 'togglerow';
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = true;
      cb.onchange = () => { layerEnabled[li] = cb.checked; applyLayerVis(); };
      const txt = document.createElement('span');
      txt.textContent = layer.name || ('Layer ' + (li + 1));
      lab.append(cb, txt);
      togglesEl.appendChild(lab);
    });
  }

  if (hasHeat && document.getElementById('jcbar')) {
    // Sheet current colorbar (same dB range as the heat colors)
    const stops = [];
    for (let k = 0; k <= 10; k++) {
      const t = 1 - k / 10;
      stops.push(`hsl(${252 * (1 - t)},100%,50%) ${k * 10}%`);
    }
    document.getElementById('jcbar').style.display = '';
    document.getElementById('jcbar').style.background =
        `linear-gradient(${stops.join(',')})`;
    document.getElementById('jcbarmax').style.display = '';
    document.getElementById('jcbarmax').textContent = 'peak';
    document.getElementById('jcbarmin').style.display = '';
    document.getElementById('jcbarmin').textContent = `-${dbRange}dB`;
    document.getElementById('jcbartitle').style.display = '';
  }
}
