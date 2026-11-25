/* PlanD web UI, first script (loaded from <head>, before the stylesheet): runs before the first paint.
 * A file rather than an inline <script> so the page can be served with a strict Content-Security-Policy
 * (script-src 'self'). start.js, at the end of <body>, loads app.js once the dictionary is in. */
// Apply the appearance settings before the first paint (no flash of the wrong theme or a sidebar that snaps shut).
(function () {
  var ui = {};
  try { ui = JSON.parse(localStorage.getItem('pland.ui') || '{}') || {}; } catch (e) { /* storage unavailable */ }
  var r = document.documentElement;
  if (ui.theme === 'light' || ui.theme === 'dark') r.dataset.theme = ui.theme;
  if (ui.accent && ui.accent !== 'vermilion') r.dataset.accent = ui.accent;
  if (ui.size && ui.size !== 'default') r.dataset.size = ui.size;
  if (ui.density === 'compact') r.dataset.density = 'compact';
  if (ui.reasoning === 'hide') r.dataset.reasoning = 'hide';
  if (ui.sideWidth) r.style.setProperty('--side-w', ui.sideWidth + 'px');
  if (ui.panelWidth) r.style.setProperty('--panel-w', ui.panelWidth + 'px');
  if (ui.sideCollapsed) r.classList.add('side-collapsed');
  // Interface language (Settings → Appearance → Language): auto follows the browser's first language and picks
  // Traditional Chinese for zh-TW / zh-HK / zh-MO / zh-Hant*. The dictionary is fetched now, and app.js is loaded
  // only once it has arrived (start.js, at the end of <body>), so the first render is already translated.
  var lang = ui.lang === 'en' || ui.lang === 'zh-Hant' ? ui.lang : 'en';
  if (!ui.lang || ui.lang === 'auto') {
    var first = (navigator.languages && navigator.languages[0]) || navigator.language || '';
    lang = /^zh-(hant|tw|hk|mo)(-|$)/i.test(first) ? 'zh-Hant' : 'en';
  }
  r.lang = lang;
  if (lang !== 'en') {
    r.classList.add('i18n-pending');  // keeps the English static text from flashing (style.css)
    // a dictionary that hangs must not keep the app from starting: give up after 3 s and start untranslated
    var ctl = typeof AbortController === 'function' ? new AbortController() : null;
    var timer = setTimeout(function () { if (ctl) ctl.abort(); }, 3000);
    var load = function (file) {
      return fetch('i18n/' + file, { cache: 'no-cache', signal: ctl ? ctl.signal : undefined })
        .then(function (res) { return res.ok ? res.json() : null; })
        .catch(function () { return null; });
    };
    var late = new Promise(function (done) { setTimeout(function () { done([null, null]); }, 3100); });
    // two files: the interface itself, and the text the server sends (errors, notices, group system lines)
    window.PLAND_DICT_LOADING = Promise.race([Promise.all([load(lang + '.json'), load(lang + '.server.json')]), late])
      .then(function (d) { clearTimeout(timer); window.PLAND_SERVER_DICT = d[1]; return d[0]; });
  }
})();
