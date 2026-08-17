// Several runs in one page: the switcher that picks which of them everything
// below is drawn from.
//
// A page normally draws the one dump beside it. Point it at a *manifest*
// instead (`report.html?scan=<file>.js`, see js/dump.js) and it becomes a
// browser over a whole folder of runs -- a parameter scan, or any set of runs
// worth reading one after another under the same axes. The manifest names the
// runs and their dumps; this file is the list that steps between them, and the
// page's own render function is called once per selection.
//
// Nothing here judges a run. A manifest may give each one a `props` list of
// already-scored properties (label, glyph, status, text); js/verdicts.js turns
// those into the strip on a row and the table under the list, and a page
// showing a single run paints the same list from the same place -- so what
// counts as a pass is decided by whoever wrote the list and is never
// re-derived from the data on screen.
(function () {
'use strict';

// The scan's own header: what this set of runs is, over the list of them.
// Text, never markup -- it is written by whatever produced the manifest.
function header(page) {
  if (!page) return;
  if (page.title) {
    document.title = page.title;
    const h1 = document.querySelector('#railtop h1');
    if (h1) h1.textContent = page.title;
  }
  const line = document.getElementById('scanline');
  if (line && page.subtitle) {
    line.textContent = page.subtitle;
    line.style.display = '';
  }
}

// ---- keeping the reader's place across a run switch ---------------------
// The list sits at the top of a tall scrolling side panel, and switching runs
// rebuilds everything below it. Two things would otherwise dump the reader
// back at the top: the rebuild hides its sections first, so the panel briefly
// gets shorter and the browser clamps its scrollTop; and chasing the selected
// row with scrollIntoView pulls the panel back up to the list. Both are
// handled in select() below, so arrowing through runs repaints the panel
// *underneath* whatever plot is being read.

// The nearest scrolling ancestor (on both pages: the side panel).
function scrollBox(el) {
  for (let n = el.parentElement; n; n = n.parentElement) {
    const o = getComputedStyle(n).overflowY;
    if (o === 'auto' || o === 'scroll') return n;
  }
  return document.scrollingElement || document.documentElement;
}

// Nudge `box` just enough to show `row` -- but only if the row is already
// partly on screen (a long list being stepped through). A row scrolled fully
// out of view means the reader is looking at something else further down, and
// is left alone.
function keepRowVisible(box, row) {
  const r = row.getBoundingClientRect(), b = box.getBoundingClientRect();
  if (r.bottom <= b.top || r.top >= b.bottom) return;
  if (r.top < b.top) box.scrollTop += r.top - b.top;
  else if (r.bottom > b.bottom) box.scrollTop += r.bottom - b.bottom;
}

// One clickable row per run: its label, a star on the one the manifest marks
// best, and a compact strip of verdict glyphs. A run that failed greys out and
// carries its error as the row's tooltip -- it still gets a row, because the
// set's story includes the ones that did not finish.
function buildRow(meta, onPick) {
  const row = document.createElement('div');
  row.className = 'run-row' + (meta.error ? ' fail' : '');
  let html = `<span class="rr-label">${vizEsc(meta.label)}` +
      (meta.best ? ' <span class="rr-best" title="best of the set">★</span>'
                 : '') + '</span>';
  if (meta.error) {
    row.title = meta.error;
    html += '<span class="rr-fail">failed</span>';
  } else if (meta.props) {
    html += FDTDVerdicts.strip(meta.props);
  }
  row.innerHTML = html;
  row.addEventListener('click', onPick);
  return row;
}

// The selected run's verdict table: the strip on its row, spelled out. Empty
// for a run that failed or was never scored -- there is nothing to spell out,
// and the row itself already says which.
function detailTable(meta) {
  if (!meta || meta.error || !meta.props) return '';
  return FDTDVerdicts.table(meta.props);
}

// Build the switcher for `runs` into the page's #runswitch block and select
// the first run that has data. `onChange(i)` fires on every change, including
// that first one, and is what draws the page.
function runList(runs, onChange) {
  const block = document.getElementById('runswitch');
  const host = document.getElementById('runlist');
  const detail = document.getElementById('rundetail');
  block.style.display = '';
  let sel = -1;
  const rows = runs.map((run, i) => {
    const row = buildRow(run.meta, () => select(i));
    host.appendChild(row);
    return row;
  });

  function select(i) {
    i = Math.max(0, Math.min(runs.length - 1, i));
    if (i === sel) return;
    const first = sel < 0;
    if (!first) rows[sel].classList.remove('sel');
    sel = i;
    rows[sel].classList.add('sel');
    const box = scrollBox(host);
    const keep = box.scrollTop, tall = block.offsetHeight;
    detail.innerHTML = detailTable(runs[sel].meta);
    onChange(i);
    // Back to where the reader was, plus however much the switcher block grew
    // (a failed run has no verdict table): without that, everything below
    // would slide by that much under a scroll position that did not move. On
    // the first run there is no place to keep -- the panel opens at its top,
    // title and all.
    if (first) return;
    box.scrollTop = keep + (block.offsetHeight - tall);
    keepRowVisible(box, rows[sel]);
  }

  addEventListener('keydown', e => {
    if (/^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)) return;
    if (e.key === 'ArrowLeft') { select(sel - 1); e.preventDefault(); }
    else if (e.key === 'ArrowRight') { select(sel + 1); e.preventDefault(); }
  });
  select(Math.max(0, runs.findIndex(r => !r.meta.error)));
}

window.FDTDRuns = {header, runList};
})();
