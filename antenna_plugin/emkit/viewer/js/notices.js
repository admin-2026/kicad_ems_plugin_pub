// What the run has to SAY about itself, listed at the foot of the rail.
//
// A grid page is a picture of a lattice, and a picture cannot say "this is not
// the lattice the config asked for". When that is true -- the mesh was
// coarsened to fit a memory budget, say -- it is the most important thing on
// the page, and it has to be there in a month when the console that said it
// once is long gone.
//
// So the dump carries notices (src/report/Notice.hpp) and this paints them as
// a LIST at the foot of the rail, under everything the run drew. One row each:
// a warning sign, the title, and "What this means" -- which opens the figures
// and the explanation whoever wrote the notice attached to it. Nothing here
// knows what any particular notice is about: no mesh, no budget, no cell size.
// A notice is a title, a list of k/v facts and some paragraphs, and every one
// of them is painted the same way, which is what makes the next one free. The
// rows read worst-first.
//
// Everything is TEXT, never innerHTML: a notice is written by the run and may
// carry a board's own layer names or a file path.
(function () {
'use strict';

// The payload section, shared with the C++ that writes it
// (viz::NoticeOverlay::kSection). The one string the two halves have in
// common.
const NOTICE_SECTION = 'notices';

// The sign each level wears, and the class that colours it. `warn` is the
// page's one alarm colour; `info` is a remark, in the ordinary ink.
const LEVELS = {
  warn: {glyph: '⚠', cls: 'ntc-warn'},
  info: {glyph: 'ℹ', cls: 'ntc-info'},
};

// Where a page puts them: its own #notices block, at the foot of the rail. A
// page without one draws none -- better than a banner inserted somewhere this
// module guessed at.
function anchor() {
  return document.getElementById('notices');
}

// Warnings before remarks, and within a level the order the run posted them.
// The run says what happened; which of two things is read first is the page's
// call, and Array.sort is stable, so the run's order survives inside a level.
const RANK = {warn: 0, info: 1};
function ordered(notices) {
  return notices.slice().sort(
      (a, b) => (RANK[a.level] ?? 0) - (RANK[b.level] ?? 0));
}

// One notice as an item of the list: a sign, a title, and the one word that
// opens it. Nothing else is on the page until it is asked for -- the figures
// and the paragraphs alike open under the row, the way the group list's rows
// open their own explanations. So a run with three things to say is three
// lines, and every one of them can be read in full without leaving the page.
function item(notice) {
  const level = LEVELS[notice.level] || LEVELS.warn;
  const box = document.createElement('div');
  // .vizpanel is what a page's render reset takes away (vizRenderReset). The
  // list below is emptied on every render anyway; this covers the render that
  // never reaches this module -- a selected run with no grid data at all, which
  // must not be left wearing the last run's warning.
  box.className = 'vizpanel ntc-item ' + level.cls;

  const row = document.createElement('div');
  row.className = 'ntc-row';
  const sign = document.createElement('span');
  sign.className = 'ntc-sign';
  sign.textContent = level.glyph;
  const title = document.createElement('span');
  title.className = 'ntc-title';
  title.textContent = notice.title || '';
  row.append(sign, title);
  box.appendChild(row);

  // What the disclosure opens: the figures first, as the measurement rows
  // every page states a value in, then the paragraphs. The numbers come first
  // because they are what a reader who already knows the story came back for.
  const facts = notice.facts || [], paras = notice.text || [];
  if (facts.length || paras.length) {
    const rest = document.createElement('div');
    rest.className = 'ntc-more';
    for (const f of facts) {
      const kv = document.createElement('div');
      kv.className = 'kv';
      const k = document.createElement('span');
      k.textContent = f.k;
      const v = document.createElement('b');
      v.textContent = f.v;
      kv.append(k, v);
      rest.appendChild(kv);
    }
    for (const para of paras) {
      const p = document.createElement('p');
      p.textContent = para;
      rest.appendChild(p);
    }
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'ntc-btn';
    button.setAttribute('aria-expanded', 'false');
    // `open` would shadow window.open; the state is the class on the box, so
    // there is nothing else to keep in step with it.
    const label = shown => (shown ? 'Hide the details' : 'What this means');
    button.textContent = label(false);
    button.onclick = () => {
      const shown = rest.classList.toggle('open');
      button.setAttribute('aria-expanded', shown);
      button.textContent = label(shown);
    };
    // On the row itself, ranged right like the counts down the group list, so
    // a list of notices reads as one column of titles and one of controls.
    row.appendChild(button);
    box.appendChild(rest);
  }
  return box;
}

// The page hook. Registered rather than called by name, like every other
// module the pages carry: a copy of the viewer without this file is a page
// that draws no notices, not a broken one.
function vizGridNotices(THREE, ctx) {
  const at = anchor();
  if (!at) return;
  // Emptied first, always: a page stepping through a set of runs must not
  // leave one run's warning standing under another's grid, and a run with
  // nothing to say has to leave the block empty rather than untouched.
  at.textContent = '';
  const notices = (ctx.data && ctx.data[NOTICE_SECTION]) || [];
  for (const notice of ordered(notices)) at.appendChild(item(notice));
}

window.FDTD_OVERLAYS = window.FDTD_OVERLAYS || [];
window.FDTD_OVERLAYS.push(vizGridNotices);
})();
