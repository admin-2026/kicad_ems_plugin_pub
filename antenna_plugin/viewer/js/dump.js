// How a page finds the run -- or the runs -- it is drawing, and the developer
// tools that may or may not have been copied beside it.
//
// The viewer is checked in once and copied into a run's output directory
// (`make view OUT=...`), so a page is never generated for a particular dump:
// it looks for one. Everything here is a classic <script> injected at runtime,
// which is a subresource load rather than a fetch, so it works from a plain
// file:// path with no server and no CORS -- the same reason the solver writes
// its dump as a `window.FDTD = {s: ...}` assignment instead of as JSON.
//
// Two ways in, and the address bar picks between them:
//
//   report.html                 the dump beside the page (or ?d=<file>)
//   report.html?scan=<file>.js  a MANIFEST naming several runs, each with its
//                               own dump -- a parameter scan, or any set of
//                               runs read one after another. The page draws one
//                               at a time, and the switcher (js/runs.js) says
//                               which. See bootScan below for the format.
//
// Either way the run's `meta` -- what is known ABOUT the run rather than in it
// -- ends up on window.FDTD.meta: from the manifest for a set, from a sidecar
// beside the dump for a single run (loadMeta below).
(function () {
'use strict';

// Loads `src`, resolving TRUE if it ran and FALSE if it was not there.
// Never rejects: a missing file is an answer, not an error. It is the next
// candidate name to try for a dump, and a tool nobody copied for the rest.
function load(src) {
  return new Promise(function (done) {
    var el = document.createElement('script');
    el.src = src;
    el.onload = function () { done(true); };
    el.onerror = function () { done(false); };
    document.head.appendChild(el);
  });
}

// The first of `names` that loads, or null.
async function firstOf(names) {
  for (var i = 0; i < names.length; i++)
    if (await load(names[i])) return names[i];
  return null;
}

// No data beside the page: say so, in words, rather than rendering an empty
// scene that looks like a broken run.
function explain(tried) {
  document.body.innerHTML = '';
  document.body.style.cssText =
      'display:block;max-width:620px;margin:16vh auto;padding:0 24px';
  var el = document.createElement('div');
  // Written as markup rather than assembled node by node because every part
  // of it is fixed text; the one value from outside is escaped below.
  el.innerHTML =
      '<h2>No run data beside this page</h2>' +
      '<p>This viewer draws a run’s dump, and expects to find one next to ' +
      'it. Copy the viewer into an output directory:</p>' +
      '<p><code>make view OUT=&lt;the run’s directory&gt;</code></p>' +
      '<p>and open this page from there. To read a dump by name instead, ' +
      'add <code>?d=&lt;file&gt;</code> to this page’s address.</p>' +
      '<p class="looked">Looked for: <span></span></p>';
  el.querySelector('.looked span').textContent = tried.join(', ');
  el.querySelector('.looked').style.cssText = 'color:var(--ink-3)';
  // The theme styles the pages, not prose: give the few elements used here
  // their look directly rather than growing a stylesheet rule for one screen.
  el.querySelectorAll('p').forEach(function (p) {
    p.style.cssText += ';line-height:1.65;color:var(--ink-2)';
  });
  el.querySelectorAll('code').forEach(function (c) {
    c.style.cssText = 'font-family:var(--font-mono);color:var(--ink);' +
        'background:var(--plot);border:1px solid var(--line);' +
        'border-radius:4px;padding:3px 7px';
  });
  document.body.appendChild(el);
}

// The developer tools, if this copy of the viewer carries any: one probe for
// js/debug/tools.js, which names the rest (make view DEBUG=1). Not being there
// is the normal case and the ordinary outcome -- the browser notes the missing
// file and nothing else happens. Each tool registers itself on
// window.FDTD_OVERLAYS as it runs, so nothing here or on the page names one.
async function loadDebugTools(dir) {
  if (!await load(dir + '/tools.js')) return false;
  var names = window.FDTD_DEBUG_TOOLS || [];
  for (var i = 0; i < names.length; i++) await load(dir + '/' + names[i]);
  return names.length > 0;
}

// What is known ABOUT a single run, from a sidecar beside its dump: the
// design target it was run for and how it measured up (js/verdicts.js). The
// solver cannot write this -- it is never told what the board was designed to
// do -- so it comes from whoever started the run, in a file named by the page
// that would show it (`meta` in the boot config) and resolved relative to the
// DUMP rather than to the page: an archived run folder then carries its own
// verdicts wherever it is copied to.
//
// Not being there is the ordinary case (a run nobody scored), and it is the
// same non-event as a missing debug tool: the browser notes the file, the page
// renders without the block, and nothing is said about it.
async function loadMeta(name, dump) {
  if (!await load(new URL(name, new URL(dump, location.href)).href)) return;
  window.FDTD = window.FDTD || {};
  window.FDTD.meta = window.FDTD_VERDICTS;
}

// A dotted path into the loaded dump, or undefined. Used for the one question
// a page asks of its data before rendering it: does this run carry the section
// a tool needs.
function at(path) {
  return path.split('.').reduce(function (o, k) {
    return o == null ? undefined : o[k];
  }, window.FDTD && window.FDTD.s);
}

// A whole folder of runs, from one manifest. The manifest is a classic script
// assigning
//
//   window.FDTD_SCAN = {page: {title, subtitle},
//                       runs: [{meta: {label, best, error, props}, data: <js>},
//                              ...]};
//
// where each `data` names that run's dump RELATIVE TO THE MANIFEST, so the set
// stays portable as a whole and the page reading it can live anywhere -- a
// viewer installed once, beside neither.
//
// Every dump is loaded up front and its `s` bucket kept, because each one
// reassigns window.FDTD as it runs and only the moment after it loads can tell
// them apart. A run whose dump is missing or absent from the manifest keeps an
// empty bucket rather than dropping out of the list: it is part of the set's
// story, and the page says so when it is selected.
async function bootScan(page, manifest) {
  if (!await load(manifest)) return explain([manifest]);
  var scan = window.FDTD_SCAN;
  var base = new URL(manifest, location.href);
  for (var i = 0; i < scan.runs.length; i++) {
    var run = scan.runs[i];
    var got = run.data && await load(new URL(run.data, base).href);
    run.s = (got && window.FDTD && window.FDTD.s) || {};
  }
  FDTDRuns.header(scan.page);
  FDTDRuns.runList(scan.runs, function (n) {
    window.FDTD = {s: scan.runs[n].s, meta: scan.runs[n].meta, scan: scan};
    page.main();
  });
}

window.FDTDViewer = {
  // page = {data: [candidate dump names],
  //         meta: '<sidecar name>',
  //         debug: {dir: 'js/debug', when: '<payload path>'},
  //         main: fn}
  //
  // `main` draws window.FDTD.s. It is called once for a single run and once
  // per selection for a set of them, so a page's render has to be able to run
  // twice -- see vizRenderReset (js/pagekit.js), which is where that starts.
  //
  // The dump first, since a page with nothing to draw has nothing to load
  // tools for; then the tools, if this run recorded anything for them AND this
  // copy of the viewer carries them; then the page's own rendering, once, with
  // everything in place.
  //
  // Those two conditions are separate on purpose (viewer/README.md): one asks
  // what the solve recorded, the other what was copied here, and the machine
  // that wrote a dump is often not the one reading it. Failing either, the
  // page renders without the tools and says nothing about it.
  async boot(page) {
    var query = new URLSearchParams(location.search);
    var scan = query.get('scan');
    if (scan) return bootScan(page, scan);
    var named = query.get('d');
    var tried = named ? [named] : page.data;
    var found = await firstOf(tried);
    if (!found) return explain(tried);
    if (page.meta) await loadMeta(page.meta, found);
    if (page.debug && at(page.debug.when) !== undefined &&
        await loadDebugTools(page.debug.dir))
      window.FDTD_GRID_DEBUG = true;
    page.main();
  },
};
})();
