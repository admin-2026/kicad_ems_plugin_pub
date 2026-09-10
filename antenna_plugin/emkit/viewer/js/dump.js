// How a page finds the run -- or the runs -- it is drawing, and how anything
// that is not part of the viewer attaches itself to a page.
//
// The viewer is checked in once and read where it stands (`make workbench`
// serves the tree), so a page is never generated for a particular dump: it is
// told which to draw, or it looks beside itself for one -- a folder with it
// copied into it opens on its own. Everything here is a classic <script>
// injected at runtime,
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
// Either way, `?with=<script>[,<script>]` names scripts to run once the dump
// is in and before the page draws (loadWith below). Nothing shipped here ever
// passes it, and no page names a script it does not carry: it is the one way
// in for code the viewer does not know about, which registers itself on
// whatever it means to extend and is drawn without ever being named here.
//
// Either way the run's `meta` -- what is known ABOUT the run rather than in it
// -- ends up on window.FDTD.meta: from the manifest for a set, from a sidecar
// beside the dump for a single run (loadMeta below).
(function () {
'use strict';

// Loads `src`, resolving TRUE if it ran and FALSE if it was not there.
// Never rejects: a missing file is an answer, not an error -- the next
// candidate name to try for a dump, or an optional file nobody put here.
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
      '<h2>No run data for this page</h2>' +
      '<p>This viewer draws a run’s dump, and was given none. Name one in ' +
      'this page’s address:</p>' +
      '<p><code>?d=&lt;the run’s dump&gt;</code></p>' +
      '<p>Opened from a run’s own folder, this page reads the dump beside it ' +
      'and needs nothing in the address at all.</p>' +
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

// Would running `src` still be running something of this site's? A page must
// not be talked into fetching code from elsewhere by a link somebody sent, so
// an address may only name a script the page could have loaded itself. Same
// protocol and same origin -- which on a file:// page means the same opaque
// origin both sides, so a folder opened from the filesystem can still extend
// itself and nothing with a scheme of its own gets in.
function ours(src) {
  try {
    var to = new URL(src, location.href);
    return to.protocol === location.protocol && to.origin === location.origin;
  } catch (e) { return false; }
}

// The scripts named in `?with=`, in the order given, each waited for. This is
// the whole of what the viewer knows about code that is not its own: it runs
// it, and the page draws whatever registered itself in the meantime (the grid
// page's window.FDTD_OVERLAYS, say). Nothing here names a file, a directory or
// a purpose, so a page carries no trace of what anyone might attach to it.
//
// A script may bring its own: pushing onto window.FDTD_WITH queues more, which
// is how a directory of them arrives under one name in the address. It pushes
// paths resolved against ITSELF -- the address named the entry, and only the
// entry knows where its neighbours are.
async function loadWith(list) {
  var queue = list.slice();
  window.FDTD_WITH = [];
  while (queue.length) {
    var src = queue.shift();
    if (!ours(src)) continue;
    await load(src);
    queue = queue.concat(window.FDTD_WITH.splice(0));
  }
}

// What is known ABOUT a single run, from a sidecar beside its dump: the
// design target it was run for and how it measured up (js/verdicts.js). The
// solver cannot write this -- it is never told what the board was designed to
// do -- so it comes from whoever started the run, in a file named by the page
// that would show it (`meta` in the boot config) and resolved relative to the
// DUMP rather than to the page: an archived run folder then carries its own
// verdicts wherever it is copied to.
//
// Not being there is the ordinary case (a run nobody scored) and a non-event:
// the browser notes the file, the page renders without the block, and nothing
// is said about it.
async function loadMeta(name, dump) {
  if (!await load(new URL(name, new URL(dump, location.href)).href)) return;
  window.FDTD = window.FDTD || {};
  window.FDTD.meta = window.FDTD_VERDICTS;
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
    window.FDTD = {s: scan.runs[n].s, meta: scan.runs[n].meta, scan: scan,
                   dump: scan.runs[n].data};
    page.main();
  });
}

window.FDTDViewer = {
  // page = {data: [candidate dump names], meta: '<sidecar name>', main: fn}
  //
  // `main` draws window.FDTD.s. It is called once for a single run and once
  // per selection for a set of them, so a page's render has to be able to run
  // twice -- see vizRenderReset (js/pagekit.js), which is where that starts.
  //
  // The dump first, since a page with nothing to draw has nothing to attach
  // anything to; then whatever the address asked to run; then the page's own
  // rendering, once, with everything in place.
  async boot(page) {
    var query = new URLSearchParams(location.search);
    var scan = query.get('scan');
    if (scan) return bootScan(page, scan);
    var named = query.get('d');
    var tried = named ? [named] : page.data;
    var found = await firstOf(tried);
    if (!found) return explain(tried);
    // Which of the candidates answered -- the one thing that says which flow
    // wrote this run, for a page both of them draw.
    (window.FDTD = window.FDTD || {}).dump = found;
    if (page.meta) await loadMeta(page.meta, found);
    var with_ = query.get('with');
    if (with_) await loadWith(with_.split(','));
    page.main();
  },
};
})();
