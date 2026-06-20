// Mirror of viewer.html per-view content-width resolution.
// "폭 독립화": md 뷰와 split 뷰가 각각 자기 폭을 기억한다.
// pdf/video 뷰는 .markdown-container 가 없어 폭이 적용되지 않으므로 md 키로 합친다.

// ── logic under test (mirror of viewerApp methods) ──────────────────
function contentWidthKey(view) {
  return view === 'split' ? 'pf-content-width-split' : 'pf-content-width-md';
}
function defaultContentWidth(view) {
  return view === 'split' ? '100%' : '900px';
}
// store: plain object standing in for localStorage
function loadContentWidthForView(view, store) {
  return (
    store[contentWidthKey(view)] ||
    store['pf-content-width'] ||   // migration from legacy global key
    defaultContentWidth(view)
  );
}
function setContentWidth(view, store, width) {
  store[contentWidthKey(view)] = width;
  return width;
}

// ── harness ─────────────────────────────────────────────────────────
const T = (d, g, w) => {
  const ok = g === w;
  console.log(`${ok ? '✓' : '✗'} ${d}: ${g}${ok ? '' : ' WANT ' + w}`);
  if (!ok) process.exitCode = 1;
};

// fresh (no stored keys): view-specific defaults
T('fresh md -> 900px', loadContentWidthForView('md', {}), '900px');
T('fresh split -> 100%', loadContentWidthForView('split', {}), '100%');
T('fresh pdf -> md default 900px', loadContentWidthForView('pdf', {}), '900px');

// legacy global migration: old single key seeds both views until overridden
T('legacy global seeds md', loadContentWidthForView('md', {'pf-content-width': '1200px'}), '1200px');
T('legacy global seeds split', loadContentWidthForView('split', {'pf-content-width': '1200px'}), '1200px');

// independence: each view keeps its own value
{
  const store = {};
  setContentWidth('md', store, '720px');
  setContentWidth('split', store, '100%');
  T('md remembers own', loadContentWidthForView('md', store), '720px');
  T('split remembers own', loadContentWidthForView('split', store), '100%');
  // changing split must NOT bleed into md
  setContentWidth('split', store, '1200px');
  T('md unchanged after split change', loadContentWidthForView('md', store), '720px');
  T('split updated', loadContentWidthForView('split', store), '1200px');
}

// view-specific key overrides legacy global
{
  const store = {'pf-content-width': '1200px', 'pf-content-width-md': '720px'};
  T('md own key beats legacy', loadContentWidthForView('md', store), '720px');
  T('split falls back to legacy', loadContentWidthForView('split', store), '1200px');
}

console.log(process.exitCode ? 'FAIL' : 'ALL PASS');
