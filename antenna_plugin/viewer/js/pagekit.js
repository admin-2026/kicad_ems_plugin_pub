// The one way anything that is not CSS -- canvas text, three.js materials --
// gets at the theme's tokens (the :root block above). Looked up on each call,
// so it can never race the stylesheet.
function vizToken(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name);
  return v.trim() || fallback;
}
// One stat tile of the shared .metrics grid: the figure, an optional unit
// riding small beside it, and the label under it. Every page builds its
// headline numbers out of these, so a tile reads the same on all of them.
function vizCard(value, unit, label) {
  return `<div class="card"><div class="v">${value}` +
         (unit ? `<small>${unit}</small>` : '') +
         `</div><div class="l">${label}</div></div>`;
}
// Text that came from a run -- a candidate's label, a solver's error -- on its
// way into an innerHTML string. Nothing here composes markup from a payload
// without it.
function vizEsc(t) {
  return String(t).replace(/[&<>]/g, c => ({'&': '&amp;', '<': '&lt;',
                                            '>': '&gt;'}[c]));
}
// Remove and dispose every child of a three.js group. A page draws one run at
// a time into one such group (see vizRender below), so stepping through a
// folder of runs never leaks geometries or materials on the GPU.
function vizClearGroup(group) {
  for (let i = group.children.length - 1; i >= 0; i--) {
    const o = group.children[i];
    o.traverse(n => {
      if (n.geometry) n.geometry.dispose();
      if (n.material)
        (Array.isArray(n.material) ? n.material : [n.material])
            .forEach(m => m.dispose());
    });
    group.remove(o);
  }
}
// The state every render starts from. A page's panels live in #panels and its
// headline figures in #summary; both are put back on show, any DOM a metric
// panel mounted last time (.vizpanel) is taken away, and the note under the
// summary is cleared. Only a page drawing several runs in turn ever sees a
// second call, but the first one costs nothing.
function vizRenderReset() {
  const panels = document.getElementById('panels');
  if (panels) panels.style.display = '';
  const summary = document.getElementById('summary');
  if (summary) summary.style.display = '';
  const msg = document.getElementById('summarymsg');
  if (msg) msg.innerHTML = '';
  for (const el of document.querySelectorAll('.vizpanel')) el.remove();
}
// What a page shows instead of panels when the selected run carries nothing to
// draw -- a scan candidate whose solve failed, say. Saying so is the point:
// leaving the previous run's charts standing under a new label would be a lie
// about which geometry they belong to.
function vizRenderEmpty(message) {
  const panels = document.getElementById('panels');
  if (panels) panels.style.display = 'none';
  const summary = document.getElementById('summary');
  if (summary) { summary.innerHTML = ''; summary.style.display = 'none'; }
  const msg = document.getElementById('summarymsg');
  if (msg) msg.innerHTML = `<span class="muted">${message}</span>`;
}
