/* PlanD web UI, last script of <body>: starts app.js once the interface dictionary has arrived (boot.js fetches it).
 * A file rather than an inline <script>, for the Content-Security-Policy (script-src 'self'). */
// app.js runs once the interface dictionary has arrived (English needs none); a failed fetch falls back to English.
(function () {
  function start(dict) {
    window.PLAND_DICT = dict || null;
    if (window.PLAND_DICT_LOADING && !dict) window.PLAND_DICT_FAILED = true;  // app.js starts in English and says so
    var s = document.createElement('script');
    s.src = 'app.js';
    document.body.appendChild(s);
  }
  if (window.PLAND_DICT_LOADING) window.PLAND_DICT_LOADING.then(start); else start(null);
  // Never leave the page hidden: if app.js is slow or fails, show what there is after a few seconds.
  setTimeout(function () { document.documentElement.classList.remove('i18n-pending'); }, 4000);
})();
