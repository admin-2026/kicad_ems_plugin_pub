// A run judged against the design target it was run for, painted two ways.
//
// Nothing here judges anything, and that is the point. A run arrives already
// scored -- a list of properties, each with a label, a status (pass / warn /
// fail / none), the glyph that stands for it and the text to show -- and this
// turns that list into a strip of glyphs or a table. What counts as a pass is
// decided by whoever produced the list and is never re-derived from what is on
// screen: the target a board was designed against (its band, its match, the
// impedance it feeds) is not in the solver's dump, so a page deriving a verdict
// would have to invent one.
//
// Two things carry such a list, and both are somebody else's file:
//
//   a scan manifest    one per run, beside its dump (js/runs.js paints them
//                      on the switcher's rows)
//   a run's own sidecar  beside the dump of a single run (js/dump.js loads it
//                      into window.FDTD.meta; report.html shows the table)
(function () {
'use strict';

// The compact form: one glyph per property, in table order, each carrying its
// own reading as a tooltip. Small enough to ride on a row in a list of runs.
function strip(props) {
  return '<span class="rr-verdicts">' + props.map(p =>
      `<span class="rv rv-${p.status}" ` +
      `title="${vizEsc(p.label + ': ' + p.text)}">` +
      `${vizEsc(p.glyph || '·')}</span>`).join('') + '</span>';
}

// The same list spelled out: property, verdict, value. A measurement list like
// the report's own .kv rows -- name left, figure ranged right in the mono face
// -- with the verdict glyph between them.
function table(props) {
  return '<table class="rv-table"><tbody>' + props.map(p =>
      `<tr class="rv-${p.status}"><td class="rv-k">${vizEsc(p.label)}</td>` +
      `<td class="rv-g">${vizEsc(p.glyph)}</td>` +
      `<td class="rv-v">${vizEsc(p.text)}</td></tr>`).join('') +
      '</tbody></table>';
}

// One glyph for the whole run, in the colour of its worst measured property:
// the strip's summary, for a page with a single run to put beside what it was
// judged against.
function overall(meta) {
  return `<span class="rv rv-${meta.overall}">` +
         `${vizEsc(meta.overall_glyph || '·')}</span>`;
}

window.FDTDVerdicts = {strip, table, overall};
})();
