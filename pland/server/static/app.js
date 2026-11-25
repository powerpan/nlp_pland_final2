/* PlanD web UI — vanilla JS, no build step, no external dependencies.
 *
 * Layout (Bot Mode):
 *   sidebar   Chats (single-agent sessions of the default profile) | Bots (roster + group rooms)
 *   main      the conversation: messages, tool-call cards, activity rows, the streaming reply,
 *             HITL cards, the agent's plan (todo list), live status, composer — or, for a group,
 *             its task board as status columns (#/room/<id>/board)
 *   panel     room: task board / members / shared files / settings; bot: memory / workspace files /
 *             tasks / sessions / settings
 *
 * Data flow: REST for state, one WebSocket (/api/events) for live updates. Events never carry the
 * authoritative transcript; they trigger small incremental fetches (`?after=<last id>`), so the
 * view is always what the server stored.
 */
'use strict';

// ====================================================================== helpers
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const enc = encodeURIComponent;

/** Element builder. `html` is only ever fed with output of the markdown renderer (escaped). */
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'html') el.innerHTML = v;
      else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
      else if (k === 'dataset') Object.assign(el.dataset, v);
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else if (k === 'value') el.value = v;
      else if (v === true) el.setAttribute(k, '');
      else el.setAttribute(k, v);
    }
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/** fetch(), with a readable error when the server cannot be reached at all (fetch's own is "Failed to fetch"). */
async function reach(path, opt) {
  try { return await fetch(path, opt); } catch (e) {
    if (e.name === 'AbortError') throw e;
    const err = new Error(t('Cannot reach the PlanD server'));
    err.status = 0;
    throw err;
  }
}

async function api(method, path, body) {
  const opt = { method, headers: {} };
  if (body !== undefined) {
    opt.headers['Content-Type'] = 'application/json';
    opt.body = JSON.stringify(body);
  }
  const r = await reach(path, opt);
  const text = await r.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!r.ok) {
    let detail = data && data.detail !== undefined ? data.detail : `${r.status} ${r.statusText}`;
    if (Array.isArray(detail)) detail = detail.map(d => d.msg || JSON.stringify(d)).join('; ');
    const err = new Error(typeof detail === 'string' ? ts(detail) : JSON.stringify(detail));
    err.status = r.status;
    err.detail = detail;  // as the server sent it
    throw err;
  }
  return data;
}

/** "now", "5m", "3h", "2d", then a date ("Nov 20"); `ago` adds "ago" to the minute/hour/day forms. */
function relTime(ts, suffix = false) {
  if (!ts) return '';
  const s = Date.now() / 1000 - ts;
  if (s < 45) return t('now');
  if (s < 3600) return suffix ? t('{n}m ago', { n: Math.round(s / 60) }) : t('{n}m', { n: Math.round(s / 60) });
  if (s < 86400) return suffix ? t('{n}h ago', { n: Math.round(s / 3600) }) : t('{n}h', { n: Math.round(s / 3600) });
  if (s < 7 * 86400) return suffix ? t('{n}d ago', { n: Math.round(s / 86400) }) : t('{n}d', { n: Math.round(s / 86400) });
  return new Date(ts * 1000).toLocaleDateString(LOCALE, { month: 'short', day: 'numeric' });
}
const clock = ts => ts ? new Date(ts * 1000).toLocaleTimeString(LOCALE, { hour: '2-digit', minute: '2-digit' }) : '';
const fullTime = ts => ts ? new Date(ts * 1000).toLocaleString(LOCALE) : '';
const fmtDur = s => s == null ? '' : s < 1 ? t('{n}ms', { n: Math.round(s * 1000) }) : s < 60 ? t('{n}s', { n: s.toFixed(1) })
  : t('{m}m{s}s', { m: Math.floor(s / 60), s: Math.round(s % 60) });
const fmtNum = n => n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : String(n || 0);
/** A count with its noun, as a whole phrase so each language can word it: plural(3, '{n} task', '{n} tasks'). */
const plural = (n, one, many) => t(n === 1 ? one : many, { n });
const cap = s => (s ? s[0].toUpperCase() + s.slice(1) : s);
const ago = ts => relTime(ts, true);

function debounce(fn, ms) {
  let timer = null;
  return (...a) => { clearTimeout(timer); timer = setTimeout(() => fn(...a), ms); };
}

function rafOnce(fn) {
  let queued = false;
  return () => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; fn(); });
  };
}

/** Below this width the details panel overlays the conversation instead of sitting beside it. */
const isNarrow = () => window.innerWidth <= 1180;

const prefs = {
  get(k, d) { try { const v = localStorage.getItem('pland.' + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem('pland.' + k, JSON.stringify(v)); } catch { /* storage unavailable */ } },
};

/** Appearance and layout of this browser (Settings → Appearance). The <head> script applies the same keys before
 *  the first paint; `applyUi` keeps the root element in step afterwards. */
const UI_DEFAULTS = { theme: 'system', accent: 'vermilion', size: 'default', density: 'comfortable', reasoning: 'collapsed', lang: 'auto',
  panelDefault: 'remember', sideWidth: 272, panelWidth: 360, sideCollapsed: false };
const ui = { ...UI_DEFAULTS, ...prefs.get('ui', {}) };
function setUi(key, value) {
  ui[key] = value;
  prefs.set('ui', Object.fromEntries(Object.entries(ui).filter(([k, v]) => v !== UI_DEFAULTS[k])));
  applyUi();
}
// ====================================================================== language
/* Interface language (Settings → Appearance → Language, `ui.lang`: auto | en | zh-Hant). The <head> script of
   index.html resolves it, sets <html lang> and fetches static/i18n/<lang>.json before this file runs, so the first
   render is already translated. `t(source, params)` looks the English source string up in that dictionary and
   fills `{name}` placeholders; a missing key falls back to the English source. Data (bot and room names, messages,
   tool names, model ids, paths) is never passed through t(). Keep the first argument a literal: tests/test_i18n.py
   collects the keys from this file. */
const LANG_NAMES = { auto: 'Auto', en: 'English', 'zh-Hant': '繁體中文' };
const DICT = (document.documentElement.lang === 'zh-Hant' && window.PLAND_DICT) || null;
const LANG = DICT ? 'zh-Hant' : 'en';
const LOCALE = LANG === 'en' ? undefined : 'zh-Hant-TW';  // undefined: the browser's own locale, as before
if (!DICT) document.documentElement.lang = 'en';  // the dictionary did not load: the whole UI stays English
function t(source, params) {
  const s = DICT && Object.prototype.hasOwnProperty.call(DICT, source) && DICT[source] ? DICT[source] : source;
  return params ? s.replace(/\{(\w+)\}/g, (m, k) => (k in params ? String(params[k]) : m)) : s;
}
/** Static text of index.html: elements with `data-i18n` ("text", "title", "aria-label", "placeholder"; empty = text). */
function translateStatic() {
  if (DICT) {
    for (const el of document.querySelectorAll('[data-i18n]')) {
      for (const what of (el.dataset.i18n || 'text').split(/\s+/)) {
        if (what === 'text') el.textContent = t(el.textContent);
        else if (el.hasAttribute(what)) el.setAttribute(what, t(el.getAttribute(what)));
      }
    }
  }
  document.documentElement.classList.remove('i18n-pending');  // set by the <head> script while the dictionary loads
}

// ---------------------------------------------------------------- text the server sends
/* Errors, key notices, folder-check reasons, the lines the server writes into a group's transcript and the example
   team's descriptions arrive in English (the bots read some of them too, so they are stored that way). They are
   translated here, for display only, from i18n/<lang>.server.json: entries are English templates with {name}
   placeholders. tests/test_i18n_server.py collects the templates from the Python sources and fails when one has
   no entry. */
const SERVER_DICT = (DICT && window.PLAND_SERVER_DICT) || null;
const hasOwn = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
const SERVER_PATTERNS = Object.entries(SERVER_DICT || {}).filter(([k]) => /\{\w+\}/.test(k)).map(([k, out]) => {
  const parts = k.split(/\{(\w+)\}/);  // literal, name, literal, name, … literal
  const names = parts.filter((_, i) => i % 2);
  const body = parts.map((p, i) => (i % 2 ? '([\\s\\S]+?)' : p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))).join('');
  return {
    names, out, weight: parts.filter((_, i) => i % 2 === 0).join('').length,
    full: new RegExp(`^${body}$`),
    // as the first of several sentences: only a template that ends in literal text can tell where it stops
    head: parts[parts.length - 1] ? new RegExp(`^${body}(?=\\s)`) : null,
  };
}).sort((a, b) => b.weight - a.weight);  // the most specific template first

/** A value the server put into a message: a known phrase ("a subagent", "an API key and a model") or data. */
function tsValue(v) {
  const bare = /^'[^']*'$/.test(v) ? v.slice(1, -1) : v;  // Python's {name!r}
  if (hasOwn(SERVER_DICT, bare)) return SERVER_DICT[bare];
  const parts = bare.split(' and ');
  return parts.length > 1 && parts.every(x => hasOwn(SERVER_DICT, x)) ? parts.map(x => SERVER_DICT[x]).join('與') : bare;
}
const CJK = '\\u3000-\\u303f\\u4e00-\\u9fff\\uff00-\\uffef';
function tsFill(pat, m) {
  const text = pat.out.replace(/\{(\w+)\}/g, (all, k) => (pat.names.includes(k) ? tsValue(m[pat.names.indexOf(k) + 1]) : all));
  // a translated phrase dropped into a Chinese sentence needs no space around it (a path or a name keeps its own)
  return text.replace(new RegExp(`([${CJK}]) (?=[${CJK}])`, 'g'), '$1');
}
/** The template that matches all of `text`, most specific first. */
function tsWhole(text) {
  if (hasOwn(SERVER_DICT, text)) return SERVER_DICT[text];
  for (const pat of SERVER_PATTERNS) {
    const m = pat.full.exec(text);
    if (m) return tsFill(pat, m);
  }
  return null;
}
/** The shortest known sentence `text` starts with, when more text follows it. */
function tsFirstSentence(text) {
  let best = null;
  for (const key of Object.keys(SERVER_DICT)) {
    if (!/\{\w+\}/.test(key) && /\.$/.test(key) && text.startsWith(key + ' ') && (!best || key.length < best.length)) {
      best = { length: key.length, text: SERVER_DICT[key] };
    }
  }
  for (const pat of SERVER_PATTERNS) {
    const m = pat.head && pat.head.exec(text);
    if (m && (!best || m[0].length < best.length)) best = { length: m[0].length, text: tsFill(pat, m) };
  }
  return best;
}
/** Exact server phrases only (e.g. a bot description from the example team); anything else is returned as it is. */
function tsExact(text) {
  return SERVER_DICT && typeof text === 'string' && hasOwn(SERVER_DICT, text) ? SERVER_DICT[text] : text;
}
/** Translate text the server wrote; text it does not recognise comes back unchanged. */
function ts(text) {
  if (!SERVER_DICT || typeof text !== 'string' || !text) return text;
  let rest = text, out = '';
  while (rest) {  // a notice can be several sentences joined by a space: take them one at a time
    const first = tsFirstSentence(rest);
    if (first) {
      out += first.text;
      rest = rest.slice(first.length).trimStart();
      continue;
    }
    const whole = tsWhole(rest);
    if (whole == null) return out ? `${out} ${rest}` : text;
    return out + whole;
  }
  return out;
}

function applyUi() {
  const r = document.documentElement;
  const attr = (name, value, off) => { if (value === off) delete r.dataset[name]; else r.dataset[name] = value; };
  attr('theme', ui.theme, 'system');
  attr('accent', ui.accent, 'vermilion');
  attr('size', ui.size, 'default');
  attr('density', ui.density, 'comfortable');
  attr('reasoning', ui.reasoning, 'collapsed');
  r.style.setProperty('--side-w', `${ui.sideWidth}px`);
  r.style.setProperty('--panel-w', `${ui.panelWidth}px`);
  r.classList.toggle('side-collapsed', !!ui.sideCollapsed);
}

const IS_MAC = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
/** "mod+shift+o" -> "⇧⌘O" on macOS, "Ctrl+Shift+O" elsewhere. */
function keyLabel(combo) {
  const parts = combo.split('+');
  const key = parts.pop();
  const name = { ',': ',', '.': '.', '/': '/', escape: 'Esc', enter: '↵' }[key] || key.toUpperCase();
  if (IS_MAC) return parts.map(m => ({ mod: '⌘', shift: '⇧', alt: '⌥' }[m])).sort((a, b) => '⌥⇧⌘'.indexOf(a) - '⌥⇧⌘'.indexOf(b)).join('') + name;
  return [...parts.map(m => ({ mod: 'Ctrl', shift: 'Shift', alt: 'Alt' }[m])), name].join('+');
}

const ICON = {
  panel: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M15 4v16"/></svg>',
  close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/></svg>',
  edit: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h4L19 9l-4-4L4 16v4z"/><path d="M13.5 6.5l4 4"/></svg>',
  tool: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4 2.6-2.6z"/></svg>',
  menu: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h16"/></svg>',
  chat: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M5 18l-2 3V6a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5z"/></svg>',
  refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20 11a8 8 0 0 0-14.6-4.5L4 8"/><path d="M4 4v4h4"/><path d="M4 13a8 8 0 0 0 14.6 4.5L20 16"/><path d="M20 20v-4h-4"/></svg>',
  folder: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"/></svg>',
  file: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/></svg>',
  sidebar: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M9 4v16"/><path d="M5.5 8h1.5M5.5 11h1.5"/></svg>',
  gear: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>',
  search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/></svg>',
  palette: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3a9 9 0 1 0 0 18c1.1 0 1.7-.8 1.7-1.7 0-.5-.2-.9-.5-1.2-.3-.3-.5-.7-.5-1.2 0-.9.8-1.7 1.7-1.7H16a5 5 0 0 0 5-5c0-4-4-7.2-9-7.2z"/><circle cx="7.5" cy="11" r="1"/><circle cx="10" cy="7" r="1"/><circle cx="15" cy="7.5" r="1"/></svg>',
  cube: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M4 7.5l8 4.5 8-4.5M12 12v9"/></svg>',
  shield: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M12 3l7.5 3v5.5c0 4.6-3.2 8.3-7.5 9.5-4.3-1.2-7.5-4.9-7.5-9.5V6z"/><path d="M9 12l2 2 4-4" stroke-linecap="round"/></svg>',
  box: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="3.5" y="3.5" width="17" height="17" rx="2"/><path d="M8 9l3 3-3 3M13 15h3" stroke-linecap="round"/></svg>',
  gauge: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4.2 17.5a9 9 0 1 1 15.6 0"/><path d="M12 13l4-4"/><circle cx="12" cy="13" r="1.3"/></svg>',
  chart: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4 20h16"/><path d="M7 16v-5M12 16V6M17 16v-8"/></svg>',
  keyboard: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2.5" y="6" width="19" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M8 14h8"/></svg>',
  info: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/></svg>',
};
const iconBtn = (icon, title, onclick, extra = '') => h('button', { type: 'button', class: `icon-btn ${extra}`, title, 'aria-label': title, onclick, html: ICON[icon] });

// ====================================================================== markdown
/** A small, safe markdown renderer: everything is HTML-escaped; only known tags are emitted. */
const md = (() => {
  const RE_FENCE = /^\s{0,3}(`{3,}|~{3,})\s*([\w+#.-]*)/;
  const RE_HEAD = /^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/;
  const RE_HR = /^\s{0,3}([-*_])(?:\s*\1){2,}\s*$/;
  const RE_QUOTE = /^\s{0,3}>\s?/;
  const RE_LIST = /^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$/;
  const RE_TSEP = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;

  const indent = l => l.match(/^\s*/)[0].replace(/\t/g, '    ').length;
  const safeUrl = u => (/^(https?:|mailto:)/i.test(u.trim()) ? u.trim() : null);

  function emph(s) { // s is already escaped
    return s
      .replace(/\*\*(?=\S)([\s\S]*?\S)\*\*/g, '<strong>$1</strong>')
      .replace(/(^|[^\w])__(?=\S)([\s\S]*?\S)__(?!\w)/g, '$1<strong>$2</strong>')
      .replace(/(^|[^*\w])\*(?=[^\s*])([^*\n]*?[^\s*])\*(?![*\w])/g, '$1<em>$2</em>')
      .replace(/(^|[^_\w])_(?=[^\s_])([^_\n]*?[^\s_])_(?![_\w])/g, '$1<em>$2</em>')
      .replace(/~~(?=\S)([\s\S]*?\S)~~/g, '<del>$1</del>');
  }

  function inline(text) {
    const slots = [];
    const keep = html => `\u0000${slots.push(html) - 1}\u0000`;
    let s = String(text).replace(/\u0000/g, '');
    s = s.replace(/(`+)(?!`)([\s\S]*?[^`])\1(?!`)/g, (_, t, code) => keep(`<code>${esc(code.replace(/^ (.*) $/, '$1'))}</code>`));
    s = s.replace(/!?\[([^\]\n]*)\]\(\s*<?([^)\s>\u0000]+)>?(?:\s+"[^"]*")?\s*\)/g, (m, label, url) => {
      const href = safeUrl(url);
      return href ? keep(`<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${emph(esc(label)) || esc(href)}</a>`) : m;
    });
    s = s.replace(/\bhttps?:\/\/[^\s<>"'`\u0000]+[^\s<>"'`.,;:!?)\]\u0000]/g,
      u => keep(`<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(u)}</a>`));
    s = emph(esc(s));
    for (let pass = 0; pass < 3 && s.includes('\u0000'); pass++) s = s.replace(/\u0000(\d+)\u0000/g, (_, i) => slots[+i] ?? '');
    return s.replace(/\u0000/g, '');
  }

  const isTableStart = (lines, i) => lines[i].includes('|') && i + 1 < lines.length && lines[i + 1].includes('-') && RE_TSEP.test(lines[i + 1]);
  const isBlockStart = (lines, i) => {
    const l = lines[i];
    return RE_FENCE.test(l) || RE_HEAD.test(l) || RE_HR.test(l) || RE_QUOTE.test(l) || RE_LIST.test(l) || isTableStart(lines, i);
  };

  function codeBlock(code, lang) {
    return `<div class="code"><div class="code-head"><span>${esc(lang || 'text')}</span>` +
      `<button type="button" class="code-copy">${esc(t('Copy'))}</button></div><pre><code>${esc(code)}</code></pre></div>`;
  }

  function table(lines, i) {
    const split = r => {
      let s = r.trim();
      if (s.startsWith('|')) s = s.slice(1);
      if (s.endsWith('|') && !s.endsWith('\\|')) s = s.slice(0, -1);
      return s.split(/(?<!\\)\|/).map(c => c.trim().replace(/\\\|/g, '|'));
    };
    const head = split(lines[i]);
    const aligns = split(lines[i + 1]).map(c => (c.startsWith(':') && c.endsWith(':') ? 'center' : c.endsWith(':') ? 'right' : ''));
    const rows = [];
    i += 2;
    while (i < lines.length && lines[i].trim() && lines[i].includes('|')) rows.push(split(lines[i++]));
    // a class, not an inline style attribute: the Content-Security-Policy (style-src self) refuses those
    const cell = (tag, c, k) => `<${tag}${aligns[k] ? ` class="al-${aligns[k]}"` : ''}>${inline(c)}</${tag}>`;
    const thead = `<tr>${head.map((c, k) => cell('th', c, k)).join('')}</tr>`;
    const tbody = rows.map(r => `<tr>${head.map((_, k) => cell('td', r[k] ?? '', k)).join('')}</tr>`).join('');
    return { html: `<div class="table-wrap"><table><thead>${thead}</thead><tbody>${tbody}</tbody></table></div>`, next: i };
  }

  function dedent(lines) {
    const ind = Math.min(...lines.filter(l => l.trim()).map(indent));
    return lines.map(l => l.replace(/\t/g, '    ').slice(Math.min(ind, indent(l)))).join('\n');
  }

  function list(lines, start) {
    const first = lines[start].match(RE_LIST);
    const base = indent(lines[start]);
    const ordered = /\d/.test(first[2]);
    const startNum = ordered ? parseInt(first[2], 10) : 1;
    const items = [];
    let i = start;
    while (i < lines.length) {
      const line = lines[i];
      if (!line.trim()) {
        let j = i + 1;
        while (j < lines.length && !lines[j].trim()) j++;
        if (j >= lines.length) { i = j; break; }
        const nm = lines[j].match(RE_LIST);
        if ((nm && indent(lines[j]) === base && /\d/.test(nm[2]) === ordered) || (indent(lines[j]) > base && items.length)) {
          items[items.length - 1].sub.push('');
          i = j;
          continue;
        }
        break;
      }
      const m = line.match(RE_LIST);
      const ind = indent(line);
      if (m && ind >= base && ind <= base + 1) {
        if (/\d/.test(m[2]) !== ordered) break;
        items.push({ text: [m[3]], sub: [] });
        i++;
        continue;
      }
      if (ind > base && items.length) { items[items.length - 1].sub.push(line); i++; continue; }
      if (!m && items.length && !isBlockStart(lines, i)) {
        const it = items[items.length - 1];
        if (it.sub.length) it.sub.push(line); else it.text.push(line.trim());
        i++;
        continue;
      }
      break;
    }
    const body = items.map(it => {
      let line = it.text.map(inline).join('<br>');
      line = line.replace(/^\[( |x|X)\]\s+/, (_, x) => `<input type="checkbox" disabled${x.trim() ? ' checked' : ''}> `);
      const sub = it.sub.some(l => l.trim()) ? block(dedent(it.sub)) : '';
      return `<li>${line}${sub}</li>`;
    }).join('');
    const tag = ordered ? 'ol' : 'ul';
    return { html: `<${tag}${ordered && startNum !== 1 ? ` start="${startNum}"` : ''}>${body}</${tag}>`, next: i };
  }

  function block(src) {
    const lines = src.split('\n');
    const out = [];
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (!line.trim()) { i++; continue; }
      let m = line.match(RE_FENCE);
      if (m) {
        const close = new RegExp(`^\\s{0,3}${m[1][0] === '`' ? '`' : '~'}{${m[1].length},}\\s*$`);
        const buf = [];
        i++;
        while (i < lines.length && !close.test(lines[i])) buf.push(lines[i++]);
        i++;
        out.push(codeBlock(buf.join('\n'), m[2]));
        continue;
      }
      if ((m = line.match(RE_HEAD))) { const n = m[1].length; out.push(`<h${n}>${inline(m[2])}</h${n}>`); i++; continue; }
      if (RE_HR.test(line)) { out.push('<hr>'); i++; continue; }
      if (RE_QUOTE.test(line)) {
        const buf = [];
        while (i < lines.length && lines[i].trim() && RE_QUOTE.test(lines[i])) buf.push(lines[i++].replace(RE_QUOTE, ''));
        out.push(`<blockquote>${block(buf.join('\n'))}</blockquote>`);
        continue;
      }
      if (isTableStart(lines, i)) { const r = table(lines, i); out.push(r.html); i = r.next; continue; }
      if (RE_LIST.test(line)) { const r = list(lines, i); out.push(r.html); i = r.next; continue; }
      const buf = [line];
      i++;
      while (i < lines.length && lines[i].trim() && !isBlockStart(lines, i)) buf.push(lines[i++]);
      out.push(`<p>${buf.map(l => inline(l.trim())).join('<br>')}</p>`);
    }
    return out.join('\n');
  }

  return src => block(String(src ?? '').replace(/\r\n?/g, '\n').replace(/\u0000/g, ''));
})();

// ====================================================================== state
const S = {
  status: null,
  profiles: [],
  rooms: [],
  chats: [],
  hitl: [],
  usage: null,
  runs: new Map(),     // "profile\0session" -> {profile, session_id, room_id, state, tool, origin}
  drives: new Map(),   // room id -> drive info
  tab: 'chats',
  panelOpen: !isNarrow() && ui.panelDefault !== 'closed' && prefs.get('panelOpen', true),
  ws: null,
  wsOk: false,
  wsRetry: 0,
  wsWasDown: false,
};
let C = null;          // the open conversation (see openView)
const P = { tab: { room: 'board', agent: 'memory' }, token: null, forcePanel: false,
  resizer: h('div', { class: 'resizer', role: 'separator', 'aria-orientation': 'vertical', 'aria-label': t('Resize details (double-click to reset)'), tabindex: '0' }) };

const runKey = (profile, sid) => `${profile}\u0000${sid}`;
const profileOf = name => S.profiles.find(p => p.name === name) || { name, title: name, avatar: '#9ca3af', missing: true };
const bots = () => S.profiles.filter(p => p.bot);

/* A bot's avatar is its colour tile with a small face. Faces of a bot that is running look around and change
   expression with what the run is doing (see faceTick); faces in the transcript history stay still. */
const FACE_SVG = `<svg viewBox="0 0 32 32" aria-hidden="true"><g class="f-head">
<g class="f-eye"><ellipse class="f-white" cx="11" cy="14" rx="3.6" ry="4.2"/><circle class="f-pupil" cx="11" cy="14.2" r="2"/></g>
<g class="f-eye"><ellipse class="f-white" cx="21" cy="14" rx="3.6" ry="4.2"/><circle class="f-pupil" cx="21" cy="14.2" r="2"/></g>
<path class="f-joy" d="M7.6 15.2Q11 10.6 14.4 15.2M17.6 15.2Q21 10.6 24.4 15.2"/>
<path class="f-mouth m-smile" d="M12.6 21.4Q16 24 19.4 21.4"/>
<path class="f-mouth m-flat" d="M13.2 22.6H18.8"/>
<path class="f-mouth m-side" d="M13 23.2Q16.4 22.6 19.4 20.9"/>
<path class="f-mouth m-sad" d="M12.8 23.8Q16 21.2 19.2 23.8"/>
<ellipse class="f-mouth m-o" cx="16" cy="22.6" rx="1.7" ry="2"/>
<path class="f-mouth m-grin" d="M11.6 20.6Q16 26 20.4 20.6Z"/>
</g></svg>`;

function avatar(p, size = 32, ring = false) {
  const el = h('span', {
    class: 'avatar face' + (ring ? ' ring' : ''),
    role: 'img',
    title: `${p.title || p.name} (@${p.name})`,
    'aria-label': p.title || p.name,
    dataset: { bot: p.name },
    style: { background: p.avatar || '#9ca3af', width: `${size}px`, height: `${size}px` },
    html: FACE_SVG,
  });
  const f = FACE.bots.get(p.name);  // join the bot's current look instead of starting from neutral
  if (f && f.shown) faceApply(el, f.shown);
  return el;
}

// ---------------------------------------------------------------- living faces
const FACE = {
  bots: new Map(),     // bot name -> {gx, gy, expr, next, blinkAt, blinkUntil, sweep, shown}
  flash: new Map(),    // bot name -> {expr, until}: a short reaction after a run ends
  wake: 0,             // idle: the next time a face blinks or changes mood (performance.now())
  still: matchMedia('(prefers-reduced-motion: reduce)'),
};
const rand = (a, b) => a + Math.random() * (b - a);
const pickOne = xs => xs[Math.floor(Math.random() * xs.length)];
// What each run state does: where the eyes go, which expressions it shows, how long a look is held (ms).
const FACE_MOODS = {
  thinking: { gaze: [[-1, -1], [1, -1], [-.6, -.9], [.9, -.4], [0, -1], [-1, .1]], expr: ['think', 'think', 'neutral', 'focus'], hold: [650, 1700] },
  tool: { gaze: [[-.8, .9], [.8, .9], [0, 1], [-1, .3], [1, .4], [0, 0]], expr: ['focus', 'focus', 'focus', 'neutral', 'surprise'], hold: [450, 1300] },
  waiting: { gaze: [[0, 0], [0, 0], [0, 0], [-.9, 0], [.9, 0]], expr: ['ask'], hold: [1200, 2600] },
  idle: { gaze: [[0, 0]], expr: ['neutral'], hold: [4000, 8000] },
};
const FACE_STILL = { thinking: 'think', tool: 'focus', writing: 'neutral', waiting: 'ask', idle: 'neutral' };

function faceState(name) {
  const rs = runsFor(r => r.profile === name);
  if (!rs.length) return 'idle';
  for (const s of ['waiting', 'writing', 'tool', 'thinking']) if (rs.some(r => r.state === s)) return s;
  return 'thinking';
}

/** Called when a bot's last run ends: a brief smile after success, a frown after an error. */
function faceReact(name, status) {
  if (profileBusy(name) || status === 'cancelled') return;
  const bad = ['error', 'budget_exceeded', 'loop_detected'].includes(status);
  FACE.flash.set(name, { expr: bad ? 'sad' : 'happy', until: performance.now() + (bad ? 3200 : 2400) });
  const f = FACE.bots.get(name);
  if (f) f.next = 0;
}

function faceStep(name, f, now) {
  const state = faceState(name);
  const flash = FACE.flash.get(name);
  if (flash && (flash.until < now || state !== 'idle')) FACE.flash.delete(name);
  const still = FACE.still.matches;
  if (FACE.flash.has(name)) {
    Object.assign(f, { gx: 0, gy: 0, expr: FACE.flash.get(name).expr });
    f.next = FACE.flash.get(name).until;
  } else if (still) {
    Object.assign(f, { gx: 0, gy: 0, expr: FACE_STILL[state] });
  } else if (state !== f.state || now >= f.next) {
    if (state === 'writing') {  // eyes run along a line, then jump back to the start of the next one
      f.sweep = f.state === 'writing' && f.sweep < 1 ? f.sweep + .5 : -1;
      Object.assign(f, { gx: f.sweep, gy: .55, expr: Math.random() < .12 ? 'happy' : 'neutral', next: now + rand(260, 460) });
    } else {
      const m = FACE_MOODS[state];
      const [gx, gy] = pickOne(m.gaze);
      Object.assign(f, { gx, gy, expr: pickOne(m.expr), next: now + rand(...m.hold) });
    }
  }
  f.state = state;
  if (still) f.blinkUntil = 0;
  else if (now >= f.blinkAt) {
    f.blinkUntil = now + 130;
    f.blinkAt = now + (state === 'idle' ? rand(2600, 7000) : rand(1400, 4200)) * (Math.random() < .15 ? .1 : 1);  // sometimes a double blink
  }
  return { gx: f.gx, gy: f.gy, expr: f.expr, blink: now < f.blinkUntil, live: state !== 'idle' };
}

function faceApply(el, s) {
  const gx = String(s.gx), gy = String(s.gy);
  if (el.style.getPropertyValue('--gx') !== gx) el.style.setProperty('--gx', gx);
  if (el.style.getPropertyValue('--gy') !== gy) el.style.setProperty('--gy', gy);
  if (el.dataset.expr !== s.expr) el.dataset.expr = s.expr;
  el.classList.toggle('blink', s.blink);
  el.classList.toggle('alive', s.live);
}

function faceTick() {
  if (document.hidden) return;
  const now = performance.now();
  // With no run or reaction going on, faces only blink and change mood every few seconds: sleep until the next
  // such moment instead of scanning every avatar eight times a second.
  const active = S.runs.size > 0 || FACE.flash.size > 0;
  if (!active && now < FACE.wake) return;
  const groups = new Map();
  for (const el of document.querySelectorAll('.avatar.face')) {
    if (el.closest('.msg:not(.msg-stream), .activity')) continue;  // history stays still
    const name = el.dataset.bot;
    if (!groups.has(name)) groups.set(name, []);
    groups.get(name).push(el);
  }
  let wake = Infinity;
  for (const [name, els] of groups) {
    let f = FACE.bots.get(name);
    if (!f) FACE.bots.set(name, f = { gx: 0, gy: 0, expr: 'neutral', next: 0, blinkAt: now + rand(500, 4000), blinkUntil: 0, sweep: -1 });
    f.shown = faceStep(name, f, now);
    for (const el of els) faceApply(el, f.shown);
    for (const at of [f.next, f.blinkUntil > now ? f.blinkUntil : f.blinkAt]) if (at > now) wake = Math.min(wake, at);
  }
  FACE.wake = wake;
}
const userAvatar = (size = 32) => h('span', { class: 'avatar avatar-user', style: { width: `${size}px`, height: `${size}px`, fontSize: `${Math.round(size * 0.4)}px` } }, t('You'));

function runsFor(pred) { return [...S.runs.values()].filter(pred); }
const profileBusy = name => runsFor(r => r.profile === name).length > 0;
function sessionBusy(profile, sid) {
  return runsFor(r => (r.profile === profile && r.session_id === sid) ||
    (r.origin && r.origin.profile === profile && r.origin.session_id === sid)).length > 0;
}
function hitlFor(view) {
  if (!view) return [];
  return S.hitl.filter(r => view.type === 'room'
    ? r.room_id === view.roomId
    : view.sid && ((r.profile === view.profile && r.session_id === view.sid) ||
      (r.origin && r.origin.profile === view.profile && r.origin.session_id === view.sid)));
}

// ====================================================================== toasts
function toast(text, kind = '', action) {
  const el = h('div', { class: `toast ${kind}` }, h('span', null, text));
  if (action) el.append(h('button', { type: 'button', onclick: () => { action.fn(); el.remove(); } }, action.label));
  $('#toasts').append(el);
  // The countdown pauses while the pointer is over the toast or focus is inside it (its button must not vanish
  // under the user), and starts again with the time that was left.
  let left = action ? 9000 : 4500, since = 0, timer = 0;
  const run = () => { since = Date.now(); timer = setTimeout(() => el.remove(), left); };
  const pause = () => { if (!timer) return; clearTimeout(timer); timer = 0; left = Math.max(1500, left - (Date.now() - since)); };
  const resume = () => { if (!timer && el.isConnected && !el.matches(':hover') && !el.contains(document.activeElement)) run(); };
  el.addEventListener('mouseenter', pause);
  el.addEventListener('focusin', pause);
  el.addEventListener('mouseleave', resume);
  el.addEventListener('focusout', () => setTimeout(resume, 0));
  run();
}

// ====================================================================== data loading
async function loadStatus() {
  try { S.status = await api('GET', '/api/status'); } catch { /* shown as disconnected */ }
  renderBrand();
  if (S.status && S.status.docker === null) setTimeout(loadStatus, 4000);  // docker probe still running
}
async function loadProfiles() { S.profiles = await api('GET', '/api/profiles'); renderSidebar(); }
async function loadRooms() { S.rooms = await api('GET', '/api/rooms'); renderSidebar(); }
async function loadChats() { S.chats = await api('GET', '/api/profiles/default/sessions?kinds=chat&limit=200'); renderSidebar(); }
async function loadHitl() {
  S.hitl = await api('GET', '/api/hitl');
  renderSidebar();
  renderHitlCards();
  renderTray();
  renderBrand();
  renderBoardLive();
}
async function loadActivity() {
  const a = await api('GET', '/api/activity');
  S.runs = new Map(a.runs.map(r => [runKey(r.profile, r.session_id), r]));
  S.drives = new Map(a.drives.map(d => [d.room_id, d]));
}
async function loadUsage() {
  try { S.usage = await api('GET', '/api/usage'); } catch { return; }
  const u = S.usage;
  $('#usage').textContent = t('{calls} calls · {tokens} tok · ${cost}', { calls: fmtNum(u.calls), tokens: fmtNum(u.prompt_tokens + u.completion_tokens), cost: u.cost_usd.toFixed(3) });
  $('#usage').title = t('Model usage (ledger): {calls} calls, {prompt} prompt tokens ({hit}% cache hits), {completion} completion tokens, ≈ ${cost}',
    { calls: u.calls, prompt: u.prompt_tokens, hit: Math.round(u.cache_hit_rate * 100), completion: u.completion_tokens, cost: u.cost_usd });
}
const refreshLists = debounce(() => { loadProfiles().catch(() => {}); loadRooms().catch(() => {}); loadChats().catch(() => {}); }, 250);
const refreshHitl = debounce(() => loadHitl().catch(() => {}), 80);
const refreshUsage = debounce(loadUsage, 800);

// ====================================================================== sidebar
function renderBrand() {
  const st = S.status;
  const sub = $('#brand-sub');
  if (!st) sub.textContent = t('offline');
  else {
    sub.replaceChildren(`${PROVIDER_NAMES[st.provider] || st.provider} · ${String(st.model || '?').replace(/^deepseek-/, '')}`);
    if (!st.api_key_set) sub.append(' · ', h('span', { class: 'warn' }, t('no API key')));
  }
  const n = S.hitl.length;
  const badge = $('#hitl-badge');
  badge.classList.toggle('hidden', !n);
  badge.textContent = t('{n} waiting', { n });
  document.title = n ? `(${n}) PlanD` : 'PlanD';
}

/** A sidebar row: opens `hash` on click, Enter or Space (not when the key comes from a button inside it). */
const sideRow = (key, active, hash, ...kids) => h('div', {
  class: 'row' + (active ? ' active' : ''), role: 'button', tabindex: '0', 'aria-current': active ? 'page' : null, dataset: { key },
  onclick: () => go(hash),
  onkeydown: e => { if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); go(hash); } },
}, ...kids);

/** Rows of the sidebar lists by key, with the signature of what they show: a render rebuilds only the rows whose
 * signature changed (an event re-renders the sidebar, which can hold 200 chats with avatars). */
const SIDE_ROWS = new Map();  // list id -> Map(key -> {sig, el})
function keyedRows(listId, items, keyOf, sigOf, build) {
  const old = SIDE_ROWS.get(listId) || new Map();
  const next = new Map();
  const nodes = items.map(item => {
    const key = keyOf(item);
    const sig = JSON.stringify(sigOf(item));
    const hit = old.get(key);
    const el = hit && hit.sig === sig ? hit.el : build(item);
    next.set(key, { sig, el });
    return el;
  });
  SIDE_ROWS.set(listId, next);
  return nodes;
}

const renderSidebar = rafOnce(() => {
  // the lists are rebuilt: keep keyboard focus on the same row (or its delete button)
  const a = document.activeElement, fRow = a && a.closest ? a.closest('.side-pane .row[data-key]') : null;
  const fKey = fRow && fRow.dataset.key, fDel = !!(fRow && a.classList.contains('row-del'));
  $$('.side-tabs .tab').forEach(tab => {
    const on = tab.dataset.tab === S.tab;
    tab.classList.toggle('active', on);
    tab.setAttribute('aria-selected', String(on));
    tab.tabIndex = on ? 0 : -1;  // one tab stop for the tab list; arrow keys move between the tabs
  });
  $('#side-chats').classList.toggle('hidden', S.tab !== 'chats');
  $('#side-bots').classList.toggle('hidden', S.tab !== 'bots');
  const v = C && C.view;

  // chats
  const chatList = $('#chat-list');
  const chatState = s => ({
    active: !!(v && v.type === 'chat' && v.sid === s.id),
    busy: sessionBusy('default', s.id),
    waiting: hitlFor({ type: 'chat', profile: 'default', sid: s.id }).length,
  });
  syncChildren(chatList, S.chats.length ? keyedRows('chats', S.chats, s => s.id, s => {
    return [chatState(s), s.title, s.preview ? s.preview.text : null, relTime(s.updated), !!s.interrupted];
  }, s => {
    const { active, busy, waiting } = chatState(s);
    return sideRow(`chat:${s.id}`, active, `#/chat/${enc(s.id)}`,
      h('div', { class: 'row-main' },
        h('div', { class: 'row-title' }, h('span', { class: 't' }, s.title || t('New chat'))),
        h('div', { class: 'row-sub' }, s.preview ? s.preview.text : t('No messages yet'))),
      h('div', { class: 'row-meta' }, h('span', { class: 'row-time' }, relTime(s.updated)),
        waiting ? h('span', { class: 'dot need', title: t('Waiting for you') }) : busy ? h('span', { class: 'dot busy', title: t('Working') })
          : s.interrupted ? h('span', { class: 'pill pill-amber', title: t('Interrupted — open it to resume') }, t('interrupted')) : null),
      iconBtn('trash', t('Delete chat'), e => { e.stopPropagation(); deleteChat(s); }, 'row-del'));
  }) : [h('div', { class: 'list-empty' }, t('No chats yet. Say hello to get started.'))]);
  $('#chat-count').textContent = S.chats.length ? String(S.chats.length).padStart(2, '0') : '';

  // bots
  const botList = $('#bot-list');
  const roster = bots();
  const botState = p => {
    const busy = profileBusy(p.name);
    return {
      active: !!(v && v.type === 'bot' && v.profile === p.name),
      waiting: S.hitl.filter(r => r.profile === p.name).length,
      busy,
      working: busy ? workingText(p.name) : '',
      preview: p.preview ? (p.preview.role === 'user' ? t('You: {text}', { text: p.preview.text }) : p.preview.text) : (tsExact(p.description) || t('No messages yet')),
      time: p.preview ? relTime(p.preview.created) : '',
    };
  };
  const botRows = roster.length ? keyedRows('bots', roster, p => p.name, p => [botState(p), p.title, p.avatar, p.bot_chat_status], p => {
    const { active, waiting, busy, preview } = botState(p);
    return sideRow(`bot:${p.name}`, active, `#/bot/${enc(p.name)}`,
      avatar(p, 34, busy),
      h('div', { class: 'row-main' },
        h('div', { class: 'row-title' }, h('span', { class: 't' }, p.title), h('span', { class: 'handle' }, `@${p.name}`)),
        h('div', { class: 'row-sub' }, busy ? workingText(p.name) : preview)),
      h('div', { class: 'row-meta' }, h('span', { class: 'row-time' }, p.preview ? relTime(p.preview.created) : ''),
        waiting ? h('span', { class: 'pill pill-warn' }, waiting)
          : !busy && p.bot_chat_status === 'interrupted' ? h('span', { class: 'pill pill-amber', title: t('Bot Chat was interrupted — open it to resume') }, t('interrupted')) : null));
  }) : null;
  if (botRows) syncChildren(botList, botRows);
  else botList.replaceChildren(h('div', { class: 'list-empty' }, t('No bots yet. A bot is an agent with its own identity, memory and workspace.'), ' ',
    h('button', { type: 'button', class: 'link-btn', onclick: templatesDialog }, t('Add a ready-made team'))));

  // groups
  const groupList = $('#group-list');
  const roomState = r => ({
    active: !!(v && v.type === 'room' && v.roomId === r.id),
    needs: !!(r.needs_you || S.hitl.some(x => x.room_id === r.id)),
    driving: S.drives.has(r.id),
  });
  syncChildren(groupList, S.rooms.length ? keyedRows('rooms', S.rooms, r => r.id, r => [roomState(r), r.name, r.members.length,
    (r.member_info || []).slice(0, 3).map(m => [m.name, m.title, m.avatar]), r.preview, relTime(r.updated)], r => {
    const { active, needs, driving } = roomState(r);
    const members = (r.member_info || []).slice(0, 3);
    const preview = r.preview ? (r.preview.speaker === 'user' ? t('You: {text}', { text: r.preview.text }) : `@${r.preview.speaker}: ${r.preview.text}`)
      : plural(r.members.length, '{n} member', '{n} members');
    return sideRow(`room:${r.id}`, active, `#/room/${enc(r.id)}`,
      h('span', { class: 'stack' }, members.map(m => avatar(m, 24))),
      h('div', { class: 'row-main' },
        h('div', { class: 'row-title' }, h('span', { class: 't' }, r.name), h('span', { class: 'handle' }, `${r.members.length}`)),
        h('div', { class: 'row-sub' }, driving ? t('Team is working…') : preview)),
      h('div', { class: 'row-meta' }, h('span', { class: 'row-time' }, relTime(r.updated)),
        needs ? h('span', { class: 'pill pill-warn', title: t('Needs you') }, t('needs you')) : driving ? h('span', { class: 'dot busy' }) : null));
  }) : [h('div', { class: 'list-empty' }, t('No groups yet. Put bots in a room and give the team a goal.'))]);
  if (fKey && !(document.activeElement && document.activeElement.closest && document.activeElement.closest('.side-pane .row'))) {
    const row = $(`.side-pane .row[data-key="${CSS.escape(fKey)}"]`);
    const target = row && (fDel ? $('.row-del', row) : row);
    if (target) target.focus({ preventScroll: true });
  }
});

function workingText(name) {
  const r = runsFor(x => x.profile === name)[0];
  if (!r) return '';
  if (r.state === 'waiting') return t('Waiting for you…');
  if (r.state === 'writing') return t('Writing…');
  if (r.state === 'tool') return t('Running {tool}…', { tool: r.tool });
  return t('Thinking…');
}

async function deleteChat(s) {
  if (!confirm(t('Delete "{title}"? This removes its transcript.', { title: s.title || t('New chat') }))) return;
  try {
    await api('DELETE', `/api/profiles/default/sessions/${enc(s.id)}`);
    if (C && C.view.sid === s.id) go('#/chat');
    loadChats();
  } catch (e) { toast(e.message, 'error'); }
}

// ====================================================================== routing
function parseHash() {
  const parts = location.hash.replace(/^#\/?/, '').split('/').filter(Boolean).map(decodeURIComponent);
  switch (parts[0]) {
    case 'chat': return { type: 'chat', profile: 'default', sid: parts[1] || null };
    case 'bot': return parts[1] ? { type: 'bot', profile: parts[1], sid: null, thread: parts[2] || null } : null;
    case 'session': return parts[2] ? { type: 'session', profile: parts[1], sid: parts[2] } : null;
    case 'room': return parts[1] ? { type: 'room', roomId: parts[1], board: parts[2] === 'board' } : null;
    default: return null;
  }
}

function go(hash) {
  document.body.classList.remove('sidebar-open');
  if (location.hash === hash) route(); else location.hash = hash;
}

let routeSeq = 0;  // a newer route() supersedes one still waiting on the network
async function route() {
  document.querySelectorAll('dialog[open]').forEach(d => d.close());  // e.g. Back while a picker is open
  const seq = ++routeSeq, hash = location.hash;
  const stale = () => seq !== routeSeq || location.hash !== hash;
  const v = parseHash() || { type: 'chat', profile: 'default', sid: null };
  if (v.type === 'bot') {
    try {
      // a bot keeps one Bot Chat per working folder; #/bot/<name>/<session> opens a given one, else the latest
      const r = await api('GET', `/api/profiles/${enc(v.profile)}/bot-chat${v.thread ? `?session=${enc(v.thread)}` : ''}`);
      if (stale()) return;
      v.sid = r.session_id;
      v.threads = r.threads || [];
    } catch (e) {
      if (stale()) return;
      toast(e.status === 404 ? t('There is no bot @{name}', { name: v.profile }) : e.message, 'error');
      return go('#/chat');
    }
  }
  S.tab = v.type === 'chat' || (v.type === 'session' && v.profile === 'default') ? 'chats' : 'bots';
  if (v.type === 'room' && C && C.view.type === 'room' && C.view.roomId === v.roomId) return switchRoomMode(v.board);
  openView(v);
}

// ====================================================================== conversation
/** `keep` (from resync) carries the composer, folded sections and scroll position over a reload of the same view. */
function openView(view, keep = null) {
  if (P.forcePanel) { S.panelOpen = true; P.forcePanel = false; }  // e.g. a file link that opens another view's Files tab
  else if (isNarrow()) S.panelOpen = false;  // the panel is an overlay on narrow screens: start each view without it
  C = { view, lastId: 0, lastEventId: 0, callEls: new Map(), group: null, lastSpeaker: null, busy: false, interrupted: false,
    session: null, room: null, fetching: false, again: false, optimistic: null, seen: new Set(), empty: null,
    todos: [], planOpen: null, hint: null, streams: new Map(), attachments: [], pending: {},
    tasks: null, tasksError: null, taskOpen: new Set(), taskFlash: new Set(), boardEls: null, boardSig: '',
    more: false, firstId: null, olderEvents: [], earlierEl: null, loadingEarlier: false, box: null };
  if (keep) Object.assign(C, keep);
  $('#messages').replaceChildren();
  $('#hitl-cards').replaceChildren();
  $('#main').classList.remove('is-empty');
  closeMentions();
  Object.keys(PICKERS).forEach(k => closePicker(k, false));
  renderAttachments();
  setBoardMode();
  renderHead();
  renderSidebar();
  renderPanel({ keepScroll: !!keep });
  renderBanner();
  updateComposer();
  renderLive();
  renderPlan();
  renderBoard();
  if (view.type === 'room') { loadRoom(true); loadTasks(); }
  else if (view.sid) loadConv(true);
  else showEmpty();
  if (!keep && window.innerWidth > 760 && !view.board) $('#input').focus();
}

/** What a resync must not lose: what the user was composing, which sections were open, and where they had scrolled. */
function keepState(c) {
  const seen = new Map(), openDetails = new Set();
  $$('#messages details').forEach(d => { const k = detailsKey(d, seen); if (d.open) openDetails.add(k); });
  return { attachments: c.attachments, pending: c.pending, planOpen: c.planOpen, taskOpen: c.taskOpen,
    restore: { atBottom: nearBottom(), scrollTop: scroller().scrollTop, openDetails } };
}
function detailsKey(d, seen) {  // class + summary text + occurrence: stable across a reload of the same transcript
  const sum = d.querySelector('summary');
  const base = `${d.className}|${sum ? sum.textContent : ''}`;
  const n = (seen.get(base) || 0) + 1;
  seen.set(base, n);
  return `${base}|${n}`;
}
/** After the first load of a resynced view: reopen its sections and put the scroll position back. */
function restoreState(c) {
  const r = c.restore;
  c.restore = null;
  if (r.openDetails.size) { const seen = new Map(); $$('#messages details').forEach(d => { if (r.openDetails.has(detailsKey(d, seen))) d.open = true; }); }
  if (r.atBottom) scrollBottom(); else scroller().scrollTop = r.scrollTop;
}

function viewProfile() { return C && C.view.type !== 'room' ? profileOf(C.view.profile) : null; }

function renderHead() {
  const head = $('#conv-head');
  if (!C) return head.replaceChildren();
  const v = C.view;
  const actions = h('div', { class: 'head-actions' });
  let lead;
  let titles;
  if (v.type === 'room') {
    const room = C.room || S.rooms.find(r => r.id === v.roomId);
    const members = room ? room.member_info || [] : [];
    lead = h('span', { class: 'stack' }, members.slice(0, 4).map(m => avatar(m, 30)));
    const sub = h('div', { class: 'conv-sub' });
    members.forEach((m, i) => {
      if (i) sub.append(' · ');
      sub.append(`@${m.name}`);
      if (room && room.lead === m.name) sub.append(h('span', { class: 'lead', title: t('Lead') }, ' ★'));
    });
    if (room) sub.append(' \u00b7 ', folderChip(room.workspace, room.workspace_custom, t('shared folder'), () => pickRoomFolder(room)));
    titles = h('div', { class: 'titles' }, h('div', { class: 'conv-title' }, room ? room.name : t('Group')), sub);
    const open = C.tasks ? C.tasks.filter(x => OPEN_STATUSES.has(x.status)).length : 0;
    const mode = (board, label, extra) => h('button', {
      type: 'button', class: v.board === board ? 'on' : '', 'aria-pressed': String(v.board === board),
      onclick: () => go(`#/room/${enc(v.roomId)}${board ? '/board' : ''}`),
    }, label, extra);
    if (room && room.fast_mode) {
      actions.append(h('button', {
        type: 'button', class: 'fast-chip', title: t('Fast Mode is on: limited command time, one review per card. Click to turn it off.'),
        onclick: () => setFastMode(room, false),
      }, t('\u26a1 Fast Mode')));
    }
    actions.append(h('div', { class: 'seg view-seg', role: 'group', 'aria-label': t('Show') },
      mode(false, t('Chat')),
      mode(true, t('Board'), open ? h('span', { class: 'seg-n', title: plural(open, '{n} task not finished', '{n} tasks not finished') }, String(open)) : null)));
  } else {
    const p = viewProfile();
    lead = avatar(p, 34, sessionBusy(v.profile, v.sid));
    let title = p.title;
    let sub = `@${p.name}${p.model ? ' · ' + p.model : ''}`;
    if (v.type === 'chat') {
      title = (C.session && C.session.title) || t('New chat');
      sub = `${p.title} · ${t('single agent')}${p.model ? ' · ' + p.model : ''}`;
    } else if (v.type === 'bot') {
      sub = `@${p.name} · Bot Chat${p.description ? ' · ' + tsExact(p.description) : ''}`;
    } else if (C.session) {
      title = C.session.title || C.session.kind;
      sub = `@${p.name} · ${kindLabel(C.session.kind)}`;
    }
    const backend = p.missing ? null : h('span', { class: 'pill pill-backend', title: t('Execution backend: {name}', { name: BACKEND_HELP[p.backend_effective] || backendLabel(p) }) }, backendLabel(p));
    const chatLike = v.type === 'chat' || v.type === 'bot' || (v.type === 'session' && C.session && ['chat', 'bot_chat'].includes(C.session.kind));
    const fs = chatLike ? chatFolder() : null;
    titles = h('div', { class: 'titles' }, h('div', { class: 'conv-title' }, h('span', { class: 'conv-title-t' }, title), backend),
      h('div', { class: 'conv-sub' }, sub, fs ? [' \u00b7 ', folderChip(fs.path, fs.custom, t('@{name}’s workspace', { name: p.name }), pickChatFolder, fs.error)] : null));
    if (v.type === 'chat' && v.sid) {
      actions.append(iconBtn('edit', t('Rename chat'), renameChat), iconBtn('trash', t('Delete chat'), () => deleteChat({ id: v.sid, title: C.session && C.session.title })));
    }
    if (v.type === 'session' && p.bot) actions.append(h('button', { type: 'button', class: 'btn btn-ghost btn-sm', onclick: () => go(`#/bot/${enc(p.name)}`) }, t('Open Bot Chat')));
  }
  const key = keyLabel('mod+.');
  actions.append(iconBtn('panel', S.panelOpen ? t('Hide details ({key})', { key }) : t('Show details ({key})', { key }), togglePanel, S.panelOpen ? 'active' : ''));
  const menu = iconBtn(window.innerWidth <= 760 ? 'menu' : 'sidebar', t('Show sidebar ({key})', { key: keyLabel('mod+b') }), toggleSidebar, 'menu-btn');
  head.replaceChildren(menu, lead, titles, actions);
}

// ====================================================================== sidebar and panel layout
/** ⌘B and the sidebar buttons: on a phone the sidebar slides over the conversation; otherwise it collapses away. */
function toggleSidebar() {
  if (window.innerWidth <= 760) { document.body.classList.toggle('sidebar-open'); return; }
  setUi('sideCollapsed', !ui.sideCollapsed);
  if (!ui.sideCollapsed) $('#new-chat').focus({ preventScroll: true });
}

/** Drag (or arrow-key) resizing of the sidebar and the details panel: widths are clamped,
 *  persisted per browser, double-click resets; dragging the sidebar almost shut collapses it. */
function makeResizer(handle, { key, min, max, fromPointer, collapse }) {
  const live = w => document.documentElement.style.setProperty(key === 'sideWidth' ? '--side-w' : '--panel-w', `${w}px`);
  handle.addEventListener('pointerdown', e => {
    if (e.button !== 0) return;
    e.preventDefault();
    handle.setPointerCapture(e.pointerId);
    document.body.classList.add('resizing');
    let raw = ui[key];
    const move = ev => { raw = fromPointer(ev); live(Math.max(min, Math.min(max, raw))); };
    const up = () => {
      handle.removeEventListener('pointermove', move);
      handle.removeEventListener('pointerup', up);
      handle.removeEventListener('pointercancel', up);
      document.body.classList.remove('resizing');
      if (collapse && raw < min - 60) { live(ui[key]); setUi('sideCollapsed', true); return; }
      setUi(key, Math.round(Math.max(min, Math.min(max, raw))));
    };
    handle.addEventListener('pointermove', move);
    handle.addEventListener('pointerup', up);
    handle.addEventListener('pointercancel', up);
  });
  handle.addEventListener('dblclick', () => setUi(key, UI_DEFAULTS[key]));
  handle.addEventListener('keydown', e => {
    const step = e.shiftKey ? 48 : 16;
    const dir = { ArrowLeft: -1, ArrowRight: 1 }[e.key];
    if (!dir) return;
    e.preventDefault();
    const sign = key === 'panelWidth' ? -dir : dir;  // the panel grows to the left
    setUi(key, Math.max(min, Math.min(max, ui[key] + sign * step)));
  });
}

// --- Conversation folders (pland/workspace.py): a chat or group can work in a folder of the user's choice.
const baseName = path => String(path || '').replace(/\/+$/, '').split('/').pop() || path;

function chatFolder() {
  const s = C.session;
  if (s && s.workspace) return { path: s.workspace, custom: !!s.workspace_custom, error: s.workspace_error };
  if (C.pending.workspace) return { path: C.pending.workspace, custom: true };
  return { path: '', custom: false };
}

function folderChip(path, custom, defaultLabel, onclick, error) {
  return h('button', {
    type: 'button', class: `folder-chip${custom ? ' custom' : ''}${error ? ' missing' : ''}`, onclick,
    title: `${error || (custom ? path : path ? t('{label}: {path}', { label: defaultLabel, path }) : defaultLabel)}\n${t('Click to choose the folder this conversation works in.')}`,
  }, h('span', { class: 'folder-ico', html: ICON.folder }), custom ? baseName(path) : defaultLabel);
}

async function folderDialog({ title, subtitle, current, custom, resetLabel, onPick, submitLabel, secondary, threads }) {
  let recent = [];
  try { recent = await api('GET', '/api/workspaces/recent'); } catch { /* optional */ }
  let state = null;
  let dlg = null;
  const input = h('input', { type: 'text', value: current || '', placeholder: '/Users/you/projects/app', spellcheck: 'false', autocomplete: 'off' });
  const note = h('div', { class: 'help folder-note' });
  const list = h('div', { class: 'dir-list' });
  const dirRow = (label, path) => h('div', {
    class: 'fs-row dir', role: 'button', tabindex: '0', onclick: () => load(path),
    onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); load(path); } },
  }, h('span', { class: 'fs-icon', html: ICON.folder }), h('span', { class: 'fs-name' }, label));
  const submit = () => dlg && dlg.querySelector('button[type=submit]');
  async function load(path) {
    try {
      state = await api('GET', `/api/fs/dirs?path=${enc(path)}`);
    } catch (e) {
      note.textContent = e.message;
      note.classList.add('bad');
      return;
    }
    input.value = state.path;
    note.textContent = state.usable ? t('Work in {path}', { path: state.path }) : ts(state.reason);
    note.classList.toggle('bad', !state.usable);
    if (submit()) submit().disabled = !state.usable;
    list.replaceChildren(...[state.parent ? dirRow('..', state.parent) : null, ...state.dirs.map(d => dirRow(d.name, d.path))].filter(Boolean));
    if (!state.dirs.length) list.append(h('div', { class: 'p-empty' }, t('No sub-folders.')));
  }
  input.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); load(input.value.trim()); } });
  const second = secondary ? h('button', { type: 'button', class: 'btn btn-sm folder-second', onclick: async () => {
    if (!state || !state.usable) { toast(state ? ts(state.reason) : t('Choose a folder first'), 'error'); return; }
    try { await secondary.fn(state.path); dlg.close(); } catch (e) { toast(e.message, 'error'); }
  } }, secondary.label) : null;
  dlg = dialog({
    title, subtitle, submitLabel: submitLabel || t('Use this folder'),
    body: h('div', null,
      threads && threads.items.length ? h('div', { class: 'field' }, h('div', { class: 'label' }, threads.label),
        h('div', { class: 'thread-list' }, threads.items)) : null,
      recent.length ? h('div', { class: 'field' }, h('div', { class: 'label' }, t('Recent')),
        h('div', { class: 'recent-dirs' }, recent.map(r => h('button', { type: 'button', class: 'chip-btn', title: r, onclick: () => load(r) }, baseName(r))))) : null,
      h('div', { class: 'field' }, h('div', { class: 'label' }, t('Folder')),
        h('div', { class: 'path-row' }, input, h('button', { type: 'button', class: 'btn btn-sm', onclick: () => load(input.value.trim()) }, t('Go')))),
      note, list, second,
      custom ? h('button', { type: 'button', class: 'link-btn folder-reset', onclick: async () => {
        try { await onPick(''); dlg.close(); } catch (e) { toast(e.message, 'error'); }
      } }, resetLabel) : null),
    onSubmit: async () => {
      if (!state || !state.usable) throw new Error(state ? ts(state.reason) : t('Choose a folder first'));
      await onPick(state.path);
    },
  });
  load(current || '');
}

function pickChatFolder() {
  const c = C;
  const p = viewProfile();
  const cur = chatFolder();
  const isBot = c.view.type === 'bot' || (C.session && C.session.kind === 'bot_chat');
  const done = path => {
    if (c !== C) return;
    renderHead();
    if (S.panelOpen) renderPanel();
    toast(path ? t('This conversation works in {path}, from the next message.', { path }) : t('This conversation works in @{name}’s own workspace.', { name: p.name }));
  };
  const move = async path => {  // keep this conversation (and its context), work in another folder
    if (!c.view.sid) c.pending.workspace = path || null;
    else c.session = await api('PATCH', `/api/profiles/${enc(c.view.profile)}/sessions/${enc(c.view.sid)}`, { workspace: path });
    done(path);
  };
  if (isBot) {
    // A bot has one Bot Chat per folder: picking a folder opens that folder's chat (its own context; the
    // bot's memory, experience and skills are shared), so two projects never mix in one conversation.
    const open = async folder => {
      const r = await api('GET', `/api/profiles/${enc(p.name)}/bot-chat?folder=${enc(folder)}`);
      go(`#/bot/${enc(p.name)}/${enc(r.session_id)}`);
    };
    const threads = (c.view.threads || []).map(th => h('button', {
      type: 'button', class: `chip-btn${th.id === c.view.sid ? ' on' : ''}`, title: th.workspace || t('@{name}’s private workspace', { name: p.name }),
      onclick: () => { document.querySelectorAll('dialog[open]').forEach(d => d.close()); go(`#/bot/${enc(p.name)}/${enc(th.id)}`); },
    }, th.workspace ? baseName(th.workspace) : t('private workspace')));
    return folderDialog({
      title: t('@{name}’s folders', { name: p.name }),
      subtitle: t('@{name} keeps one Bot Chat per folder, each with its own conversation; its memory, experience and skills are shared across them. Choose a folder to switch to its chat (created on first use).', { name: p.name }),
      current: cur.custom ? cur.path : '', custom: cur.custom, resetLabel: t('Back to @{name}’s home Bot Chat (private workspace)', { name: p.name }),
      submitLabel: t('Switch to this folder’s chat'), onPick: open,
      secondary: { label: t('Move this conversation here instead (keep its context)'), fn: move },
      threads: threads.length > 1 || cur.custom ? { label: t('@{name}’s Bot Chats', { name: p.name }), items: threads } : null,
    });
  }
  return folderDialog({
    title: t('Folder for this conversation'),
    subtitle: t('@{name} reads, writes and runs commands in this folder (sandboxed to it), from the next message on. It is stored with the conversation, so it stays when the conversation is resumed; the conversation keeps its context.', { name: p.name }),
    current: cur.custom ? cur.path : '', custom: cur.custom, resetLabel: t('Use @{name}’s own workspace instead', { name: p.name }),
    submitLabel: t('Use for this chat'), onPick: move,
    secondary: c.view.sid ? { label: t('Start a new chat in this folder instead'), fn: async path => {
      history.pushState(null, '', '#/chat');
      openView({ type: 'chat', profile: 'default', sid: null });
      C.pending.workspace = path;
      renderHead();
    } } : null,
  });
}

function pickRoomFolder(room) {
  const c = C;
  folderDialog({
    title: t('Shared folder for this group'),
    subtitle: t('Every member sees this folder as shared/ and works on its files; their other files stay private.'),
    current: room.workspace_custom ? room.workspace : '', custom: room.workspace_custom, resetLabel: t('Use the group\u2019s default shared folder'),
    submitLabel: t('Use for this group'),
    secondary: { label: t('Start a new group with the same bots for this folder'), fn: async path => {
      let name = `${room.name} \u00b7 ${baseName(path)}`;
      for (let i = 2; S.rooms.some(r => r.name === name); i++) name = `${room.name} \u00b7 ${baseName(path)} ${i}`;
      const r = await api('POST', '/api/rooms', { name, members: room.members, lead: room.lead || null });
      await api('PATCH', `/api/rooms/${enc(r.id)}`, { workspace: path });
      await loadRooms();
      go(`#/room/${enc(r.id)}`);
      toast(t('Created {name}: the same bots, working in {path}.', { name, path }));
    } },
    onPick: async path => {
      const r = await api('PATCH', `/api/rooms/${enc(room.id)}`, { workspace: path });
      if (c === C) { C.room = r; renderHead(); if (S.panelOpen) renderPanel(); }
      loadRooms();
      if (c === C) loadRoom();
      toast(path ? t('The group now shares {path}; every member is told at its next turn.', { path }) : t('The group uses its default shared folder again.'));
    },
  });
}

const kindLabel = k => ({ chat: t('chat'), bot_chat: 'Bot Chat', room_member: t('group work log'), delegation: t('delegated task'), subagent: t('subagent'), eval: t('evaluation') }[k] || k);

async function renameChat() {
  const cur = (C.session && C.session.title) || '';
  const title = prompt(t('Rename chat'), cur);
  if (title == null || !title.trim() || title.trim() === cur) return;
  try {
    C.session = await api('PATCH', `/api/profiles/${enc(C.view.profile)}/sessions/${enc(C.view.sid)}`, { title: title.trim() });
    renderHead();
    loadChats();
  } catch (e) { toast(e.message, 'error'); }
}

function renderBanner() {
  const b = $('#banner');
  const st = S.status;
  if (st && !st.api_key_set) {
    b.replaceChildren(h('span', null, t('No API key for {provider} yet: agents cannot run until one is added.', { provider: PROVIDER_NAMES[st.provider] || st.provider })),
      h('button', { type: 'button', class: 'btn btn-sm', onclick: () => openSettings('model') }, t('Add key')));
    b.classList.remove('hidden');
    return;
  }
  if (C && C.view.type !== 'room' && C.interrupted && !C.busy && !sessionBusy(C.view.profile, C.view.sid) &&
      !(C.session && C.session.kind === 'room_member')) {
    b.replaceChildren(h('span', null, t('This conversation was interrupted (the server stopped while it was working). Resume continues from where it stopped — unfinished tool calls run first, and questions are asked again.')),
      h('button', { type: 'button', class: 'btn btn-sm', onclick: resumeRun }, t('Resume')));
    b.classList.remove('hidden');
    return;
  }
  b.classList.add('hidden');
}

async function resumeRun() {
  try {
    await api('POST', `/api/profiles/${enc(C.view.profile)}/sessions/${enc(C.view.sid)}/resume`);
    refreshLists();
    C.busy = true;
    C.interrupted = false;
    renderBanner();
    updateComposer();
    renderLive();
  } catch (e) { toast(e.message, 'error'); }
}

/** Numbered starter lines under an empty conversation; clicking one puts it in the message box. */
function starters(list) {
  return h('ol', { class: 'starters' }, list.map((line, i) => h('li', null, h('button', {
    type: 'button', class: 'starter', onclick: () => { const el = $('#input'); el.value = line; autosize(); el.focus(); },
  }, h('span', { class: 'num' }, String(i + 1).padStart(2, '0')), h('span', { class: 't' }, line), h('span', { class: 'go', 'aria-hidden': 'true' }, t('use ↵'))))));
}

function showEmpty() {
  const box = $('#messages');
  if (C.empty || box.children.length) return;
  const v = C.view;
  let el;
  if (v.type === 'room') {
    const room = C.room || S.rooms.find(r => r.id === v.roomId) || { member_info: [] };
    const lead = room.lead ? `@${room.lead}` : t('the first bot you address');
    el = h('div', { class: 'empty' },
      h('div', { class: 'kicker' }, `${t('Group')} · ${plural((room.member_info || []).length, '{n} member', '{n} members')}`),
      h('span', { class: 'stack' }, (room.member_info || []).map(m => avatar(m, 40))),
      h('h1', null, room.name || t('Group')),
      h('p', null, t('Give the team a goal. Mention @name to address one bot, or write to everyone; {lead} leads, breaks the work down on the board and delegates to teammates.', { lead })));
  } else {
    const p = viewProfile();
    if (v.type === 'chat') {
      const st = S.status || {};
      el = h('div', { class: 'empty' },
        h('div', { class: 'wordmark', 'aria-label': 'PlanD' }, h('span', null, 'Plan'), h('span', { class: 'seal', 'aria-hidden': 'true' }, 'D')),
        h('p', null, t('One agent with files, code, web search and git, in the folder you choose. It asks when something is ambiguous, and before anything risky.')),
        h('div', { class: 'kicker', style: { marginTop: '14px' } }, t('Try')),
        starters([
          t('Write a Python script that prints the first 10 primes and run it'),
          t('Search the web for the latest Python release and summarise it in notes.md'),
          t('What do you remember about me?'),
        ]),
        h('div', { class: 'empty-meta' },
          st.model ? h('span', null, t('model'), ' ', h('b', null, st.model)) : null,
          h('span', null, t('thinking'), ' ', h('b', null, reasoningName(p.reasoning || 'default').toLowerCase())),
          h('span', null, t('sandbox'), ' ', h('b', null, backendLabel(p))),
          h('button', { type: 'button', class: 'link-btn', onclick: () => openSettings('model') }, t('change defaults'))));
    } else {
      el = h('div', { class: 'empty' },
        h('div', { class: 'kicker' }, v.type === 'bot' ? `Bot Chat · @${p.name}` : kindLabel((C.session && C.session.kind) || 'chat')),
        avatar(p, 56), h('h1', null, p.title),
        h('p', null, v.type === 'bot' ? `${t('Your private Bot Chat with @{name}.', { name: p.name })} ${tsExact(p.description) || ''}` : t('This session has no messages.')));
    }
  }
  C.empty = el;
  box.append(el);
  $('#main').classList.add('is-empty');
}

function clearEmpty() {
  if (C && C.empty) { C.empty.remove(); C.empty = null; }
  $('#main').classList.remove('is-empty');
}

const scroller = () => $('#scroller');
const nearBottom = () => { const s = scroller(); return s.scrollHeight - s.scrollTop - s.clientHeight < 120; };
function scrollBottom() { const s = scroller(); s.scrollTop = s.scrollHeight; }

async function loadConv(initial = false) {
  const c = C;
  if (!c || !c.view.sid || c.view.type === 'room') return;
  if (c.fetching) { c.again = true; return; }
  c.fetching = true;
  const stick = initial || nearBottom();
  const first = initial && !c.lastId;  // the first load gets the newest page; "Load earlier" fetches the rest
  try {
    const d = await api('GET', `/api/profiles/${enc(c.view.profile)}/sessions/${enc(c.view.sid)}/messages?after=${c.lastId}&events_after=${c.lastEventId}${first ? `&latest=${PAGE}` : ''}`);
    if (c !== C) return;
    c.session = d.session;
    c.busy = d.busy;
    c.interrupted = d.interrupted;
    c.todos = d.todos || [];
    let events = d.activity;
    if (first) {
      c.more = !!d.more;
      c.firstId = d.first_id;
      if (c.more && d.items.length) {  // activity older than this page waits for the page it belongs to
        const t0 = d.items[0].created;
        c.olderEvents = events.filter(e => e.created < t0);
        events = events.filter(e => e.created >= t0);
      }
    }
    for (const it of mergeByTime(d.items, events)) appendConvItem(it);
    renderEarlier();
    settleStreams(d.items.some(it => it.role === 'assistant') ? () => true : () => false);
    c.lastId = d.last_id;
    c.lastEventId = Math.max(c.lastEventId, d.last_event_id || 0);
    renderPlan();
    if (!c.busy && !sessionBusy(c.view.profile, c.view.sid)) markStaleTools();
    if (!$('#messages').children.length) showEmpty();
    renderHead();
    renderBanner();
    updateComposer();
    renderLive();
    renderHitlCards();
    if (c.restore) restoreState(c); else if (stick) scrollBottom();
  } catch (e) {
    if (c !== C) return;
    if (e.status === 404) { toast(t('That conversation no longer exists.')); go('#/chat'); } else toast(e.message, 'error');
  } finally {
    c.fetching = false;
    if (c.again && c === C) { c.again = false; loadConv(); }
  }
}
const refreshConv = debounce(() => loadConv(), 60);

// ---------------------------------------------------------------- earlier pages of a long transcript
const PAGE = 150;  // transcript records (group: messages) per page

/** The "Load earlier messages" button at the top of the transcript, while older messages exist. */
function renderEarlier() {
  const c = C;
  if (!c) return;
  if (!c.more) { if (c.earlierEl) { c.earlierEl.remove(); c.earlierEl = null; } return; }
  if (!c.earlierEl) c.earlierEl = h('div', { class: 'earlier' }, h('button', { type: 'button', class: 'btn btn-ghost btn-sm', onclick: () => loadEarlier() }));
  const btn = c.earlierEl.firstChild;
  btn.textContent = c.loadingEarlier ? t('Loading…') : t('Load earlier messages');
  btn.disabled = !!c.loadingEarlier;
  const box = $('#messages');
  if (box.firstChild !== c.earlierEl) box.prepend(c.earlierEl);
}

/** Fetch the page before the oldest one shown and put it on top, keeping what the user is reading in place. */
async function loadEarlier() {
  const c = C;
  if (!c || !c.more || c.loadingEarlier || !c.firstId) return;
  c.loadingEarlier = true;
  renderEarlier();
  const room = c.view.type === 'room';
  const path = room ? `/api/rooms/${enc(c.view.roomId)}/messages?before=${c.firstId}&latest=${PAGE}`
    : `/api/profiles/${enc(c.view.profile)}/sessions/${enc(c.view.sid)}/messages?before=${c.firstId}&latest=${PAGE}`;
  try {
    const d = await api('GET', path);
    if (c !== C) return;
    const page = h('div');
    const saved = { group: c.group, lastSpeaker: c.lastSpeaker };
    Object.assign(c, { box: page, group: null, lastSpeaker: null });  // render into `page`, as if it were the transcript
    try {
      if (room) d.messages.forEach(appendRoomMsg);
      else {
        let events = [];
        if (c.olderEvents && c.olderEvents.length) {
          const t0 = d.more && d.items.length ? d.items[0].created : -Infinity;
          events = c.olderEvents.filter(e => e.created >= t0);
          c.olderEvents = c.olderEvents.filter(e => e.created < t0);
        }
        mergeByTime(d.items, events).forEach(appendConvItem);
      }
    } finally {
      Object.assign(c, { box: null, ...saved });
    }
    c.firstId = d.first_id || c.firstId;
    c.more = !!d.more && !!d.first_id;
    const s = scroller(), fromBottom = s.scrollHeight - s.scrollTop;
    const box = $('#messages');
    const anchor = c.earlierEl && c.earlierEl.parentNode === box ? c.earlierEl.nextSibling : box.firstChild;
    const frag = document.createDocumentFragment();
    frag.append(...page.childNodes);
    box.insertBefore(frag, anchor);
    s.scrollTop = s.scrollHeight - fromBottom;
  } catch (e) {
    if (c === C) toast(e.message, 'error');
  } finally {
    c.loadingEarlier = false;
    if (c === C) renderEarlier();
  }
}

/** Interleave activity rows (sorted by time) into transcript items without reordering either list. */
function mergeByTime(items, events) {
  if (!events || !events.length) return items;
  const out = [];
  let j = 0;
  for (const it of items) {
    while (j < events.length && events[j].created < it.created) out.push(events[j++]);
    out.push(it);
  }
  return out.concat(events.slice(j));
}

function appendConvItem(it) {
  clearEmpty();
  const box = C.box || $('#messages');
  if (it.role === 'event') {
    const info = activityInfo(it);
    // Inside the open assistant turn (next to the tool card it belongs to), else as its own row.
    if (info) (C.group ? C.group.body : box).append(activityRow(info, it.created));
    return;
  }
  if (it.role === 'user') {
    if (C.optimistic && !C.box) { C.optimistic.remove(); C.optimistic = null; }
    C.group = null;
    if (it.kind === 'note') box.append(h('div', { class: 'note', title: fullTime(it.created) }, it.content.replace(/^\[system\]\s*/, '')));
    else if (it.kind === 'room_turn') {
      box.append(h('details', { class: 'turn' }, h('summary', null, `${it.turn_role ? t('Group update for this turn (as {role})', { role: it.turn_role }) : t('Group update for this turn')} · ${clock(it.created)}`), h('pre', null, it.content)));
    } else if (it.kind === 'agent_message') {
      const p = profileOf(it.from_agent);
      box.append(h('div', { class: 'msg', title: fullTime(it.created) }, avatar(p, 30),
        h('div', { class: 'msg-main msg-from' }, h('div', { class: 'label' }, t('Message from @{name}', { name: p.name })),
          h('div', { class: 'md', html: md(it.content.replace(/^Message from[^\n]*\n/, '')) }))));
    } else {
      box.append(h('div', { class: 'msg msg-user', title: fullTime(it.created) }, h('div', { class: 'bubble' }, it.content)));
    }
    if (it.recalled && it.recalled.length) {
      box.append(activityRow({ icon: '↺', text: plural(it.recalled.length, 'recalled {n} past experience for this task', 'recalled {n} past experiences for this task'), more: it.recalled }, it.created));
    }
    return;
  }
  if (it.role === 'assistant') {
    const g = assistantGroup(it.created);
    if (it.reasoning) g.body.append(h('details', { class: 'reasoning' }, h('summary', null, t('Thinking')), h('div', null, it.reasoning)));
    if (it.content) {
      const cls = 'md' + (it.error ? ' md-error' : '') + (it.cancelled ? ' md-muted' : '');
      g.body.append(h('div', { class: cls, html: md(it.content) }));
    }
    for (const call of it.tool_calls) g.body.append(toolCard(call));
    return;
  }
  if (it.role === 'tool') {
    const el = C.callEls.get(it.tool_call_id);
    if (el) updateToolCard(el, it);
    else assistantGroup(it.created).body.append(toolCard({ id: it.tool_call_id, name: it.name, args: '', ...it }));
  }
}

function assistantGroup(ts) {
  if (C.group) return C.group;
  const p = viewProfile();
  const body = h('div', { class: 'msg-body' });
  const el = h('div', { class: 'msg' }, avatar(p, 30),
    h('div', { class: 'msg-main' },
      h('div', { class: 'msg-name' }, p.title, h('span', { class: 'handle' }, `@${p.name}`), h('span', { class: 'time' }, clock(ts))),
      body));
  (C.box || $('#messages')).append(el);
  C.group = { el, body };
  return C.group;
}

function parseArgs(raw) {
  if (raw && typeof raw === 'object') return raw;
  try { return JSON.parse(raw || '{}'); } catch { return null; }
}

function argSummary(name, raw) {
  const a = parseArgs(raw);
  if (!a || typeof a !== 'object') return String(raw || '').slice(0, 120);
  if (name === 'delegate_task' && Array.isArray(a.tasks)) return a.tasks.map(x => (x.to ? `@${String(x.to).replace(/^@/, '')}` : t('subagent')) + ': ' + (x.goal || '')).join(' · ');
  if (name === 'todo') {
    if (!Array.isArray(a.todos)) return t('read the plan');
    return a.merge ? plural(a.todos.length, 'update {n} item', 'update {n} items') : plural(a.todos.length, 'write {n} item', 'write {n} items');
  }
  const pick = a.command ?? a.path ?? a.query ?? a.url ?? a.question ?? a.goal ?? a.message ?? a.name ?? a.repo ?? a.code;
  if (pick != null) {
    const s = String(pick).split('\n')[0];
    const extra = a.target && name !== 'memory' ? `@${a.target} ` : a.action ? `${a.action} ` : '';
    return (extra + s).slice(0, 160);
  }
  const s = JSON.stringify(a);
  return s === '{}' ? '' : s.slice(0, 160);
}

function prettyArgs(raw) {
  const a = parseArgs(raw);
  if (a == null) return String(raw || '');
  const keys = Object.keys(a);
  if (keys.length === 1 && typeof a[keys[0]] === 'string' && a[keys[0]].includes('\n')) return `${keys[0]}:\n${a[keys[0]]}`;
  return JSON.stringify(a, null, 2);
}

function toolCard(call) {
  const state = h('span', { class: 'tool-state' });
  const arg = h('span', { class: 'tool-arg' }, argSummary(call.name, call.args));
  const result = h('pre', null);
  const det = h('details', { class: 'tool' },
    h('summary', null,
      h('span', { class: 'tool-icon', html: ICON.tool }),
      h('span', { class: 'tool-name' }, call.name),
      arg,
      state),
    h('div', { class: 'tool-body' },
      call.args ? [h('div', { class: 'tool-label' }, t('Arguments')), h('pre', null, prettyArgs(call.args))] : null,
      h('div', { class: 'tool-label' }, t('Result')), result));
  const el = { det, state, result, arg, name: call.name, args: call.args };
  if (call.id) C.callEls.set(call.id, el);
  updateToolCard(el, call);
  return det;
}

function updateToolCard(el, r) {
  if (r.result == null) {
    el.det.classList.add('running');
    el.state.replaceChildren(h('span', { class: 'spinner' }), t('running'));
    el.result.textContent = t('Waiting for the result…');
    return;
  }
  el.det.classList.remove('running', 'stale');
  el.det.classList.toggle('ok', !!r.ok);
  el.det.classList.toggle('err', !r.ok);
  el.state.textContent = `${r.ok ? '✓' : t('✗ error')}${r.duration != null ? ' · ' + fmtDur(r.duration) : ''}`;
  el.result.textContent = r.result || t('(empty)');
  const path = r.ok && FILE_TOOLS.has(el.name) ? writtenPath(el.args, r.result) : null;
  if (path && !el.arg.querySelector('.file-link')) {
    el.arg.replaceChildren(h('a', { class: 'file-link', href: '#', title: t('Open in Files'),
      onclick: e => { e.preventDefault(); e.stopPropagation(); openInFiles(path); } }, path));
  }
}

/** Tools whose result is a file the user may want to look at (the path opens it in the Files tab). */
const FILE_TOOLS = new Set(['write_file', 'edit_file']);
function writtenPath(args, result) {
  const m = /^(?:Created|Updated|Edited) (.+?) \(/.exec(result || '');  // the tool reports the workspace-relative path
  if (m) return m[1];
  const a = parseArgs(args);
  const p = a && typeof a.path === 'string' ? a.path.trim().replace(/^\.\//, '') : '';
  return p && !/^[/~]/.test(p) && !p.split('/').includes('..') ? p : null;
}

function markStaleTools() {
  for (const el of C.callEls.values()) {
    if (el.det.classList.contains('running')) {
      el.det.classList.replace('running', 'stale');
      el.state.textContent = t('no result');
      el.result.textContent = t('This call did not finish (the run was stopped or interrupted).');
    }
  }
}

function markToolRunning(callId, tool) {
  const el = C && C.callEls.get(callId);
  if (el && !el.det.classList.contains('ok') && !el.det.classList.contains('err')) updateToolCard(el, { result: null });
  if (!el && tool) renderLive();
}

// ====================================================================== rooms
async function loadRoom(initial = false) {
  const c = C;
  if (!c || c.view.type !== 'room') return;
  if (c.fetching) { c.again = true; return; }
  c.fetching = true;
  const stick = initial || nearBottom();
  const first = initial && !c.lastId;
  try {
    const d = await api('GET', `/api/rooms/${enc(c.view.roomId)}/messages?after=${c.lastId}${first ? `&latest=${PAGE}` : ''}`);
    if (c !== C) return;
    c.room = d.room;
    if (first) { c.more = !!d.more; c.firstId = d.first_id; }
    for (const m of d.messages) appendRoomMsg(m);
    renderEarlier();
    const posted = new Set(d.messages.filter(m => m.kind === 'message').map(m => m.speaker));
    settleStreams(st => posted.has(st.profile));
    c.lastId = d.last_id;
    if (!$('#messages').children.length) showEmpty();
    if (initial) { renderHead(); renderPanel(); }
    updateComposer();
    renderLive();
    renderPlan();
    renderHitlCards();
    if (c.restore) restoreState(c); else if (stick) scrollBottom();
  } catch (e) {
    if (c !== C) return;
    if (e.status === 404) { toast(t('That group no longer exists.')); go('#/chat'); } else toast(e.message, 'error');
  } finally {
    c.fetching = false;
    if (c.again && c === C) { c.again = false; loadRoom(); }
  }
}
const refreshRoom = debounce(() => loadRoom(), 50);

function appendRoomMsg(m) {
  if (C.seen.has(m.id)) return;
  C.seen.add(m.id);
  clearEmpty();
  const box = C.box || $('#messages');
  if (m.kind === 'system') {
    box.append(h('div', { class: 'note', title: fullTime(m.created) }, ts(m.content)));
    C.lastSpeaker = null;
    return;
  }
  if (m.kind === 'activity') {
    const p = profileOf(m.speaker);
    const [first, ...rest] = m.content.split('\n');
    const cls = first.startsWith('✓') ? 'ok' : first.startsWith('✗') || first.startsWith('⚠') ? 'err' : first.startsWith('→') ? 'start' : '';
    const line = h('div', { class: 'a-line' }, h('span', { class: 'who' }, `@${m.speaker} `), ts(first));
    const main = rest.join('\n').trim()
      ? h('details', { class: 'a-main' }, h('summary', null, line), h('div', { class: 'a-more' }, rest.join('\n').trim()))
      : h('div', { class: 'a-main' }, line);
    box.append(h('div', { class: `activity ${cls}`, title: fullTime(m.created) }, avatar(p, 18), main, h('span', { class: 'handle' }, clock(m.created))));
    C.lastSpeaker = null;
    return;
  }
  if (m.speaker === 'user') {
    box.append(h('div', { class: 'msg msg-user', title: fullTime(m.created) }, h('div', { class: 'bubble' }, m.content)));
    C.lastSpeaker = 'user';
    return;
  }
  const p = profileOf(m.speaker);
  const isLead = C.room && C.room.lead === m.speaker;
  const cont = C.lastSpeaker === m.speaker;
  box.append(h('div', { class: 'msg' + (cont ? ' cont' : ''), title: fullTime(m.created) }, avatar(p, 30),
    h('div', { class: 'msg-main' },
      cont ? null : h('div', { class: 'msg-name' }, p.title, h('span', { class: 'handle' }, `@${m.speaker}`),
        isLead ? h('span', { class: 'star', title: t('Lead') }, '★') : null, h('span', { class: 'time' }, clock(m.created))),
      h('div', { class: 'md', html: md(m.content) }))));
  C.lastSpeaker = m.speaker;
}

// ====================================================================== live status
function relevantRuns() {
  if (!C) return [];
  const v = C.view;
  if (v.type === 'room') return runsFor(r => r.room_id === v.roomId);
  if (!v.sid) return [];
  return runsFor(r => (r.profile === v.profile && r.session_id === v.sid) ||
    (r.origin && r.origin.profile === v.profile && r.origin.session_id === v.sid));
}

function runText(r) {
  const text = runStateText(r);
  const parts = [text];
  if (r.iteration) parts.push(t('step {n}', { n: r.iteration }));
  if (r.started) parts.push(t('{n}s', { n: Math.max(0, Math.floor(Date.now() / 1000 - r.started)) }));
  return parts.join(' · ');
}

function runStateText(r) {
  const who = r.profile;
  if (r.state === 'waiting') return t('@{who} is waiting for you', { who });
  if (r.state === 'writing') return t('@{who} is writing…', { who });
  if (r.state === 'tool') {
    if (r.tool === 'delegate_task') return t('@{who} is waiting on teammates', { who });
    if (r.tool === 'message_agent') return t('@{who} is messaging a teammate', { who });
    return t('@{who} is running {tool}…', { who, tool: r.tool });
  }
  return t('@{who} is thinking…', { who });
}

const renderLive = rafOnce(() => {
  const el = $('#live');
  if (!C) { el.dataset.sig = ''; return el.classList.add('hidden'); }
  const runs = relevantRuns().sort((a, b) => (a.depth || 0) - (b.depth || 0));
  let texts = runs.map(runText);
  if (C.view.type === 'room' && S.drives.has(C.view.roomId) && !texts.length) texts = [t('The team is working…')];
  if (C.view.type !== 'room' && !texts.length && C.busy) texts = [t('Working…')];
  const hint = C.hint && C.hint.until > Date.now() ? C.hint : null;
  if (!texts.length && !hint) { el.dataset.sig = ''; return el.classList.add('hidden'); }
  // an aria-live region announces every rebuild: touch it only when what it says (or its icon) changes
  const sig = JSON.stringify([texts, hint && [hint.icon, hint.cls, hint.text]]);
  if (el.dataset.sig !== sig) {
    el.dataset.sig = sig;
    el.replaceChildren(texts.length ? h('span', { class: 'spinner' }) : h('span', { class: 'live-icon', 'aria-hidden': 'true' }, hint.icon),
      h('span', { class: 'txt' }, texts.join(' · '),
        hint ? h('span', { class: 'live-hint' + (hint.cls ? ' ' + hint.cls : '') }, (texts.length ? ' · ' : '') + hint.text) : null));
  }
  el.classList.remove('hidden');
});

// ====================================================================== streaming reply (assistant.delta)
/* While a model response is generated the core publishes batched `assistant.delta` events (content
 * or reasoning, per loop iteration). The open conversation shows them in an in-progress bubble kept
 * at the end of the transcript: fragments are appended to text nodes (no re-rendering). Once the run
 * moves on (assistant.message / tool.started / run.finished) the bubble is marked done and replaced
 * by the stored message on the next fetch (or dropped after a short grace period). */
const PASS_TOKENS = ['[pass]', 'pass', '[silent]', 'no_reply', '[no_reply]'];
const STREAM_GRACE_MS = 3000;

function streamTarget(ev) {
  if (!C) return false;
  const v = C.view;
  if (v.type === 'room') {  // a member's own turn (not its delegates), which ends up as a room message
    if (!ev.room_id || ev.room_id !== v.roomId) return false;
    const run = S.runs.get(runKey(ev.profile, ev.session_id));
    return !run || !run.role || run.role === 'main';
  }
  return !!v.sid && ev.profile === v.profile && ev.session_id === v.sid;
}

function createStream(ev) {
  const room = C.view.type === 'room';
  const p = room ? profileOf(ev.profile) : viewProfile();
  const box = $('#messages');
  const cont = !room && C.group && box.lastElementChild === C.group.el;  // continues the current turn
  const content = document.createTextNode('');
  const body = h('div', { class: 'msg-body' }, h('div', { class: 'stream-text' }, content));
  const el = h('div', { class: 'msg msg-stream hidden' + (cont ? ' cont' : ''), 'aria-live': 'off' }, avatar(p, 30),
    h('div', { class: 'msg-main' },
      cont ? null : h('div', { class: 'msg-name' }, p.title, h('span', { class: 'handle' }, `@${p.name}`), h('span', { class: 'time' }, t('writing…'))),
      body));
  box.append(el);
  return { profile: ev.profile, iteration: ev.iteration, el, body, content, text: '', reasoning: null, room, done: false };
}

function streamVisible(st) {
  const text = st.text.trim().toLowerCase().replace(/[ .]+$/, '');
  if (!text) return !!st.reasoning;
  // a room member that has nothing to add answers [PASS]; that is never posted, so never shown
  return !(st.room && (text.startsWith('[pass]') || PASS_TOKENS.some(p => p.startsWith(text))));
}

function onDelta(ev) {
  if (!streamTarget(ev)) return;
  const key = runKey(ev.profile, ev.session_id);
  if (ev.kind === 'reset') {  // the stream broke and the request is being retried: drop the partial bubble
    const old = C.streams.get(key);
    if (old) { old.el.remove(); C.streams.delete(key); }
    return;
  }
  if (!ev.text) return;
  let st = C.streams.get(key);
  if (st && (st.iteration !== ev.iteration || st.done)) { st.el.remove(); st = null; }
  if (!st) { st = createStream(ev); C.streams.set(key, st); }
  const stick = nearBottom();
  if (ev.kind === 'reasoning') {
    if (st.room) return;  // members' private reasoning stays out of the group view
    if (!st.reasoning) {
      st.reasoning = document.createTextNode('');
      st.body.prepend(h('details', { class: 'reasoning' }, h('summary', null, t('Thinking…')), h('div', null, st.reasoning)));
    }
    st.reasoning.appendData(ev.text);
  } else {
    const text = st.text ? ev.text : ev.text.replace(/^\s+/, '');
    st.text += text;
    st.content.appendData(text);
  }
  const show = streamVisible(st);
  if (show) clearEmpty();
  st.el.classList.toggle('hidden', !show);
  if (stick && show) scrollBottom();
}

function finishStream(ev) {
  const st = C && C.streams.get(runKey(ev.profile, ev.session_id));
  if (!st || st.done) return;
  st.done = true;
  st.el.classList.add('done');
  const c = C;
  setTimeout(() => {
    st.el.remove();
    if (c.streams.get(runKey(st.profile, ev.session_id)) === st) c.streams.delete(runKey(st.profile, ev.session_id));
  }, STREAM_GRACE_MS);
}

/** After a fetch appended items: drop finished bubbles whose final message has arrived (`replaced`),
 * keep the others at the end of the transcript. */
function settleStreams(replaced) {
  const box = $('#messages');
  for (const [key, st] of C.streams) {
    if (st.done && replaced(st)) { st.el.remove(); C.streams.delete(key); } else if (box.lastElementChild !== st.el) box.append(st.el);
  }
}

// ====================================================================== activity (subtle rows + status hints)
/* Bus events about what the agent does behind the scenes. In the open session they are drawn as
 * small muted rows in the transcript (the server returns the stored ones with each fetch); those of
 * delegates, room members, and the ones without a row are flashed briefly in the status line. */
const ROW_EVENTS = new Set(['memory.session_search', 'context.pruned', 'context.compacted', 'loop.detected', 'experience.added',
  'approval.auto', 'approval.smart', 'memory.corrected', 'security.injection_flagged']);
const HINT_EVENTS = new Set([...ROW_EVENTS, 'experience.retrieved', 'budget.checkpoint']);

const OUTCOME_NAMES = { success: t('success'), partial: t('partial'), failure: t('failure') };
function activityInfo(ev) {
  switch (ev.type) {
    case 'memory.session_search':
      return { icon: '⌕', text: plural(ev.hits || 0, 'searched past conversations for “{query}” — {n} hit', 'searched past conversations for “{query}” — {n} hits')
        .replace('{query}', () => ev.query || '') };
    case 'context.pruned':
      return { icon: '✂', text: t('cleared old tool output to keep the context small') };
    case 'context.compacted':
      return { icon: '✂', text: plural(ev.folded || 0, 'compacted the context — {n} earlier message summarised', 'compacted the context — {n} earlier messages summarised') };
    case 'loop.detected':
      return { icon: '⚠', text: t('loop guard stopped the run: {reason}', { reason: ev.reason || t('no progress') }), cls: 'warn' };
    case 'experience.added':
      return { icon: '✎', text: t('recorded an experience ({outcome})', { outcome: OUTCOME_NAMES[ev.outcome || 'partial'] || ev.outcome }), more: ev.lessons || [] };
    case 'approval.auto':
      return { icon: '✓', text: ev.grant === 'always' ? t('auto-approved {what} — always allowed', { what: ev.summary || ev.category })
        : t('auto-approved {what} — allowed for this session', { what: ev.summary || ev.category }),
        title: t('Permission scope: {scope}', { scope: ev.category }) };
    case 'approval.smart': {
      const outcome = { approve: t('allowed (low risk)'), deny: t('denied (high risk)') }[ev.verdict] || t('needs your decision');
      return { icon: ev.verdict === 'approve' ? '✓' : ev.verdict === 'deny' ? '✗' : '?', cls: ev.verdict === 'deny' ? 'warn' : '',
        text: t('smart approval: {what} — {outcome}', { what: ev.summary || ev.category, outcome }), title: t('Permission scope: {scope}', { scope: ev.category }) };
    }
    case 'memory.corrected': {
      const note = String(ev.old_text || '');
      const short = note.length > 90 ? note.slice(0, 89) + '…' : note;
      return { icon: '✎', title: note,
        text: ev.action === 'replace' ? t('corrected a memory note that turned out wrong: “{note}”', { note: short })
          : t('removed a memory note that turned out wrong: “{note}”', { note: short }) };
    }
    case 'security.injection_flagged': {
      const patterns = Array.isArray(ev.patterns) ? ev.patterns : [];
      return { icon: '⚠', cls: 'warn', text: patterns.length ? t('fetched content looks like a prompt injection ({patterns}) — treated as untrusted data', { patterns: patterns.join('; ') })
        : t('fetched content looks like a prompt injection — treated as untrusted data'),
        more: [t('Source: {source}', { source: ev.source || t('unknown') }), ...patterns.map(p => t('Pattern: {pattern}', { pattern: p }))] };
    }
    case 'experience.retrieved':
      return { icon: '↺', text: plural((ev.ids || []).length, 'recalled {n} past experience', 'recalled {n} past experiences') };
    case 'budget.checkpoint':
      return { icon: '⏱', text: plural(ev.steps_left || 0, '{n} step left in the step budget', '{n} steps left in the step budget') };
    default:
      return null;
  }
}

function activityRow(info, ts) {
  const cls = 'ev-note' + (info.cls ? ' ' + info.cls : '');
  const title = [info.title, fullTime(ts)].filter(Boolean).join('\n');
  const line = [h('span', { class: 'ev-icon', 'aria-hidden': 'true' }, info.icon), h('span', { class: 'ev-text' }, cap(info.text))];
  if (info.more && info.more.length) {
    return h('details', { class: cls, title }, h('summary', null, line), h('ul', null, info.more.map(m => h('li', null, m))));
  }
  return h('div', { class: cls, title }, line);
}

/** Does an event concern the open view (its session, a delegate working for it, or its room)? */
function eventInView(ev) {
  if (!C) return false;
  const v = C.view;
  if (v.type === 'room') return !!ev.room_id && ev.room_id === v.roomId;
  if (!v.sid) return false;
  return (ev.profile === v.profile && ev.session_id === v.sid) ||
    !!(ev.origin && ev.origin.profile === v.profile && ev.origin.session_id === v.sid);
}

function flashHint(ev) {
  const info = activityInfo(ev);
  if (!info || !C) return;
  C.hint = { icon: info.icon, text: `@${ev.profile} ${info.text}`, cls: info.cls, until: Date.now() + 6000 };
  renderLive();
  setTimeout(renderLive, 6100);
}

// ====================================================================== the agent's plan (todo tool)
const PLAN_MARK = { completed: '✓', in_progress: '▸', pending: '○', cancelled: '–' };

function planStats(todos) {
  const counted = todos.filter(x => x.status !== 'cancelled');
  const done = counted.filter(x => x.status === 'completed').length;
  return { done, total: counted.length, cancelled: todos.length - counted.length, cur: todos.find(x => x.status === 'in_progress') };
}
const planTitle = st => t('{done} of {total} done', { done: st.done, total: st.total }) + (st.cancelled ? ` · ${t('{n} cancelled', { n: st.cancelled })}` : '');
const PLAN_STATUS = { pending: t('pending'), in_progress: t('in progress'), completed: t('completed'), cancelled: t('cancelled') };
/** A plan is only as current as its last update: the agent ticks items itself (todo), PlanD does not. Flag a plan with
 *  open items that has not been touched for a while, and one whose run has ended. */
const PLAN_STALE_CALLS = 8;
function planStale(st, run) {
  if (st.done >= st.total) return null;
  if (!run) return h('span', { class: 'plan-stale', title: t('The run ended with items still open; the plan shows its last update.') }, t('run ended'));
  const n = run.plan_idle || 0;
  return n >= PLAN_STALE_CALLS
    ? h('span', { class: 'plan-stale', title: t('{n} tool calls since this plan was last updated. The agent updates its plan itself; the work may be further along.', { n }) }, t('not updated · {n} calls', { n }))
    : null;
}

/** Compact checklist above the composer: the open session's plan, plus one line per running
 * delegate / room member that keeps a plan (click to open its work log). */
const renderPlan = rafOnce(() => {
  const el = $('#plan');
  if (!C) return el.classList.add('hidden');
  const v = C.view;
  const own = v.type !== 'room' && v.sid ? C.todos || [] : [];
  const others = relevantRuns()
    .filter(r => r.todos && r.todos.length && !(v.type !== 'room' && r.profile === v.profile && r.session_id === v.sid))
    .sort((a, b) => (a.depth || 0) - (b.depth || 0));
  if (!own.length && !others.length) { el.replaceChildren(); return el.classList.add('hidden'); }
  const kids = [];
  if (own.length) {
    const st = planStats(own);
    const complete = st.done === st.total;
    const open = C.planOpen ?? !complete;  // finished plans start folded to one line
    const pct = st.total ? Math.round((st.done / st.total) * 100) : 100;
    kids.push(h('button', { type: 'button', class: 'plan-head', 'aria-expanded': String(open), title: open ? t('Hide the plan') : t('Show the plan'),
      onclick: () => { C.planOpen = !open; renderPlan(); } },
      h('span', { class: 'plan-chev', 'aria-hidden': 'true' }),
      h('span', { class: 'plan-label' }, t('Plan')),
      h('span', { class: 'plan-count', title: planTitle(st) }, `${st.done}/${st.total}`),
      h('span', { class: 'bar plan-bar' + (complete ? ' ok' : '') }, h('span', { style: { width: `${pct}%` } })),
      h('span', { class: 'plan-cur' }, open ? '' : st.cur ? `▸ ${st.cur.content}` : complete ? t('All done') : ''),
      planStale(st, S.runs.get(runKey(v.profile, v.sid)))));
    if (open) {
      kids.push(h('ol', { class: 'plan-list' }, own.map(x => h('li', { class: `plan-item s-${x.status}`, title: PLAN_STATUS[x.status] || x.status.replace('_', ' ') },
        h('span', { class: 'plan-mark', 'aria-hidden': 'true' }, PLAN_MARK[x.status] || '○'),
        h('span', { class: 'plan-text' }, x.content)))));
    }
  }
  for (const r of others) {
    const st = planStats(r.todos);
    const open = () => go(`#/session/${enc(r.profile)}/${enc(r.session_id)}`);
    kids.push(h('div', { class: 'plan-sub', role: 'button', tabindex: '0', title: t("@{name}'s plan — {progress}. Open its work log.", { name: r.profile, progress: planTitle(st) }),
      onclick: open, onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } } },
      avatar(profileOf(r.profile), 18),
      h('span', { class: 'plan-who' }, `@${r.profile}`),
      h('span', { class: 'plan-count' }, `${st.done}/${st.total}`),
      h('span', { class: 'plan-cur' }, st.cur ? `▸ ${st.cur.content}` : st.done === st.total ? t('all done') : ''),
      planStale(st, r)));
  }
  el.replaceChildren(...kids);
  el.classList.remove('hidden');
  const list = $('.plan-list', el);
  const cur = list && $('.s-in_progress', list);
  if (cur && list.scrollHeight > list.clientHeight) list.scrollTop = Math.max(0, cur.offsetTop - list.offsetTop - 28);
});

// ====================================================================== composer
function updateComposer() {
  const input = $('#input');
  const send = $('#send');
  const stop = $('#stop');
  if (!C) return;
  const v = C.view;
  let placeholder = t('Message PlanD…');
  let readOnly = false;
  let running = false;
  if (v.type === 'room') {
    const room = C.room || S.rooms.find(r => r.id === v.roomId);
    placeholder = room ? t('Message {name} — @mention a bot to address it', { name: room.name }) : t('Message the group…');
    running = S.drives.has(v.roomId) || relevantRuns().length > 0;
  } else {
    const p = viewProfile();
    if (v.type === 'bot') placeholder = t('Message {name}…', { name: p.title });
    if (v.type === 'session' && C.session && !['chat', 'bot_chat'].includes(C.session.kind)) {
      readOnly = true;
      placeholder = t('This {kind} is a read-only work log.', { kind: kindLabel(C.session.kind) });
    }
    running = C.busy || runsFor(r => r.profile === v.profile && r.session_id === v.sid).length > 0;
  }
  input.placeholder = placeholder;
  input.disabled = readOnly;
  $('#attach').disabled = readOnly;
  send.disabled = readOnly || (v.type !== 'room' && running);
  stop.classList.toggle('hidden', !running);
  send.classList.toggle('hidden', running && v.type !== 'room');
  renderPickers();
}

// --- + button: files go to uploads/ in the bot's workspace (or the group's shared folder) and are
// attached to the next message as paths the agent can open.
async function uploadFiles(list) {
  if (!C || $('#input').disabled) return;
  const c = C;
  const v = c.view;
  if (v.type !== 'room' && !v.sid && c.pending.workspace) {
    try { await ensureSession(c); } catch (e) { toast(e.message, 'error'); return; }
  }
  const base = v.type === 'room' ? `/api/rooms/${enc(v.roomId)}/uploads?x=1`
    : `/api/profiles/${enc(v.profile)}/uploads?${v.sid ? `session=${enc(v.sid)}` : 'x=1'}`;
  await Promise.all(Array.from(list || []).map(async file => {
    const item = { name: file.name, size: file.size, status: 'uploading', path: null };
    c.attachments.push(item);
    if (liveConv(c)) renderAttachments();
    try {
      const r = await reach(`${base}&filename=${enc(file.name)}`, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file });
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `${r.status} ${r.statusText}`);
      Object.assign(item, { status: 'done', path: data.path, name: data.name, size: data.size });
    } catch (e) {
      const cur = liveConv(c) || c;
      cur.attachments = cur.attachments.filter(a => a !== item);
      toast(`${file.name}: ${e.message}`, 'error');
    }
    if (liveConv(c)) renderAttachments();
  }));
}

function renderAttachments() {
  const box = $('#attachments');
  const list = (C && C.attachments) || [];
  box.classList.toggle('hidden', !list.length);
  const where = C && C.view.type === 'room' ? t('the group\u2019s shared folder') : t('the workspace');
  box.replaceChildren(...list.map(a => h('span', {
    class: `attach-chip${a.status === 'uploading' ? ' uploading' : ''}`,
    title: a.path ? t('Saved in {where} as {path}', { where, path: a.path }) : t('Uploading\u2026'),
  },
  a.status === 'uploading' ? h('span', { class: 'spinner' }) : h('span', { class: 'attach-ico', 'aria-hidden': 'true' }, '\u{1F4CE}'),
  h('span', { class: 'attach-name' }, a.name),
  h('span', { class: 'attach-size' }, fmtSize(a.size)),
  h('button', {
    type: 'button', class: 'attach-x', 'aria-label': t('Remove {name}', { name: a.name }),
    onclick: () => { C.attachments = C.attachments.filter(x => x !== a); renderAttachments(); },
  }, '\u00d7'))));
}

// --- Model and thinking pickers at the right of the message box (the web counterpart of the session-scoped
// /model and /reasoning commands). They set this chat's own value; "Use the bot's
// setting" clears it. In groups every bot uses its own settings, so the pickers are hidden there.
const MODELS = [
  ['deepseek-flash', 'DeepSeek Flash', t('Fast and cheap; the evaluated default')],
  ['deepseek-v4-pro', 'DeepSeek V4 Pro', t('Stronger, about 4–7× the price')],
];
const PICKERS = {
  model: {
    pill: '#model-pick', menu: '#model-menu', field: 'model', head: t('Model for this chat'),
    options: () => MODELS,
    bot: p => p.model || 'deepseek-flash',
    available: p => p.provider === 'deepseek',
    label: v => (isNarrow() ? v.replace(/^deepseek-/, '') : v),
    done: v => t('This chat now uses {model}.', { model: v }),
  },
  reasoning: {
    pill: '#think', menu: '#think-menu', field: 'reasoning', head: t('Thinking intensity for this chat'),
    options: (p, value) => reasoningOptions(p.provider, value),
    bot: p => p.reasoning || 'default',
    available: p => canThink(p.provider),
    label: v => reasoningName(v),
    done: v => t('This chat now thinks at {level}.', { level: reasoningName(v) }),
  },
};

function pickState(kind) {
  if (!C || C.view.type === 'room') return null;
  const p = viewProfile();
  const k = PICKERS[kind];
  if (!p || !k.available(p)) return null;
  const own = C.session ? C.session[k.field] : C.pending[k.field];
  const bot = k.bot(p);
  return { value: own || bot, own: !!own, bot, p };
}

function renderPickers() {
  for (const kind of Object.keys(PICKERS)) {
    const k = PICKERS[kind];
    const pill = $(k.pill);
    const st = pickState(kind);
    pill.classList.toggle('hidden', !st || $('#input').disabled);
    if (!st) { closePicker(kind); continue; }
    pill.classList.toggle('own', st.own);
    pill.replaceChildren(h('span', { class: 'pick-label' }, k.label(st.value)), h('span', { class: 'pick-chev', 'aria-hidden': 'true' }, '⌄'));
    pill.title = st.own ? t('{head}: {value} (the bot’s setting is {bot})', { head: k.head, value: k.label(st.value), bot: k.label(st.bot) })
      : t('{head}: the bot’s setting ({bot}). Click to change it for this chat.', { head: k.head, bot: k.label(st.bot) });
  }
}

function togglePicker(kind) {
  const k = PICKERS[kind];
  const menu = $(k.menu);
  if (!menu.classList.contains('hidden')) return closePicker(kind);
  Object.keys(PICKERS).forEach(k => closePicker(k, false));
  const st = pickState(kind);
  if (!st) return;
  menu.replaceChildren(...[h('div', { class: 'pick-head' }, k.head),
    ...k.options(st.p, st.value).map(([v, label, help]) => h('button', {
      type: 'button', role: 'menuitemradio', 'aria-checked': String(v === st.value), 'aria-label': `${label}: ${help}`,
      class: `pick-item${v === st.value ? ' on' : ''}`, onclick: () => setPick(kind, v),
    }, h('span', { class: 'pick-check' }, v === st.value ? '✓' : ''), h('span', { class: 'pick-name' }, label), h('span', { class: 'pick-help' }, help))),
    st.own ? h('button', { type: 'button', role: 'menuitem', class: 'pick-item pick-reset', onclick: () => setPick(kind, '') },
      h('span', { class: 'pick-check' }), h('span', { class: 'pick-name' }, t('Use the bot’s setting ({bot})', { bot: k.label(st.bot) }))) : null,
  ].filter(Boolean));
  menu.setAttribute('aria-label', k.head);
  menu.firstChild.setAttribute('aria-hidden', 'true');  // the heading is the menu's label
  menu.classList.remove('hidden');
  $(k.pill).setAttribute('aria-expanded', 'true');
  const items = menuItems(menu);
  items.forEach(it => { it.tabIndex = -1; });
  const first = items.find(it => it.getAttribute('aria-checked') === 'true') || items[0];
  if (first) first.focus();
}

const menuItems = menu => $$('[role^="menuitem"]', menu);

/** Keys inside an open picker menu: up/down/Home/End move, Esc closes (focus goes back to the pill), Tab closes. */
function pickerKey(kind, e) {
  const items = menuItems($(PICKERS[kind].menu));
  const i = items.indexOf(document.activeElement);
  if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closePicker(kind); return; }
  if (e.key === 'Tab') { closePicker(kind, false); return; }
  const j = e.key === 'ArrowDown' ? (i + 1) % items.length : e.key === 'ArrowUp' ? (i - 1 + items.length) % items.length
    : e.key === 'Home' ? 0 : e.key === 'End' ? items.length - 1 : -1;
  if (j < 0 || !items.length) return;
  e.preventDefault();
  items[j].focus();
}

/** `refocus`: when focus is inside the menu, put it back on the pill (a hidden menu would drop it on <body>). */
function closePicker(kind, refocus = true) {
  const k = PICKERS[kind];
  const menu = $(k.menu);
  const inside = menu.contains(document.activeElement);
  menu.classList.add('hidden');
  $(k.pill).setAttribute('aria-expanded', 'false');
  if (inside && refocus) $(k.pill).focus();
}

async function setPick(kind, value) {
  closePicker(kind);
  const c = C;
  if (!c) return;
  const k = PICKERS[kind];
  const v = c.view;
  if (!v.sid) { c.pending[k.field] = value || null; renderPickers(); return; }  // applied when the chat is created
  try {
    c.session = await api('PATCH', `/api/profiles/${enc(v.profile)}/sessions/${enc(v.sid)}`, { [k.field]: value });
    if (c === C) renderPickers();
    toast(value ? t('{msg} It applies from the next message.', { msg: k.done(value) }) : t('This chat now follows the bot’s setting.'));
  } catch (e) { toast(e.message, 'error'); }
}

function autosize() {
  const el = $('#input');
  el.style.height = 'auto';
  el.style.height = `${Math.min(el.scrollHeight, 240)}px`;
}

/** Create the chat behind a new-chat view (applying settings picked before it existed). */
async function ensureSession(c) {
  const v = c.view;
  if (v.sid) return;
  const s = await api('POST', `/api/profiles/${enc(v.profile)}/sessions`, {});
  v.sid = s.id;
  c.session = s;
  history.replaceState(null, '', `#/chat/${enc(s.id)}`);
  if (Object.values(c.pending).some(Boolean)) {
    c.session = await api('PATCH', `/api/profiles/${enc(v.profile)}/sessions/${enc(s.id)}`, c.pending);
    c.pending = {};
  }
  if (liveConv(c)) renderHead();
}
/** The open conversation if it is still `c`'s view (a resync swaps in a fresh C for the same view), else null. */
const liveConv = c => (C && (C === c || C.view === c.view) ? C : null);

async function send() {
  const input = $('#input');
  const text = input.value.trim();
  if (!C) return;
  if (C.attachments.some(a => a.status === 'uploading')) { toast(t('Wait for the upload to finish.')); return; }
  const files = C.attachments.filter(a => a.status === 'done');
  if (!text && !files.length) return;
  const attachments = files.map(a => a.path);
  const restore = c => { const cur = liveConv(c); if (cur) { cur.attachments = files; renderAttachments(); } };
  const v = C.view;
  if (v.type === 'room') {
    const c = C;
    input.value = '';
    autosize();
    c.attachments = [];
    renderAttachments();
    try {
      const r = await api('POST', `/api/rooms/${enc(v.roomId)}/messages`, { text, attachments });
      if (r.queued) toast(t('The team is still busy; your message is queued for the next turn.'));
      refreshRoom();
    } catch (e) {
      toast(e.message, 'error');
      input.value = text;
      autosize();
      restore(c);
    }
    return;
  }
  if ($('#send').disabled) return;
  let c = C;
  try {
    await ensureSession(c);
    c = liveConv(c);
    if (c) {  // else the user opened another conversation meanwhile: still send, but leave that view alone
      input.value = '';
      autosize();
      c.attachments = [];
      renderAttachments();
      clearEmpty();
      c.optimistic = h('div', { class: 'msg msg-user' }, h('div', { class: 'bubble pending' }, text,
        files.length ? h('div', { class: 'bubble-files' }, files.map(f => h('span', null, `\u{1F4CE} ${f.name}`))) : null));
      c.group = null;
      $('#messages').append(c.optimistic);
      scrollBottom();
      c.busy = true;
      updateComposer();
      renderLive();
    }
    await api('POST', `/api/profiles/${enc(v.profile)}/sessions/${enc(v.sid)}/messages`, { text, attachments });
    if (v.type === 'chat') loadChats().catch(() => {});
  } catch (e) {
    toast(e.message, 'error');
    if (!c || !(c = liveConv(c))) return;
    if (c.optimistic) { c.optimistic.remove(); c.optimistic = null; }
    c.busy = false;
    updateComposer();
    renderLive();
    input.value = text;
    autosize();
    restore(c);
  }
}

async function stopRun() {
  if (!C) return;
  const v = C.view;
  try {
    if (v.type === 'room') await api('POST', `/api/rooms/${enc(v.roomId)}/stop`);
    else if (v.sid) await api('POST', `/api/profiles/${enc(v.profile)}/sessions/${enc(v.sid)}/stop`);
    toast(t('Stopping…'));
  } catch (e) { toast(e.message, 'error'); }
}

// --- @mention autocomplete (rooms)
const M = { open: false, items: [], sel: 0, start: 0 };

function mentionCandidates() {
  if (!C || C.view.type !== 'room') return [];
  const room = C.room || S.rooms.find(r => r.id === C.view.roomId);
  if (!room) return [];
  return [...(room.member_info || []), { name: 'all', title: t('Everyone in the group'), avatar: '#9ca3af' }];
}

function updateMentions() {
  const input = $('#input');
  const upto = input.value.slice(0, input.selectionStart);
  const m = upto.match(/(^|[\s(])@([a-z0-9_-]*)$/i);
  const cands = m ? mentionCandidates().filter(c => c.name.startsWith(m[2].toLowerCase())) : [];
  if (!m || !cands.length) return closeMentions();
  M.open = true;
  M.items = cands;
  M.sel = Math.min(M.sel, cands.length - 1);
  M.start = upto.length - m[2].length - 1;
  const pop = $('#mention-pop');
  pop.replaceChildren(...cands.map((c, i) => h('div', {
    id: `mention-opt-${i}`, class: 'mention-item' + (i === M.sel ? ' sel' : ''), role: 'option', 'aria-selected': String(i === M.sel),
    onmousedown: e => { e.preventDefault(); pickMention(i); },
  }, avatar(c, 22), h('strong', null, `@${c.name}`), h('span', { class: 'handle' }, c.title))));
  pop.classList.remove('hidden');
  input.setAttribute('aria-expanded', 'true');
  input.setAttribute('aria-activedescendant', `mention-opt-${M.sel}`);  // screen readers follow the selection; focus stays in the input
}

function closeMentions() {
  M.open = false;
  M.sel = 0;
  $('#mention-pop').classList.add('hidden');
  const input = $('#input');
  input.setAttribute('aria-expanded', 'false');
  input.removeAttribute('aria-activedescendant');
}

function pickMention(i) {
  const input = $('#input');
  const c = M.items[i];
  if (!c) return;
  const before = input.value.slice(0, M.start);
  const after = input.value.slice(input.selectionStart);
  input.value = `${before}@${c.name} ${after}`;
  const pos = before.length + c.name.length + 2;
  input.setSelectionRange(pos, pos);
  closeMentions();
  autosize();
  input.focus();
}

// ====================================================================== HITL
function hitlTarget(r) {
  if (r.room_id) return `#/room/${enc(r.room_id)}`;
  const o = r.origin || { profile: r.profile, session_id: r.session_id, kind: null };
  if (o.profile === 'default' && (o.kind === 'chat' || !o.kind)) return `#/chat/${enc(o.session_id)}`;
  if (o.kind === 'bot_chat') return `#/bot/${enc(o.profile)}`;
  return `#/session/${enc(o.profile)}/${enc(o.session_id)}`;
}

function hitlCard(r, { inTray = false } = {}) {
  const p = { name: r.profile, title: r.profile_title || r.profile, avatar: r.avatar };
  const q = r.payload || {};
  const approval = r.kind === 'approval';
  const card = h('div', { class: `hitl-card hitl-${r.kind}`, dataset: { id: r.id } },
    h('div', { class: 'hitl-head' }, avatar(p, 22), h('strong', null, p.title), h('span', { class: 'handle' }, `@${p.name}`),
      h('span', { class: 'hitl-kind' }, approval ? t('needs your permission') : t('has a question')),
      h('span', { class: `pill hitl-kind-tag ${approval ? 'pill-amber' : 'pill-accent'}` }, approval ? t('Approval') : t('Clarification'))));
  const disable = on => $$('button, textarea', card).forEach(b => { b.disabled = on; });
  const submit = async body => {
    disable(true);
    try {
      await api('POST', `/api/hitl/${enc(r.id)}`, body);
      S.hitl = S.hitl.filter(x => x.id !== r.id);
      $$(`.hitl-card[data-id="${CSS.escape(r.id)}"]`).forEach(el => { el.classList.add('answered'); setTimeout(() => el.remove(), 260); });
      renderBrand();
      renderSidebar();
      setTimeout(renderTray, 280);
    } catch (e) {
      toast(e.message, 'error');
      disable(false);
      if (e.status === 409 || e.status === 404) refreshHitl();
    }
  };
  if (approval) {
    card.append(h('div', { class: 'hitl-q' }, q.question));
    if (q.detail) card.append(h('pre', { class: 'hitl-detail' }, q.detail));
    if (q.category) card.append(h('div', { class: 'hitl-cat' }, t('Permission scope: {scope}', { scope: q.category })));
    card.append(h('div', { class: 'hitl-actions' },
      h('button', { type: 'button', class: 'btn btn-primary', title: t('Allow this one operation'), onclick: () => submit({ choice: 'once' }) }, t('Allow once')),
      h('button', { type: 'button', class: 'btn', title: t('Allow this kind of operation for the rest of this session'), onclick: () => submit({ choice: 'session' }) }, t('Session')),
      h('button', { type: 'button', class: 'btn', title: t('Always allow "{scope}" for @{name}', { scope: q.category || t('this'), name: p.name }), onclick: () => submit({ choice: 'always' }) }, t('Always')),
      h('button', { type: 'button', class: 'btn btn-danger', onclick: () => submit({ choice: 'deny' }) }, t('Deny'))));
  } else {
    card.append(h('div', { class: 'hitl-q md', html: md(q.question || '') }));
    if (q.detail) card.append(h('div', { class: 'hitl-detail-text' }, q.detail));
    if (q.options && q.options.length) {
      card.append(h('div', { class: 'hitl-options' }, q.options.map(o => h('button', { type: 'button', class: 'btn btn-option', onclick: () => submit({ text: o }) }, o))));
    }
    const ta = h('textarea', { rows: 1, placeholder: q.options && q.options.length ? t('Or type another answer…') : t('Type your answer…') });
    const go = () => { const text = ta.value.trim(); if (text) submit({ text }); };
    ta.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && e.keyCode !== 229) { e.preventDefault(); go(); }
    });
    ta.addEventListener('input', () => { ta.style.height = 'auto'; ta.style.height = `${Math.min(ta.scrollHeight, 140)}px`; });
    card.append(h('div', { class: 'hitl-answer' }, ta, h('button', { type: 'button', class: 'btn btn-primary', onclick: go }, t('Answer'))));
  }
  if (!r.live) card.append(h('div', { class: 'hitl-warn' }, t('The run that asked this is no longer waiting; answering only records it.')));
  if (inTray) {
    card.append(h('a', { class: 'hitl-open', href: hitlTarget(r), onclick: () => closeTray(false) }, t('Open conversation →')));
  }
  return card;
}

function renderHitlCards() {
  if (!C) return;
  const box = $('#hitl-cards');
  const reqs = hitlFor(C.view);
  const ids = new Set(reqs.map(r => r.id));
  $$('.hitl-card', box).forEach(el => { if (!ids.has(el.dataset.id) && !el.classList.contains('answered')) el.remove(); });
  const have = new Set($$('.hitl-card', box).map(el => el.dataset.id));
  let added = false;
  for (const r of reqs) if (!have.has(r.id)) { box.append(hitlCard(r)); added = true; }
  if (added) {
    scrollBottom();
    const ta = $('.hitl-card:last-child textarea', box);
    // only take focus nobody is using: not from another field, button or dialog, nor from a half-typed message
    const a = document.activeElement, input = $('#input');
    if (ta && (!a || a === document.body || (a === input && !input.value.trim()))) ta.focus({ preventScroll: true });
  }
}

function renderTray() {
  const tray = $('#tray');
  if (tray.classList.contains('hidden')) return;
  if (!S.hitl.length) { closeTray(); return; }
  const had = tray.contains(document.activeElement);  // a re-render must not drop keyboard focus out of the dialog
  tray.replaceChildren(
    h('div', { class: 'tray-head' }, h('span', null, t('Waiting for you ({n})', { n: S.hitl.length })), iconBtn('close', t('Close'), () => closeTray())),
    ...S.hitl.map(r => hitlCard(r, { inTray: true })));
  if (had && !tray.contains(document.activeElement)) tray.focus();
}

function toggleTray() {
  const tray = $('#tray');
  if (!tray.classList.contains('hidden')) return closeTray();
  tray.classList.remove('hidden');
  renderTray();
  if (!tray.classList.contains('hidden')) tray.focus();  // the dialog takes focus; Tab reaches its cards
}

/** `refocus`: when focus was inside the tray, give it back to the badge that opened it. */
function closeTray(refocus = true) {
  const tray = $('#tray');
  if (tray.classList.contains('hidden')) return;
  const inside = tray.contains(document.activeElement);
  tray.classList.add('hidden');
  if (inside && refocus) {
    const badge = $('#hitl-badge');
    if (!badge.classList.contains('hidden')) badge.focus(); else $('#input').focus();
  }
}

function notifyHitl(ev) {
  const req = ev.request || {};
  const visible = C && (C.view.type === 'room' ? ev.room_id === C.view.roomId
    : (ev.profile === C.view.profile && ev.session_id === C.view.sid) ||
      (ev.origin && ev.origin.profile === C.view.profile && ev.origin.session_id === C.view.sid));
  if (visible && document.hasFocus()) return;
  const what = req.kind === 'approval' ? t('@{name} needs your permission', { name: ev.profile }) : t('@{name} has a question', { name: ev.profile });
  toast(what, 'warn', {
    label: t('Open'),
    fn: () => go(hitlTarget({ room_id: ev.room_id, origin: ev.origin, profile: ev.profile, session_id: ev.session_id })),
  });
}

// ====================================================================== task board (#/room/<id>/board)
/* A group's board as status columns across the main column. Read-only: agents add and update tasks (team_tasks) and
 * delegation moves them (todo → in progress → done / failed). Every task.updated event carries the task as
 * stored, so cards move as the team works without refetching; cards are keyed by task id and rebuilt only
 * when the task changes, so an expanded card, its scroll and a running highlight survive other updates. */
const BOARD_COLS = [['todo', t('To do')], ['in_progress', t('In progress')], ['blocked', t('Blocked')], ['failed', t('Failed')], ['done', t('Done')]];
const COL_EMPTY = { todo: t('Nothing waiting'), in_progress: t('Nobody on a task'), blocked: t('Nothing blocked'), failed: t('No failures'), done: t('Nothing finished yet') };
/** A task status as a word (pills, stamps, dependency titles). */
const TASK_STATUS = { todo: t('to do'), in_progress: t('in progress'), blocked: t('blocked'), failed: t('failed'), done: t('done') };
const statusName = s => TASK_STATUS[s] || String(s).replace('_', ' ');
const OPEN_STATUSES = new Set(['todo', 'in_progress', 'blocked']);

/** Show the room's conversation or its board. The board takes the details panel's room while it is open
 *  and gives it back afterwards (unless the panel was toggled by hand in between). */
function setBoardMode() {
  const on = !!(C && C.view.type === 'room' && C.view.board);
  $('#main').classList.toggle('board-mode', on);
  $('#board').classList.toggle('hidden', !on);
  if (on && S.panelOpen && !isNarrow()) { S.panelOpen = false; P.boardHid = true; }
  else if (!on && P.boardHid) { S.panelOpen = !isNarrow(); P.boardHid = false; }
}

/** Chat ⇄ Board inside the open room: the transcript stays loaded, so switching back is instant. */
function switchRoomMode(board) {
  C.view.board = board;
  setBoardMode();
  renderHead();
  renderPanel();
  renderBoard();
  if (!board) { scrollBottom(); if (window.innerWidth > 760) $('#input').focus(); }
}

async function loadTasks() {
  const c = C;
  if (!c || c.view.type !== 'room') return;
  try {
    const tasks = await api('GET', `/api/rooms/${enc(c.view.roomId)}/tasks`);
    if (c !== C) return;
    c.tasks = tasks;
    c.tasksError = null;
  } catch (e) {
    if (c !== C) return;
    c.tasksError = e.message;
  }
  renderHead();  // the Board button counts unfinished tasks
  renderBoard();
}
const refreshTasks = debounce(() => loadTasks(), 200);

function upsertTask(task) {
  if (!task || !C.tasks) return refreshTasks();  // the first load may predate this change
  const i = C.tasks.findIndex(x => x.id === task.id);
  if (i < 0 || C.tasks[i].status !== task.status) C.taskFlash.add(task.id);
  if (i < 0) C.tasks.push(task); else C.tasks[i] = task;
  renderHead();
  renderBoard();
}

/** Put `nodes` into `parent` in order, touching only what changed: a node that is moved restarts its animations. */
function syncChildren(parent, nodes) {
  const keep = new Set(nodes);
  for (const el of [...parent.children]) if (!keep.has(el)) el.remove();
  nodes.forEach((n, i) => { if (parent.children[i] !== n) parent.insertBefore(n, parent.children[i] || null); });
}

function renderBoard() {
  const box = $('#board');
  if (!C || C.view.type !== 'room' || !C.view.board) return;
  if (!C.tasks) {
    box.replaceChildren(h('div', { class: 'muted pad' }, C.tasksError || t('Loading the board…')));
    C.boardEls = null;
    return;
  }
  let b = C.boardEls;
  if (!b || !box.contains(b.cols)) {
    b = C.boardEls = { top: h('div', { class: 'board-top' }), cols: h('div', { class: 'board-cols' }), col: {}, cards: new Map() };
    C.boardSig = '';
    for (const [s, label] of BOARD_COLS) {
      const count = h('span', { class: 'kcol-n' });
      const body = h('div', { class: 'kcol-body' });
      b.cols.append(h('section', { class: `kcol s-${s}`, 'aria-label': label },
        h('header', { class: 'kcol-head' }, h('span', { class: 'kcol-dot', 'aria-hidden': 'true' }), h('span', { class: 'kcol-name' }, label), count), body));
      b.col[s] = { count, body, empty: h('div', { class: 'kcol-empty' }, COL_EMPTY[s]) };
    }
    box.replaceChildren(b.top, b.cols);
  }
  const tasks = [...C.tasks].sort((x, y) => x.created - y.created);
  const num = new Map(tasks.map((x, i) => [x.id, i + 1]));
  const byId = new Map(tasks.map(x => [x.id, x]));
  for (const [s] of BOARD_COLS) {
    const list = tasks.filter(x => x.status === s);
    if (s === 'done' || s === 'failed') list.sort((x, y) => y.updated - x.updated);  // latest outcome first
    const nodes = list.map(x => boardCard(b, x, num, byId));
    syncChildren(b.col[s].body, nodes.length ? nodes : [b.col[s].empty]);
    b.col[s].count.textContent = String(list.length);
  }
  for (const id of [...b.cards.keys()]) if (!byId.has(id)) b.cards.delete(id);
  C.taskFlash.clear();
  renderBoardLive();
}

/** A card's collapsed preview: the text without markdown syntax (tables and fences dropped, markers removed). */
function plainPreview(text) {
  return String(text).replace(/^\s*(`{3,}|~{3,})[\s\S]*?(^\s*\1|$(?![\s\S]))/gm, '')
    .split('\n').filter(l => !/^\s*\|/.test(l))
    .map(l => l.replace(/^\s{0,3}(#{1,6}|>|[-*+]|\d+[.)])\s+/, '').replace(/(\*\*|__|`)/g, '').trim())
    .filter(Boolean).join('\n');
}

function boardCard(b, task, num, byId) {
  const open = C.taskOpen.has(task.id);
  const deps = (task.depends_on || []).map(id => byId.get(id)).filter(Boolean);
  const parent = task.parent_id ? byId.get(task.parent_id) : null;
  const sig = [task.updated, task.status, task.assignee, task.review?.verdict, JSON.stringify(task.acceptance_checks), open, num.get(task.id), deps.map(d => d.status).join()].join('|');
  const old = b.cards.get(task.id);
  if (old && old.sig === sig) { old.task = task; return old.el; }
  const who = task.assignee ? profileOf(task.assignee) : null;
  const ref = d => `#${num.get(d.id)}`;
  const finished = task.status === 'done' || task.status === 'failed';
  const el = h('article', {
    class: `kcard s-${task.status}${open ? ' open' : ''}${C.taskFlash.has(task.id) ? ' flash' : ''}`,
    onclick: e => { if (!e.target.closest('a, .kc-body') && !String(window.getSelection() || '')) toggleTask(task.id); },
    onanimationend: e => { if (e.animationName === 'kc-flash') e.currentTarget.classList.remove('flash'); },  // a later move must not replay it
  },
    h('div', { class: 'kc-top' },
      h('span', { class: 'kc-num' }, ref(task)),
      parent ? h('span', { class: 'kc-rel', title: parent.title }, t('part of {ref}', { ref: ref(parent) })) : null,
      deps.length ? h('span', { class: 'kc-rel', title: deps.map(d => `${ref(d)} ${d.title} (${statusName(d.status)})`).join('\n') },
        t('after'), deps.map(d => h('span', { class: 'kc-dep' + (d.status === 'done' ? ' met' : '') }, ref(d)))) : null,
      finished ? h('span', { class: 'kc-stamp' }, statusName(task.status)) : null),
    h('button', { type: 'button', class: 'kc-title', 'aria-expanded': String(open) }, task.title),
    task.review ? h('p', { class: 'kc-desc' }, t('Acceptance criterion'), ' · ', task.review.criterion || task.title,
      ' · ', task.review.verdict.toUpperCase()) : null,
    open ? h('div', { class: 'kc-body' },
      (task.acceptance_checks || []).map(c => h('div', { class: 'kc-md' }, c.command, ' · ', c.state)),
      task.review ? h('div', { class: 'kc-md' }, Object.keys(task.review.inputs).join(', '),
        task.review.report_written ? ' → ' + task.review.report : '') : null,
      task.description ? [h('div', { class: 'kc-label' }, t('Details')), h('div', { class: 'md kc-md', html: md(task.description) })] : null,
      task.result ? [h('div', { class: 'kc-label' }, task.status === 'failed' ? t('Error') : t('Result')), h('div', { class: 'md kc-md' + (task.status === 'failed' ? ' kc-err' : ''), html: md(task.result) })] : null,
      h('div', { class: 'kc-meta' }, `${task.id} · ${t('added by @{name}', { name: task.created_by })} · ${fullTime(task.created)}`))
      : [task.description ? h('p', { class: 'kc-desc' }, plainPreview(task.description)) : null, task.result ? h('p', { class: 'kc-result' }, plainPreview(task.result)) : null],
    h('div', { class: 'kc-foot' },
      who ? avatar(who, 20) : h('span', { class: 'kc-nobody', 'aria-hidden': 'true' }),
      h('span', { class: 'kc-who' }, who ? `@${task.assignee}` : t('unassigned')),
      h('span', { class: 'kc-work' }),
      h('span', { class: 'kc-time', title: t('Updated {time}', { time: fullTime(task.updated) }) }, relTime(task.updated))));
  b.cards.set(task.id, { el, sig, task, working: false });
  return el;
}

function toggleTask(id) {
  if (!C.taskOpen.delete(id)) C.taskOpen.add(id);
  renderBoard();
  const card = C.boardEls && C.boardEls.cards.get(id);
  if (card) $('.kc-title', card.el).focus({ preventScroll: true });
}

/** The parts that change without the task changing: who is running right now, relative times, the summary. */
function renderBoardLive() {
  const b = C && C.view.type === 'room' && C.view.board ? C.boardEls : null;
  if (!b) return;
  for (const card of b.cards.values()) {
    const task = card.task;
    const working = task.status === 'in_progress' && !!task.assignee && profileBusy(task.assignee);
    if (working !== card.working) {
      card.working = working;
      card.el.classList.toggle('working', working);
      const av = $('.kc-foot .avatar', card.el);
      if (av) av.classList.toggle('ring', working);
    }
    const work = $('.kc-work', card.el);
    work.textContent = work.title = working ? workingText(task.assignee) : '';
    $('.kc-time', card.el).textContent = relTime(task.updated);
  }
  renderBoardTop(b);
}

function renderBoardTop(b) {
  const tasks = C.tasks;
  const count = s => tasks.filter(x => x.status === s).length;
  const room = C.room || S.rooms.find(r => r.id === C.view.roomId) || {};
  const working = (room.member_info || []).filter(m => profileBusy(m.name));
  const waiting = hitlFor(C.view).length;
  const sig = JSON.stringify([BOARD_COLS.map(([s]) => count(s)), working.map(m => m.name), waiting, room.lead]);
  if (sig === C.boardSig) return;  // rebuilding would restart the avatars' running pulse
  C.boardSig = sig;
  const toChat = () => go(`#/room/${enc(C.view.roomId)}`);
  const done = count('done');
  const kids = [];
  if (tasks.length) {
    kids.push(h('div', { class: 'board-stat' }, h('b', null, `${done}/${tasks.length}`), ' ', t('done')),
      h('div', { class: 'board-bar', role: 'img', 'aria-label': BOARD_COLS.map(([s, l]) => `${count(s)} ${l.toLowerCase()}`).join(', ') },
        ['done', 'failed', 'blocked', 'in_progress', 'todo'].map(s => count(s) ? h('span', { class: `s-${s}`, style: { flexGrow: count(s) } }) : null)));
  } else {
    const lead = room.lead ? `@${room.lead}` : t('the lead');
    kids.push(h('p', { class: 'board-empty' }, t('No tasks yet. When {lead} breaks a goal down, its subtasks appear here and move across as the team works.', { lead })),
      h('button', { type: 'button', class: 'btn btn-ghost btn-sm', onclick: toChat }, t('Give the team a goal')));
  }
  if (working.length) kids.push(h('span', { class: 'board-working' }, h('span', { class: 'stack' }, working.map(m => avatar(m, 20, true))), t('{n} working', { n: working.length })));
  if (waiting) kids.push(h('button', { type: 'button', class: 'btn btn-sm board-wait', onclick: toChat }, t('{n} waiting for you →', { n: waiting })));
  kids.push(h('span', { class: 'board-note', title: t('The lead adds tasks and delegation moves them; this view follows the board live.') }, t('Read-only · live')));
  b.top.replaceChildren(...kids);
}

// ====================================================================== right panel
function togglePanel() {
  S.panelOpen = !S.panelOpen;
  P.boardHid = false;
  if (!isNarrow()) prefs.set('panelOpen', S.panelOpen);
  renderHead();
  renderPanel();
}

const panelKind = () => (C && C.view.type === 'room' ? 'room' : 'agent');
const PANEL_TABS = {
  room: [['board', t('Board')], ['members', t('Members')], ['files', t('Files')], ['settings', t('Settings')]],
  agent: [['memory', t('Memory')], ['files', t('Files')], ['tasks', t('Tasks')], ['sessions', t('Sessions')], ['settings', t('Settings')]],
};

async function renderPanel({ keepScroll = false } = {}) {
  const el = $('#panel');
  const show = S.panelOpen && !!C;
  el.classList.toggle('hidden', !show);
  if (!show) return;
  const kind = panelKind();
  const cur = P.tab[kind];
  const oldBody = $('.panel-body', el);
  const scrollTop = keepScroll && oldBody ? oldBody.scrollTop : 0;
  const body = h('div', { class: 'panel-body' });
  if (!keepScroll || !oldBody) body.append(h('div', { class: 'muted pad' }, t('Loading…')));
  const tabs = h('div', { class: 'tabs tabs-sm' }, PANEL_TABS[kind].map(([k, label]) =>
    h('button', { type: 'button', class: 'tab' + (k === cur ? ' active' : ''), onclick: () => { P.tab[kind] = k; renderPanel(); } }, label)));
  const token = (P.token = Symbol('panel'));
  const head = h('div', { class: 'panel-head' }, tabs, iconBtn('close', t('Hide details ({key})', { key: keyLabel('mod+.') }), togglePanel));
  if (!keepScroll || !oldBody) el.replaceChildren(P.resizer, head, body);  // "Loading…" while the tab is built
  const build = PANEL_BUILDERS[kind][cur];
  let content;
  try { content = await build(); } catch (e) { content = h('div', { class: 'muted pad' }, e.message); }
  if (P.token !== token) return;
  body.replaceChildren(content);
  if (body.parentNode !== el) el.replaceChildren(P.resizer, head, body);
  body.scrollTop = scrollTop;
}

/** Re-render the panel only if it currently shows one of `tabs` (never a settings form being edited). */
function refreshPanel(tabs, profile) {
  if (!S.panelOpen || !C) return;
  const kind = panelKind();
  if (!tabs.includes(P.tab[kind])) return;
  if (profile && (kind !== 'agent' || C.view.profile !== profile)) return;
  schedulePanel();
}
const schedulePanel = debounce(() => renderPanel({ keepScroll: true }), 300);

const section = (title, ...kids) => h('div', { class: 'p-section' }, h('div', { class: 'p-title' }, ...[].concat(title)), ...kids);
const statusPill = s => h('span', { class: `pill status-${s}` }, statusName(s));

async function memoryPanel() {
  const name = C.view.profile;
  const m = await api('GET', `/api/profiles/${enc(name)}/memory`);
  const notes = (target, label) => {
    const n = m.notes[target];
    const pct = n.limit ? Math.min(100, Math.round((n.used / n.limit) * 100)) : 0;
    return section(label,
      h('div', { class: 'usage-line' }, h('div', { class: 'bar' }, h('span', { style: { width: `${pct}%` } })), t('{used}/{limit} chars', { used: n.used, limit: n.limit })),
      n.entries.length ? n.entries.map(e => h('div', { class: 'p-entry' }, e)) : h('div', { class: 'p-empty' }, t('Empty.')));
  };
  const exps = m.experiences.map(e => {
    const cls = e.outcome === 'success' ? 'pill-ok' : e.outcome === 'failure' ? 'pill-err' : 'pill-amber';
    return h('div', { class: 'p-card' },
      h('div', { class: 'exp-head' }, h('span', { class: `pill ${cls}` }, OUTCOME_NAMES[e.outcome] || e.outcome), h('span', { class: 'time', title: fullTime(e.created) }, relTime(e.created))),
      h('div', { class: 'exp-task' }, e.task),
      e.summary ? h('div', { class: 'exp-sum' }, e.summary) : null,
      e.lessons && e.lessons.length ? h('details', null, h('summary', null, e.procedure
        ? plural(e.lessons.length, '{n} lesson + procedure', '{n} lessons + procedure') : plural(e.lessons.length, '{n} lesson', '{n} lessons')),
        h('ul', null, e.lessons.map(l => h('li', null, l))), e.procedure ? h('pre', null, e.procedure) : null) : null,
      h('div', { class: 'exp-meta', title: t('Utility = smoothed success rate of tasks that reused this experience; it weights retrieval.') },
        t('used {uses}× · {helpful} helpful · {unhelpful} unhelpful', { uses: e.uses, helpful: e.helpful, unhelpful: e.unhelpful }),
        h('div', { class: 'bar ok' }, h('span', { style: { width: `${Math.round(e.utility * 100)}%` } })), e.utility.toFixed(2)));
  });
  const skills = m.skills.map(s => {
    const views = s.views || 0;
    const saves = s.saves || 0;
    const usage = [t('viewed {n}×', { n: views }), t('saved {n}×', { n: saves })];
    if (s.last_view) usage.push(t('last used {when}', { when: ago(s.last_view) }));
    return h('div', { class: 'p-card' },
      h('details', null, h('summary', null, h('strong', null, s.name), s.description ? ` — ${s.description}` : ''), h('pre', null, s.content)),
      h('div', { class: 'skill-meta' + (views ? '' : ' unused'),
        title: [s.last_view ? t('Last viewed {time}', { time: fullTime(s.last_view) }) : t('Never viewed by the agent'), s.last_save ? t('Last saved {time}', { time: fullTime(s.last_save) }) : '']
          .filter(Boolean).join('\n') }, usage.join(' · ')));
  });
  const events = m.events.slice(0, 30).map(ev => {
    const d = ev.detail || {};
    const what = d.content || d.task || d.name || (d.ids ? t('{n} item(s)', { n: d.ids.length }) : '') || d.after || (d.removed && d.removed.join('; ')) || '';
    return h('div', { class: 'ev-row', title: fullTime(ev.ts) }, h('span', { class: 'time' }, relTime(ev.ts)),
      h('span', { class: 'what' }, h('strong', null, `${ev.store} ${ev.op}`), what ? ` · ${what}` : ''));
  });
  return h('div', null,
    notes('memory', t('Agent notes (MEMORY.md)')),
    notes('user', t('About the user (USER.md)')),
    section([t('Experiences ({n})', { n: m.experience_count })],
      exps.length ? exps : h('div', { class: 'p-empty' }, t('No experiences yet. After each task the agent reflects and records what worked; relevant ones are recalled before similar tasks.'))),
    section(t('Skills ({n})', { n: m.skills.length }), skills.length ? skills : h('div', { class: 'p-empty' }, t('No skills saved yet.'))),
    section(t('Recent memory activity'), events.length ? h('div', null, events) : h('div', { class: 'p-empty' }, t('Nothing yet.'))));
}

function taskList(tasks, emptyText) {
  if (!tasks.length) return h('div', { class: 'p-empty pad' }, emptyText);
  const order = ['in_progress', 'todo', 'blocked', 'failed', 'done'];
  const counts = order.map(s => [s, tasks.filter(x => x.status === s).length]).filter(([, n]) => n);
  const sorted = [...tasks].sort((a, b) => order.indexOf(a.status) - order.indexOf(b.status) || a.created - b.created);
  return h('div', null,
    h('div', { class: 'board-summary' }, counts.map(([s, n]) => h('span', { class: `pill status-${s}` }, `${n} ${statusName(s)}`))),
    sorted.map(task => {
      const who = task.assignee ? profileOf(task.assignee) : null;
      return h('div', { class: 'task' },
        h('div', { class: 'task-head' }, h('div', { class: 'task-title' }, task.title), statusPill(task.status)),
        h('div', { class: 'task-meta' },
          who ? [avatar(who, 18), `@${task.assignee}`] : t('unassigned'),
          h('span', null, `· ${t('by @{name}', { name: task.created_by })}`), h('span', { title: fullTime(task.updated) }, `· ${relTime(task.updated)}`)),
        task.description ? h('details', null, h('summary', null, t('Details')), h('div', null, task.description)) : null,
        task.result ? h('details', null, h('summary', null, task.status === 'failed' ? t('Error') : t('Result')), h('div', null, task.result)) : null);
    }));
}

async function agentTasksPanel() {
  const name = C.view.profile;
  const tasks = await api('GET', `/api/board/${enc('dm:' + name)}`);
  return h('div', null, section(t('Delegated by @{name}', { name }),
    taskList(tasks, t('When @{name} delegates work outside a group, the subtasks and their results are tracked here.', { name }))));
}

async function sessionsPanel() {
  const name = C.view.profile;
  const list = await api('GET', `/api/profiles/${enc(name)}/sessions?limit=200`);
  if (!list.length) return h('div', { class: 'p-empty pad' }, t('No sessions yet.'));
  const open = s => {
    if (s.kind === 'bot_chat') return go(`#/bot/${enc(name)}`);
    if (name === 'default' && s.kind === 'chat') return go(`#/chat/${enc(s.id)}`);
    return go(`#/session/${enc(name)}/${enc(s.id)}`);
  };
  return section(t('Sessions of @{name}', { name }), list.map(s => h('div', { class: 'sess-row' + (C.view.sid === s.id ? ' active' : ''), onclick: () => open(s), title: fullTime(s.updated) },
    h('span', { class: 'pill' }, kindLabel(s.kind)), h('span', { class: 't' }, s.title || t('(untitled)')),
    s.todos && s.todos.length ? (st => h('span', { class: 'plan-mini', title: t('Plan: {progress}', { progress: planTitle(st) }) }, `${st.done}/${st.total}`))(planStats(s.todos)) : null,
    s.busy ? h('span', { class: 'dot busy' }) : s.interrupted ? h('span', { class: 'pill pill-amber' }, t('interrupted')) : null,
    h('span', { class: 'time' }, relTime(s.updated)))));
}

function field(label, input, help) {
  return h('div', { class: 'field' }, h('label', null, label), input, help ? h('div', { class: 'help' }, help) : null);
}

function modelSelect(current, provider) {
  if (provider && provider !== 'deepseek') {
    // HKGAI model ids come from its console; empty means the model set under Settings → Model
    return h('input', { type: 'text', value: current || '', placeholder: (S.status && S.status.model) || t('model id'), spellcheck: 'false' });
  }
  const models = (S.status && S.status.models) || ['deepseek-flash', 'deepseek-v4-pro'];
  const opts = models.includes(current) || !current ? models : [current, ...models];
  return h('select', null, opts.map(m => h('option', { value: m, selected: m === current }, m)));
}

const BACKEND_HELP = {
  'local+seatbelt': t('Commands run on this machine in the bot’s workspace, confined by macOS Seatbelt: no file access elsewhere in your home folder or PlanD’s data.'),
  local: t('Commands run on this machine with your user’s permissions (not an OS sandbox); risky commands ask first.'),
  docker: t('Commands run in an isolated Docker container that only sees the bot’s workspace.'),
};
/** Backend names as the server labels them (BACKEND_LABELS in server/app.py), so the label can be translated here. */
const BACKEND_NAMES = { 'local+seatbelt': t('local (sandboxed)'), local: 'local', docker: 'docker' };
const backendLabel = p => BACKEND_NAMES[p.backend_effective] || p.backend_label || (p.backend === 'docker' ? 'docker' : 'local');

/** "local (sandboxed)" pill + one-line explanation under a backend select, following its value. */
function backendHelpLine(select, osSandbox = 'auto') {
  const line = h('div', { class: 'help muted backend-help' });
  const update = () => {
    const eff = select.value === 'docker' ? 'docker' : S.status && S.status.seatbelt && osSandbox !== 'off' ? 'local+seatbelt' : 'local';
    const label = BACKEND_NAMES[eff] || ((S.status && S.status.backend_labels) || {})[eff] || eff;
    line.replaceChildren(h('span', { class: 'pill pill-backend' }, label), h('span', null, BACKEND_HELP[eff] || ''));
  };
  select.addEventListener('change', update);
  update();
  return line;
}

function backendSelect(current, osSandbox = 'auto') {
  const docker = S.status && S.status.docker;
  const sandboxed = !!(S.status && S.status.seatbelt) && osSandbox !== 'off';
  return h('select', null,
    h('option', { value: 'local', selected: current !== 'docker', title: BACKEND_HELP[sandboxed ? 'local+seatbelt' : 'local'] },
      sandboxed ? t('local (sandboxed)') : t('local — this machine')),
    h('option', { value: 'docker', selected: current === 'docker', disabled: docker === false && current !== 'docker', title: BACKEND_HELP.docker },
      docker === false ? t('docker (not available)') : t('docker — container')));
}

// Thinking intensity (pland/llm/reasoning.py): the bot's default here, per chat in the composer menu. Each provider
// offers its own levels; HKGAI's only switch is the level (it rejects minimal and medium), so its Default sends high.
// A value a provider no longer offers (an older 'minimal' or 'medium') stays listed with its label: see reasoningOptions.
const REASONING = [
  ['off', t('Off'), t('No thinking: fastest and cheapest')],
  ['default', t('Default'), t('Thinking at DeepSeek\u2019s default depth (what the evaluation used)')],
  ['minimal', t('Minimal'), t('The shortest reasoning')],
  ['low', t('Low'), t('Short reasoning')],
  ['medium', t('Medium'), t('Moderate reasoning')],
  ['high', t('High'), t('Thorough reasoning')],
  ['xhigh', t('Extra high'), t('More thorough than High')],
  ['max', t('Max'), t('Deepest: about twice the thinking of High')],
];
const REASONING_LEVELS = { deepseek: ['low', 'medium', 'high', 'max'], hkgai: ['low', 'high', 'xhigh', 'max'] };
const REASONING_HELP = { hkgai: { default: t("High (HKGAI's depth when no level is sent)"), max: t('Deepest reasoning') } };
const canThink = provider => !!REASONING_LEVELS[provider];
const reasoningName = v => (REASONING.find(r => r[0] === v) || REASONING[1])[1];

/** [value, label, help] for what `provider` offers, keeping `current` listed even if it does not offer it. */
function reasoningOptions(provider, current) {
  const offered = ['off', 'default', ...(REASONING_LEVELS[provider] || REASONING_LEVELS.deepseek)];
  return REASONING.filter(([v]) => offered.includes(v) || v === current)
    .map(([v, label, help]) => [v, label, (REASONING_HELP[provider] || {})[v] || help]);
}

function reasoningSelect(current, provider) {
  const value = current || 'default';
  return h('select', null, reasoningOptions(provider, value).map(([v, label, help]) =>
    h('option', { value: v, selected: v === value, title: help }, `${label} \u2014 ${help}`)));
}

async function agentSettingsPanel() {
  const name = C.view.profile;
  const p = await api('GET', `/api/profiles/${enc(name)}`);
  const s = p.settings;
  const title = h('input', { type: 'text', value: p.title });
  const desc = h('input', { type: 'text', value: p.description || '', placeholder: t('What this bot is good at (teammates see this)') });
  const soul = h('textarea', { rows: 8 });
  soul.value = p.soul || '';
  const model = modelSelect(s.model, p.provider);
  const thinking = reasoningSelect(s.reasoning, p.provider);
  const backend = backendSelect(s.backend, s.os_sandbox);
  const approvals = h('select', null,
    h('option', { value: 'manual', selected: s.approvals !== 'off' }, t('Ask me before risky operations')),
    h('option', { value: 'off', selected: s.approvals === 'off' }, t('Never ask (hard safety floor still applies)')));
  const color = h('input', { type: 'color', class: 'color-input', value: p.avatar });
  const toolsets = (S.status && S.status.toolsets) || s.toolsets;
  const tsBoxes = toolsets.map(ts => h('label', { class: 'check' }, h('input', { type: 'checkbox', value: ts, checked: s.toolsets.includes(ts) }), ts));
  const err = h('span', { class: 'form-error' });
  const save = h('button', { type: 'button', class: 'btn btn-primary' }, t('Save'));
  const current = () => ({
    title: title.value.trim() || name, description: desc.value.trim(), soul: soul.value, model: model.value,
    reasoning: thinking.value, backend: backend.value, approvals: approvals.value, avatar: color.value,
    toolsets: tsBoxes.map(l => l.firstChild).filter(c => c.checked).map(c => c.value),
  });
  const loaded = current();
  save.onclick = async () => {
    save.disabled = true;
    err.textContent = '';
    try {
      // Only what changed: an untouched field keeps following the global default (Settings), instead of being
      // pinned to today's value for this bot.
      const now = current();
      const changed = Object.fromEntries(Object.entries(now).filter(([k, v]) => JSON.stringify(v) !== JSON.stringify(loaded[k])));
      if (!Object.keys(changed).length) { toast(t('Nothing changed')); return; }
      await api('PATCH', `/api/profiles/${enc(name)}`, changed);
      Object.assign(loaded, changed);
      toast(t('Saved'));
      await loadProfiles();
      renderHead();
    } catch (e) { err.textContent = e.message; } finally { save.disabled = false; }
  };
  const form = h('div', { class: 'p-section' },
    h('div', { class: 'field-row' }, field(t('Name'), title), field(t('Color'), color)),
    field(t('Description'), desc),
    field(t('SOUL (persona & standing instructions)'), soul, t('Changes apply to new sessions; existing sessions keep the prompt they started with.')),
    h('div', { class: 'field-row' }, field(t('Model'), model), field(t('Sandbox'), backend)),
    backendHelpLine(backend, s.os_sandbox),
    field(t('Thinking intensity'), thinking, t('The bot\u2019s default. Any chat can override it from the Thinking menu under the message box.')),
    field(t('Approvals'), approvals),
    h('div', { class: 'field' }, h('div', { class: 'label' }, t('Toolsets')), h('div', { class: 'checks' }, tsBoxes)),
    h('div', { class: 'help muted', style: { fontSize: '11.5px', marginBottom: '10px' } }, t('Workspace: {path}. Settings this bot has never changed follow the global defaults in', { path: p.workspace }), ' ',
      h('button', { type: 'button', class: 'link-btn', onclick: () => openSettings('model') }, t('Settings')), t('.')),
    h('div', { class: 'form-actions' }, err, save));
  if (name !== 'default') {
    form.append(h('div', { class: 'danger-zone' }, h('div', { class: 'form-actions' },
      h('span', { class: 'help muted spacer', style: { fontSize: '12px' } }, t('Deleting removes this bot’s memory, sessions and workspace.')),
      h('button', {
        type: 'button', class: 'btn btn-danger', onclick: async () => {
          if (!confirm(t('Delete @{name}? Its memory, sessions and workspace are removed permanently.', { name }))) return;
          try { await api('DELETE', `/api/profiles/${enc(name)}`); await loadProfiles(); loadRooms(); go('#/chat'); } catch (e) { toast(e.message, 'error'); }
        },
      }, t('Delete bot')))));
  }
  return form;
}

async function boardPanel() {
  const tasks = await api('GET', `/api/rooms/${enc(C.view.roomId)}/tasks`);
  return h('div', null,
    C.view.board ? null : h('button', { type: 'button', class: 'btn btn-ghost btn-sm board-open', onclick: () => go(`#/room/${enc(C.view.roomId)}/board`) }, t('Open as board \u2192')),
    taskList(tasks, t('No tasks yet. When the lead breaks the goal down, subtasks, owners and results appear here.')));
}

async function membersPanel() {
  const room = await api('GET', `/api/rooms/${enc(C.view.roomId)}`);
  if (C && C.view.type === 'room') C.room = { ...(C.room || {}), ...room };
  return section(t('Members ({n})', { n: room.member_info.length }), room.member_info.map(m => h('div', { class: 'member' },
    avatar(m, 32, profileBusy(m.name)),
    h('div', { class: 'm-main' },
      h('div', { class: 'm-title' }, m.title, h('span', { class: 'handle' }, `@${m.name}`), room.lead === m.name ? h('span', { class: 'star', title: t('Lead') }, t('★ lead')) : null),
      h('div', { class: 'm-desc' }, profileBusy(m.name) ? workingText(m.name) : (tsExact(m.description) || ''))),
    m.missing ? null : h('button', { type: 'button', class: 'btn btn-ghost btn-sm', onclick: () => go(`#/bot/${enc(m.name)}`) }, t('Chat')),
    room.lead === m.name || m.missing ? null : h('button', {
      type: 'button', class: 'btn btn-ghost btn-sm', title: t('Make this bot the default lead'),
      onclick: async () => { try { await api('PATCH', `/api/rooms/${enc(room.id)}`, { lead: m.name }); renderPanel({ keepScroll: true }); loadRooms(); } catch (e) { toast(e.message, 'error'); } },
    }, t('Make lead')))),
  h('div', { class: 'p-empty', style: { marginTop: '10px' } }, t('Each member works in its own workspace with its own memory; the group shares only the room transcript, the board and the shared/ folder.')));
}

async function roomSettingsPanel() {
  const room = await api('GET', `/api/rooms/${enc(C.view.roomId)}`);
  const form = groupForm(room);
  const err = h('span', { class: 'form-error' });
  const save = h('button', { type: 'button', class: 'btn btn-primary' }, t('Save'));
  save.onclick = async () => {
    err.textContent = '';
    const v = form.values();
    if (!v.members.length) { err.textContent = t('Pick at least one bot.'); return; }
    save.disabled = true;
    try {
      await api('PATCH', `/api/rooms/${enc(room.id)}`, { name: v.name, members: v.members, lead: v.lead, max_rounds: v.maxRounds, fast_mode: v.fast });
      toast(t('Saved'));
      loadRooms();
      loadRoom();
      C.room = null;
      renderHead();
    } catch (e) { err.textContent = e.message; } finally { save.disabled = false; }
  };
  return h('div', { class: 'p-section' }, form.el, h('div', { class: 'form-actions' }, err, save),
    h('div', { class: 'danger-zone' }, h('div', { class: 'form-actions' },
      h('span', { class: 'help muted spacer', style: { fontSize: '12px' } }, t('Deleting removes the group transcript and board link; bots keep their own memory.')),
      h('button', {
        type: 'button', class: 'btn btn-danger', onclick: async () => {
          if (!confirm(t('Delete the group "{name}"?', { name: room.name }))) return;
          try { await api('DELETE', `/api/rooms/${enc(room.id)}`); loadRooms(); go('#/chat'); } catch (e) { toast(e.message, 'error'); }
        },
      }, t('Delete group')))));
}

// --- files (read-only browser of a bot's workspace or a room's shared/ folder)
const FS = new Map();  // 'agent:<profile>' | 'room:<id>' -> { dir, file } (open folder, previewed file)
const fsState = key => { if (!FS.has(key)) FS.set(key, { dir: '', file: null }); return FS.get(key); };
const parentDir = path => (path.includes('/') ? path.slice(0, path.lastIndexOf('/')) : '');
const fmtSize = n => (n == null ? '' : n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(n < 10240 ? 1 : 0)} KB` : `${(n / 1048576).toFixed(1)} MB`);
const MD_FILE = /\.(md|markdown)$/i;

function filesTarget() {
  if (C.view.type === 'room') {
    return { key: `room:${C.view.roomId}`, base: `/api/rooms/${enc(C.view.roomId)}/files`, root: 'shared',
      empty: t('Nothing in the shared folder yet. Files the team writes under shared/ appear here.') };
  }
  const name = C.view.profile;
  if (C.session && C.session.workspace_custom && C.view.sid) {
    return { key: `ws:${name}:${C.view.sid}`, base: `/api/profiles/${enc(name)}/files`, q: `&session=${enc(C.view.sid)}`,
      root: baseName(C.session.workspace), empty: t('This folder is empty.') };
  }
  return { key: `agent:${name}`, base: `/api/profiles/${enc(name)}/files`, root: t('workspace'),
    empty: t('No files yet. What @{name} writes in its workspace appears here.', { name }) };
}

function fsGo(st, dir, file = null) {
  st.dir = dir;
  st.file = file;
  renderPanel();
}

function fsBar(target, st) {
  const parts = st.dir ? st.dir.split('/') : [];
  const crumb = (label, dir, cur) => (cur ? h('span', { class: 'crumb cur' }, label)
    : h('button', { type: 'button', class: 'crumb', onclick: () => fsGo(st, dir) }, label));
  const crumbs = [crumb(target.root, '', !st.dir && !st.file)];
  parts.forEach((p, i) => {
    const dir = parts.slice(0, i + 1).join('/');
    crumbs.push(h('span', { class: 'crumb-sep' }, '/'), crumb(p, dir, dir === st.dir && !st.file));
  });
  if (st.file) crumbs.push(h('span', { class: 'crumb-sep' }, '/'), crumb(st.file.split('/').pop(), null, true));
  return h('div', { class: 'fs-bar' }, h('div', { class: 'crumbs' }, crumbs), iconBtn('refresh', t('Refresh'), () => renderPanel({ keepScroll: true })));
}

async function filesPanel() {
  const target = filesTarget();
  const st = fsState(target.key);
  if (st.file) {
    let f;
    try {
      f = await api('GET', `${target.base}/content?path=${enc(st.file)}${target.q || ''}`);
    } catch (e) {
      return h('div', null, fsBar(target, st), h('div', { class: 'p-empty' }, e.status === 404 ? t('This file no longer exists.') : e.message));
    }
    return h('div', null, fsBar(target, st),
      h('div', { class: 'fs-meta' }, fmtSize(f.size), ' · ', h('span', { title: fullTime(f.mtime) }, t('modified {when}', { when: ago(f.mtime) })),
        f.truncated ? h('span', { class: 'warn' }, ` · ${t('showing the first {size}', { size: fmtSize(new Blob([f.content]).size) })}`) : null),
      MD_FILE.test(f.name) ? h('div', { class: 'md fs-md', html: md(f.content) })
        : h('pre', { class: 'fs-code' }, f.content || t('(empty file)')));
  }
  let d;
  try {
    d = await api('GET', `${target.base}?path=${enc(st.dir)}${target.q || ''}`);
  } catch (e) {
    if (e.status === 404 && st.dir) { st.dir = ''; return filesPanel(); }  // the folder is gone: back to the root
    return h('div', null, fsBar(target, st), h('div', { class: 'p-empty' }, e.message));
  }
  const row = (cls, icon, label, onOpen, ...meta) => h('div', {
    class: `fs-row ${cls}`, role: 'button', tabindex: '0', onclick: onOpen,
    onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onOpen(); } },
  }, h('span', { class: 'fs-icon', html: ICON[icon] }), h('span', { class: 'fs-name' }, label), ...meta);
  const rows = d.entries.map(e => row(e.is_dir ? 'dir' : 'file', e.is_dir ? 'folder' : 'file', e.name,
    () => (e.is_dir ? fsGo(st, e.path) : fsGo(st, d.path, e.path)),
    h('span', { class: 'fs-size' }, e.is_dir ? '' : fmtSize(e.size)),
    h('span', { class: 'fs-time', title: fullTime(e.mtime) }, relTime(e.mtime))));
  return h('div', null, fsBar(target, st),
    d.path ? row('up', 'folder', '..', () => fsGo(st, d.parent || '')) : null,
    rows.length ? rows : h('div', { class: 'p-empty' }, d.path ? t('Empty folder.') : target.empty),
    d.truncated ? h('div', { class: 'p-empty' }, t('Only the first entries are listed.')) : null);
}

/** Open a file written by the agent of the open conversation in the Files tab (a room's shared/
 * folder when the path is shared/… and the session belongs to a room). */
function openInFiles(path) {
  if (!C || C.view.type === 'room') return;
  const roomId = C.session && C.session.room_id;
  if (roomId && (path === 'shared' || path.startsWith('shared/'))) {
    const rel = path.replace(/^shared\/?/, '');
    Object.assign(fsState(`room:${roomId}`), { dir: parentDir(rel), file: rel || null });
    P.tab.room = 'files';
    P.forcePanel = true;
    go(`#/room/${enc(roomId)}`);
    return;
  }
  Object.assign(fsState(`agent:${C.view.profile}`), { dir: parentDir(path), file: path });
  P.tab.agent = 'files';
  S.panelOpen = true;
  if (!isNarrow()) prefs.set('panelOpen', true);
  renderHead();
  renderPanel();
}

const PANEL_BUILDERS = {
  room: { board: boardPanel, members: membersPanel, files: filesPanel, settings: roomSettingsPanel },
  agent: { memory: memoryPanel, files: filesPanel, tasks: agentTasksPanel, sessions: sessionsPanel, settings: agentSettingsPanel },
};

// ====================================================================== settings page
// A full-window sheet. Appearance belongs to this browser (localStorage); Model, Agent, Sandbox
// and Run limits are the global defaults every bot inherits (PLAND_HOME/settings.yaml via /api/settings) — a bot's
// own value, set in its details panel, still wins. Rows come from one manifest so search covers all of them.
const SET = { open: false, section: 'appearance', q: '', data: null, loadError: null, recent: null, range: '7d', errors: {}, rows: new Map(), returnFocus: null, saving: 0 };
const SWATCHES = [['vermilion', t('Vermilion'), '#d4441c'], ['ultramarine', t('Ultramarine'), '#2f49d1'], ['jade', t('Jade'), '#17775c'], ['graphite', t('Graphite'), '#2a2723']];
const PROVIDER_NAMES = { deepseek: 'DeepSeek', hkgai: 'HKGAI' };

const SETTINGS = [
  { id: 'appearance', label: t('Appearance'), icon: 'palette', lede: t('How PlanD looks in this browser. Kept in this browser only; other browsers keep their own.'), groups: [
    { title: t('Theme'), rows: [
      { key: 'theme', scope: 'ui', kind: 'seg', label: t('Colour mode'), desc: t('Follow the system, or stay light or dark.'), options: [['system', t('System')], ['light', t('Light')], ['dark', t('Dark')]], keywords: 'dark light night' },
      { key: 'accent', scope: 'ui', kind: 'swatches', label: t('Accent'), desc: t('The stamp colour: send button, active rows, work in progress.'), keywords: 'colour color' },
      { key: 'lang', scope: 'ui', kind: 'seg', label: t('Language'), desc: t('The language of the interface. Auto follows the browser. Messages and names are not translated.'),
        options: [['auto', t('Auto')], ['en', LANG_NAMES.en], ['zh-Hant', LANG_NAMES['zh-Hant']]], keywords: 'language locale english chinese traditional 語言 中文 繁體', reload: true },
    ] },
    { title: t('Reading'), rows: [
      { key: 'size', scope: 'ui', kind: 'seg', label: t('Chat text size'), desc: t('Messages and the message box.'), options: [['small', t('Small')], ['default', t('Default')], ['large', t('Large')]], keywords: 'font zoom' },
      { key: 'reasoning', scope: 'ui', kind: 'seg', label: t('Thinking blocks'), desc: t('The model’s reasoning, when the provider returns it.'), options: [['collapsed', t('Collapsed')], ['hide', t('Hidden')]], keywords: 'reasoning chain of thought' },
      { key: 'density', scope: 'ui', kind: 'seg', label: t('Sidebar density'), desc: t('Compact drops the preview line under each conversation.'), options: [['comfortable', t('Comfortable')], ['compact', t('Compact')]] },
    ] },
    { title: t('Layout'), rows: [
      { key: 'sideCollapsed', scope: 'ui', kind: 'switch', invert: true, label: t('Show the sidebar'), desc: () => t('Also {key}, or drag its edge almost shut.', { key: keyLabel('mod+b') }), keywords: 'hide collapse left' },
      { key: 'sideWidth', scope: 'ui', kind: 'range', label: t('Sidebar width'), desc: t('Or drag the sidebar’s right edge; double-click the edge to reset.'), min: 220, max: 440, step: 4, unit: 'px', keywords: 'resize size' },
      { key: 'panelDefault', scope: 'ui', kind: 'seg', label: t('Details panel'), desc: () => t('Memory, files, tasks and bot settings beside the conversation ({key}).', { key: keyLabel('mod+.') }), options: [['remember', t('Remember')], ['closed', t('Start closed')]], keywords: 'right panel' },
      { key: 'panelWidth', scope: 'ui', kind: 'range', label: t('Details panel width'), desc: t('Or drag the panel’s left edge.'), min: 300, max: 640, step: 4, unit: 'px', keywords: 'resize size' },
    ] },
  ] },
  { id: 'model', label: t('Model'), icon: 'cube', lede: t('Defaults for the main chat and every bot that has not chosen its own. Any chat can still switch model and thinking from the message box.'), groups: [
    { title: t('Provider and keys'), rows: [
      { key: 'provider', kind: 'custom', render: providerRow, label: t('Provider in use'), keywords: 'deepseek hkgai switch' },
      { key: 'key-deepseek', kind: 'custom', render: keyRow, provider: 'deepseek', label: t('DeepSeek API key'), keywords: 'api key secret token sk- deepseek' },
    ] },
    { title: t('HKGAI (optional)'), rows: [
      { key: 'key-hkgai', kind: 'custom', render: keyRow, provider: 'hkgai', label: t('HKGAI API key'), keywords: 'api key secret token hkgai' },
      { key: 'hkgai-url', kind: 'custom', render: endpointRow, provider: 'hkgai', field: 'base_url', label: t('HKGAI endpoint'), placeholder: 'https://…/v1', desc: t('The OpenAI-compatible base URL from your HKGAI console (https only).'), keywords: 'base url endpoint hkgai' },
      { key: 'hkgai-model', kind: 'custom', render: endpointRow, provider: 'hkgai', field: 'model', label: t('HKGAI model'), placeholder: t('model id'), desc: t('The model id from your HKGAI console.'), keywords: 'model hkgai' },
    ] },
    { title: t('Defaults'), rows: [
      { key: 'model', scope: 'global', kind: 'model', label: t('Model'), desc: t('Flash is fast and cheap (the evaluated default); V4 Pro is stronger at several times the price.') },
      { key: 'reasoning', scope: 'global', kind: 'select', label: t('Thinking intensity'), keywords: 'reasoning effort minimal xhigh',
        desc: () => (setProvider() === 'hkgai' ? t('Off is fastest. On HKGAI, Default means High.') : t('Off is fastest; Max thinks about twice as long as High.')),
        options: () => reasoningOptions(setProvider(), settingValue({ key: 'reasoning' })).map(([v, l, d]) => [v, `${l} — ${d}`]) },
      { key: 'max_tokens', scope: 'global', kind: 'number', label: t('Output limit per reply'), desc: t('Thinking counts toward it. It only bounds runaway output: you pay for tokens produced, not for the cap.'), unit: t('tokens'), min: 1024, max: 393216, step: 1024 },
      { key: 'stream', scope: 'global', kind: 'switch', label: t('Stream replies'), desc: t('Show a reply while it is being written.') },
    ] },
  ] },
  { id: 'behaviour', label: t('Agent'), icon: 'shield', lede: t('How agents ask before acting, and what they keep from a finished task.'), groups: [
    { title: t('Approvals'), rows: [
      { key: 'approvals', scope: 'global', kind: 'seg', label: t('Before risky operations'), desc: t('Ask me: flagged operations wait for you. Smart: a model check allows routine commands and workspace file cleanup, rejects unsafe operations and asks about uncertain risks. Git push, credentials and publishing still ask unless already authorized. Never: no prompts; the hard safety floor still applies.'), options: [['manual', t('Ask me')], ['smart', t('Smart')], ['off', t('Never')]], keywords: 'hitl permission approve', warn: v => (v === 'off' ? t('Agents will run risky commands without asking.') : '') },
      { key: 'approval_timeout', scope: 'global', kind: 'number', label: t('Wait for an answer'), desc: t('After this, an unanswered request counts as not approved.'), unit: t('s'), min: 30, max: 3600, step: 30 },
      { key: 'unattended', scope: 'global', kind: 'seg', label: t('When nobody can answer'), desc: t('Background runs with no one to ask, such as an evaluation.'), options: [['deny', t('Deny')], ['approve', t('Approve')]], warn: v => (v === 'approve' ? t('Risky operations in background runs will go ahead without asking.') : '') },
    ] },
    { title: t('Learning'), rows: [
      { key: 'reflection', scope: 'global', kind: 'switch', label: t('Reflect after each task'), desc: t('Writes a short lesson into the bot’s experience memory.'), keywords: 'memory experience' },
      { key: 'background_reflection', scope: 'global', kind: 'switch', label: t('Reflect in the background'), desc: t('Return the answer first and reflect afterwards.') },
      { key: 'experience_top_k', scope: 'global', kind: 'number', label: t('Past experiences recalled'), desc: t('Similar past tasks added to a new task’s prompt. 0 turns recall off.'), min: 0, max: 10, step: 1, keywords: 'memory' },
    ] },
  ] },
  { id: 'sandbox', label: t('Sandbox & folders'), icon: 'box', lede: t('Where commands run and what they can touch.'), groups: [
    { title: t('Execution'), rows: [
      { key: 'backend', scope: 'global', kind: 'seg', label: t('Backend'), desc: t('Local runs on this machine in the conversation’s folder; Docker runs in a container that only sees that folder.'), options: [['local', t('Local')], ['docker', 'Docker']], keywords: 'container isolation',
        warn: v => (v === 'docker' && S.status && S.status.docker === false ? t('Docker is not available on this machine; runs will fail until it is.') : '') },
      { key: 'os_sandbox', scope: 'global', kind: 'seg', label: t('macOS Seatbelt'), desc: t('Confines local commands: no access elsewhere in your home folder or to PlanD’s data.'), options: [['auto', t('On')], ['off', t('Off')]], keywords: 'sandbox-exec isolation',
        warn: v => (v === 'off' ? t('Local commands will run with your full user rights.') : S.status && !S.status.seatbelt ? t('Seatbelt exists only on macOS: local commands here are not confined. Use Docker for isolation.') : '') },
      { key: 'command_timeout', scope: 'global', kind: 'number', label: t('Command timeout'), desc: t('A shell or Python command running longer is stopped.'), unit: t('s'), min: 5, max: 1800, step: 5 },
    ] },
    { title: 'Docker', rows: [
      { key: 'docker_network', scope: 'global', kind: 'seg', label: t('Network'), desc: t('None cuts the container off the network (web tools still work; they run outside it).'), options: [['bridge', t('Bridge')], ['none', t('None')]] },
      { key: 'docker_memory', scope: 'global', kind: 'text', label: t('Memory'), desc: t('Per container, e.g. 512m or 2g.'), placeholder: '1g' },
      { key: 'docker_cpus', scope: 'global', kind: 'number', label: t('CPUs'), desc: t('Per container.'), min: 0.25, max: 16, step: 0.25 },
    ] },
    { title: t('Folders'), rows: [{ key: 'folders', kind: 'custom', render: foldersRow, label: t('Conversation folders'), keywords: 'workspace directory cwd' }] },
  ] },
  { id: 'limits', label: t('Run limits'), icon: 'gauge', lede: t('Caps for one run, shared by every delegate and subagent it starts; a group’s turn gets twice the call and token caps. Reaching a cap ends the run with a summary — it never carries on silently.'), groups: [
    { title: t('Per run'), rows: [
      { key: 'max_iterations', scope: 'global', kind: 'number', label: t('Steps per agent'), desc: t('Model calls one agent may make in a run. A checkpoint at 80% makes it write its deliverables first.'), min: 1, max: 200, step: 5, keywords: 'iterations' },
      { key: 'max_run_calls', scope: 'global', kind: 'number', label: t('Model calls per run'), desc: t('All agents of the run together.'), min: 10, max: 2000, step: 10, keywords: 'budget' },
      { key: 'max_run_tokens', scope: 'global', kind: 'number', label: t('Tokens per run'), desc: t('Weighted: a cache hit counts as 0.1 token. 8M is roughly $1 at DeepSeek’s peak prices.'), unit: t('tokens'), min: 100000, max: 50000000, step: 500000, keywords: 'budget cost' },
    ] },
    { title: t('Teams'), rows: [
      { key: 'max_parallel_delegations', scope: 'global', kind: 'number', label: t('Delegations at once'), desc: t('Teammates or subagents working in parallel for one agent.'), min: 1, max: 8, step: 1 },
      { key: 'max_delegation_depth', scope: 'global', kind: 'number', label: t('Delegation depth'), desc: t('How far work may be handed on (A asks B, B asks C…).'), min: 1, max: 4, step: 1 },
      { key: 'fast_review_steps', scope: 'global', kind: 'number', label: t('Fast Mode review steps'), min: 1, max: 200, step: 1 },
      { key: 'fast_review_seconds', scope: 'global', kind: 'number', label: t('Fast Mode initial review timeout'), unit: t('s'), min: 1, max: 900, step: 1 },
      { key: 'fast_followup_seconds', scope: 'global', kind: 'number', label: t('Fast Mode revision review timeout'), unit: t('s'), min: 1, max: 900, step: 1 },
      { key: 'review_max_steps', scope: 'global', kind: 'number', label: t('Steps per independent review'), desc: t('Bots can request fewer steps for a review.'), min: 1, max: 200, step: 1 },
      { key: 'review_timeout_seconds', scope: 'global', kind: 'number', label: t('Independent review timeout'), desc: t('Bots can request less time for a review.'), unit: t('s'), min: 1, max: 900, step: 1 },
    ] },
    { title: t('Context'), rows: [
      { key: 'context_char_budget', scope: 'global', kind: 'number', label: t('Compaction threshold'), desc: t('When a conversation the model sees grows past this, older tool output is folded away (about 4 characters per token).'), unit: t('chars'), min: 50000, max: 2000000, step: 50000, keywords: 'compress memory' },
    ] },
  ] },
  { id: 'usage', label: t('Usage'), icon: 'chart', custom: usageSection, lede: t('Every model call is recorded in the ledger, without message content. Costs use DeepSeek’s list prices; your provider’s console has the bill.'), keywords: 'cost tokens billing ledger money' },
  { id: 'keys', label: t('Keyboard'), icon: 'keyboard', custom: keysSection, lede: t('Shortcuts that work anywhere in PlanD.'), keywords: 'shortcuts hotkeys' },
  { id: 'about', label: t('About'), icon: 'info', custom: aboutSection, lede: t('This installation.'), keywords: 'version data folder home github' },
];

const settingDesc = row => (typeof row.desc === 'function' ? row.desc() : row.desc || '');
const settingOptions = row => (typeof row.options === 'function' ? row.options() : row.options || []);
function settingValue(row) { return row.scope === 'ui' ? ui[row.key] : SET.data ? SET.data.values[row.key] : undefined; }
function settingDefault(row) { return row.scope === 'ui' ? UI_DEFAULTS[row.key] : SET.data ? SET.data.defaults[row.key] : undefined; }
function settingIsSet(row) { return row.scope === 'ui' ? ui[row.key] !== UI_DEFAULTS[row.key] : !!(SET.data && SET.data.stored.includes(row.key)); }
function settingText(row, v) {
  if (row.kind === 'switch') return (row.invert ? !v : v) ? t('on') : t('off');
  if (row.kind === 'swatches') return (SWATCHES.find(s => s[0] === v) || [, v])[1];
  const o = settingOptions(row).find(x => x[0] === v);
  if (o) return o[1].split(' — ')[0];
  return typeof v === 'number' ? `${v.toLocaleString(LOCALE)}${row.unit ? ' ' + row.unit : ''}` : String(v);
}

function openSettings(section) {
  if (section) SET.section = section;
  SET.q = '';
  if (!SET.open) SET.returnFocus = document.activeElement;
  SET.open = true;
  document.body.classList.remove('sidebar-open');
  $('#settings').classList.remove('hidden');
  $('#app').inert = true;
  renderSettings();
  loadSettings();
  const search = $('#settings .set-search input');
  if (search && window.innerWidth > 760) search.focus();
}

function closeSettings() {
  if (!SET.open) return;
  SET.open = false;
  $('#settings').classList.add('hidden');
  $('#settings').replaceChildren();
  $('#app').inert = false;
  const back = SET.returnFocus;
  SET.returnFocus = null;
  if (back && back.isConnected && back.focus) back.focus({ preventScroll: true });
}

/** Fetch the global settings; `quiet` (a live update) re-renders only if something actually changed, so a save made
 *  here does not redraw the page under the user's focus. */
async function loadSettings(quiet = false) {
  if (quiet && SET.saving) return;  // our own save: its response brings the new values
  const before = JSON.stringify([SET.data, SET.recent]);
  try {
    const [data, recent] = await Promise.all([api('GET', '/api/settings'), api('GET', '/api/workspaces/recent').catch(() => [])]);
    SET.data = data;
    SET.recent = recent;
    SET.loadError = null;
  } catch (e) { SET.loadError = e.message; }
  if (SET.open && !(quiet && before === JSON.stringify([SET.data, SET.recent]))) { renderSettingsMain(); renderSettingsNav(); }
}

function renderSettings() {
  const search = h('div', { class: 'set-search' }, h('span', { html: ICON.search }),
    h('input', { type: 'search', placeholder: t('Search settings'), 'aria-label': t('Search settings'), value: SET.q,
      oninput: e => { SET.q = e.target.value.trim(); renderSettingsNav(); renderSettingsMain(); } }));
  const nav = h('nav', { class: 'set-nav', 'aria-label': t('Settings sections') }, search, h('div', { class: 'set-nav-items' }));
  const main = h('div', { class: 'set-main' });
  $('#settings').replaceChildren(h('div', { class: 'set-card' }, nav, main,
    iconBtn('close', t('Close settings (Esc)'), closeSettings, 'set-close')));
  renderSettingsNav();
  renderSettingsMain();
}

function renderSettingsNav() {
  const box = $('#settings .set-nav-items');
  if (!box) return;
  box.style.display = 'contents';
  box.replaceChildren(...SETTINGS.map(s => h('button', {
    type: 'button', class: 'set-nav-item' + (!SET.q && s.id === SET.section ? ' on' : ''), 'aria-current': !SET.q && s.id === SET.section ? 'page' : null,
    onclick: () => { SET.section = s.id; SET.q = ''; const i = $('#settings .set-search input'); if (i) i.value = ''; renderSettingsNav(); renderSettingsMain(); $('#settings .set-main').scrollTop = 0; },
  }, h('span', { html: ICON[s.icon] }), s.label)),
  h('div', { class: 'set-nav-foot', title: SET.data ? SET.data.file : '' }, t('Model, agent, sandbox and limits are global defaults, saved in settings.yaml in PlanD\u2019s data folder.')));
}

function settingMatches(row, section, q) {
  return [row.label, settingDesc(row), row.keywords, section.label].join(' ').toLowerCase().includes(q);
}

function renderSettingsMain() {
  const main = $('#settings .set-main');
  if (!main) return;
  const scroll = main.scrollTop;
  const focused = document.activeElement && main.contains(document.activeElement) && document.activeElement.closest('.set-row');
  const focusKey = focused && focused.dataset.key;
  SET.rows.clear();
  const saved = h('span', { class: 'set-saved', id: 'set-saved' }, t('● saved'));
  if (SET.q) {
    const q = SET.q.toLowerCase();
    const out = [h('div', { class: 'set-crumb' }, t('Settings'), h('span', { class: 'sep' }, '/'), t('Search'), saved), h('h2', null, `“${SET.q}”`)];
    let hits = 0;
    for (const s of SETTINGS) {
      const rows = (s.groups || []).flatMap(g => g.rows).filter(r => settingMatches(r, s, q));
      const sectionHit = s.custom && [s.label, s.lede, s.keywords].join(' ').toLowerCase().includes(q);
      if (!rows.length && !sectionHit) continue;
      hits += rows.length + (sectionHit ? 1 : 0);
      out.push(h('div', { class: 'set-hit-section' }, s.label));
      out.push(...rows.map(settingRow));
      if (sectionHit) out.push(h('div', { class: 'set-row' }, h('div', null, h('div', { class: 'set-label' }, s.label), h('div', { class: 'set-desc' }, s.lede)),
        h('div', { class: 'set-control' }, h('button', { type: 'button', class: 'btn btn-sm', onclick: () => { SET.q = ''; SET.section = s.id; renderSettings(); } }, t('Open {section} →', { section: s.label })))));
    }
    if (!hits) out.push(h('div', { class: 'set-empty' }, t('No setting matches. Try “theme”, “approvals” or “tokens”.')));
    main.replaceChildren(...out);
    return;
  }
  const s = SETTINGS.find(x => x.id === SET.section) || SETTINGS[0];
  const head = [h('div', { class: 'set-crumb' }, t('Settings'), h('span', { class: 'sep' }, '/'), s.label, saved), h('h2', null, s.label), s.lede ? h('p', { class: 'set-lede' }, s.lede) : null];
  if (SET.loadError && !s.custom && s.id !== 'appearance') head.push(h('div', { class: 'set-note err' }, t('Could not load the global settings: {error}', { error: SET.loadError })));
  if (s.custom) {
    const box = h('div', null);
    main.replaceChildren(...head, box);
    s.custom(box);
  } else {
    main.replaceChildren(...head, ...s.groups.map(g => h('section', { class: 'set-group' }, h('div', { class: 'set-group-title' }, g.title), g.rows.map(settingRow))));
  }
  main.scrollTop = scroll;
  const again = focusKey && main.querySelector(`.set-row[data-key="${focusKey}"] :is(.seg .on, .swatch.on, input, select)`);
  if (again) again.focus({ preventScroll: true });
}

function flashSaved() {
  const el = $('#set-saved');
  if (!el) return;
  el.classList.add('on');
  clearTimeout(flashSaved.t);
  flashSaved.t = setTimeout(() => el.classList.remove('on'), 1400);
}

function settingRow(row) {
  if (row.kind === 'custom') return row.render(row);
  const value = settingValue(row);
  const loading = row.scope === 'global' && !SET.data;
  const notes = [];
  if (row.warn && !loading) { const w = row.warn(value); if (w) notes.push(h('div', { class: 'set-note' }, w)); }
  const others = row.scope === 'global' && SET.data && SET.data.overrides[row.key];
  if (others && others.length) {
    notes.push(h('div', { class: 'set-note info' }, others.length === 1 ? t('Has its own value: ') : t('Have their own value: '),
      others.map((n, i) => [i ? t(', ') : '', h('button', { type: 'button', class: 'link-btn', title: t('Open @{name}', { name: n }), onclick: () => { closeSettings(); go(n === 'default' ? '#/chat' : `#/bot/${enc(n)}`); } }, n === 'default' ? t('the main chat') : `@${n}`)])));
  }
  if (SET.errors[row.key]) notes.push(h('div', { class: 'set-note err' }, SET.errors[row.key]));
  const reset = settingIsSet(row) && !loading
    ? h('button', { type: 'button', class: 'set-reset', title: t('Back to the built-in default'), onclick: () => saveSetting(row, row.scope === 'ui' ? UI_DEFAULTS[row.key] : null) }, t('reset · {value}', { value: settingText(row, settingDefault(row)) }))
    : null;
  const el = h('div', { class: 'set-row', dataset: { key: `${row.scope}:${row.key}` } },
    h('div', null, h('div', { class: 'set-label' }, row.label, reset), h('div', { class: 'set-desc' }, settingDesc(row)), notes),
    h('div', { class: 'set-control' }, loading ? h('span', { class: 'set-unit' }, t('loading…')) : settingControl(row, value)));
  SET.rows.set(row, el);
  return el;
}

function settingControl(row, value) {
  const save = v => saveSetting(row, v);
  switch (row.kind) {
    case 'seg':
      return h('div', { class: 'seg', role: 'group', 'aria-label': row.label }, settingOptions(row).map(([v, label]) =>
        h('button', { type: 'button', class: v === value ? 'on' : '', 'aria-pressed': String(v === value), onclick: () => v !== value && save(v) }, label)));
    case 'swatches':
      return h('div', { class: 'swatches', role: 'group', 'aria-label': row.label }, SWATCHES.map(([v, label, color]) =>
        h('button', { type: 'button', class: 'swatch' + (v === value ? ' on' : ''), title: label, 'aria-label': label, 'aria-pressed': String(v === value), style: { background: color }, onclick: () => save(v) })));
    case 'switch':
      return h('label', { class: 'switch' }, h('input', { type: 'checkbox', role: 'switch', 'aria-label': row.label, checked: row.invert ? !value : !!value,
        onchange: e => save(row.invert ? !e.target.checked : e.target.checked) }), h('span'));
    case 'select':
    case 'model': {
      let opts = row.kind === 'model' ? MODELS.map(([v, label]) => [v, `${label} · ${v}`]) : settingOptions(row);
      if (row.kind === 'model' && SET.data && SET.data.provider.name !== 'deepseek') {
        return h('input', { type: 'text', value: value || '', 'aria-label': row.label, onchange: e => save(e.target.value.trim() || null) });
      }
      if (value && !opts.some(o => o[0] === value)) opts = [[value, value], ...opts];
      return h('select', { 'aria-label': row.label, onchange: e => save(e.target.value) }, opts.map(([v, label]) => h('option', { value: v, selected: v === value }, label)));
    }
    case 'number':
      return [h('input', { type: 'number', 'aria-label': row.label, min: row.min, max: row.max, step: row.step, value: value ?? '',
        onchange: e => save(e.target.value === '' ? null : Number(e.target.value)) }), row.unit ? h('span', { class: 'set-unit' }, row.unit) : null];
    case 'text':
      return h('input', { type: 'text', 'aria-label': row.label, value: value ?? '', placeholder: row.placeholder || '', onchange: e => save(e.target.value.trim() || null) });
    case 'range': {
      const out = h('span', { class: 'set-unit' }, `${value}${row.unit}`);
      return h('div', { class: 'set-range' }, h('input', { type: 'range', 'aria-label': row.label, min: row.min, max: row.max, step: row.step, value,
        oninput: e => { out.textContent = `${e.target.value}${row.unit}`; document.documentElement.style.setProperty(row.key === 'sideWidth' ? '--side-w' : '--panel-w', `${e.target.value}px`); },
        onchange: e => save(Number(e.target.value)) }), out);
    }
    default: return null;
  }
}

async function saveSetting(row, value) {
  delete SET.errors[row.key];
  if (row.scope === 'ui') {
    setUi(row.key, value);
    if (row.reload) { location.reload(); return; }  // the language: the page is rebuilt in the new one
    flashSaved();
  } else {
    SET.saving++;
    try {
      SET.data = await api('PATCH', '/api/settings', { [row.key]: value });
      flashSaved();
      loadProfiles().then(() => { if (C) { renderHead(); renderPickers(); } }).catch(() => {});
    } catch (e) { SET.errors[row.key] = e.message; } finally { SET.saving--; }
  }
  const old = SET.rows.get(row);
  if (!old || !old.isConnected) return renderSettingsMain();
  const hadFocus = old.contains(document.activeElement);
  const fresh = settingRow(row);
  old.replaceWith(fresh);
  if (hadFocus) { const f = fresh.querySelector('.seg .on, .swatch.on, input, select'); if (f) f.focus(); }
}

const providerInfo = name => (SET.data && SET.data.keys ? SET.data.keys.providers.find(p => p.name === name) : null);
const setProvider = () => (SET.data ? SET.data.provider.name : 'deepseek');
SET.notes = {};  // result line under a key / provider row, kept across redraws: { text, kind: 'ok' | 'err' | 'warn' }
const noteEl = id => { const n = SET.notes[id]; return n ? h('div', { class: `set-note ${n.kind === 'ok' ? 'ok' : n.kind === 'err' ? 'err' : ''}` }, n.text) : null; };

/** Key and provider changes go to their own endpoints (pland/keys.py); the response is the whole settings view. */
async function keyCall(id, method, path, body) {
  SET.saving++;  // the live "settings.updated" echo of this change must not redraw the page mid-call
  try {
    const r = await api(method, path, body);
    SET.data = r;
    SET.notes[id] = { text: ts(r.notice) || t('Saved.'), kind: /precedence|comes back|insufficient|falls back/.test(r.notice || '') ? 'warn' : 'ok' };
    flashSaved();
    loadStatus().then(() => renderBanner());
    loadProfiles().then(() => { if (C) { renderHead(); renderPickers(); } }).catch(() => {});
    return true;
  } catch (e) {
    SET.notes[id] = { text: e.message, kind: 'err' };
    return false;
  } finally {
    SET.saving--;
    renderSettingsMain();
  }
}

function providerRow(row) {
  const k = SET.data && SET.data.keys;
  const cur = k && k.current;
  const control = k ? h('div', { class: 'seg', role: 'group', 'aria-label': row.label }, k.providers.map(p => h('button', {
    type: 'button', class: p.name === cur ? 'on' : '', 'aria-pressed': String(p.name === cur), disabled: p.name !== cur && !p.ready,
    title: p.ready ? t('Use {provider} for every agent', { provider: p.label })
      : t('{provider} needs {what}', { provider: p.label, what: [!p.key_set && t('an API key'), !p.base_url && t('an endpoint'), !p.model && t('a model')].filter(Boolean).join(t(', ')) }),
    onclick: () => p.name !== cur && keyCall('provider', 'PATCH', '/api/settings/provider', { provider: p.name }),
  }, p.label))) : h('span', { class: 'set-unit' }, t('loading…'));
  const info = providerInfo(cur);
  return h('div', { class: 'set-row', dataset: { key: 'custom:provider' } },
    h('div', null,
      h('div', { class: 'set-label' }, row.label),
      h('div', { class: 'set-desc' }, t('Every agent uses this provider. Only DeepSeek and HKGAI endpoints are accepted; anything else is refused by a hard guard.')),
      info ? h('div', { class: 'set-desc' }, h('span', { class: 'set-code' }, info.base_url || t('no endpoint')), ' · ', h('span', { class: 'set-code' }, info.model || t('no model'))) : null,
      noteEl('provider')),
    h('div', { class: 'set-control' }, control));
}

/** Where a key was found, as pland/keys.py describes it (`_describe`); other values are file names. */
const KEY_SOURCES = { 'shell environment': t('shell environment'), 'PlanD data folder (.env)': t('PlanD data folder (.env)'), 'installation folder (.env)': t('installation folder (.env)') };
function keyRow(row) {
  const p = providerInfo(row.provider);
  const id = `key-${row.provider}`;
  const input = h('input', { type: 'password', autocomplete: 'off', spellcheck: 'false', 'aria-label': row.label,
    placeholder: p && p.key_set ? t('Paste a new key to replace it') : t('Paste your API key') });
  const busy = h('span', { class: 'set-unit hidden' }, t('testing…'));
  const save = test => async () => {
    const key = input.value.trim();
    if (!key) { input.focus(); return; }
    busy.classList.toggle('hidden', !test);
    buttons.forEach(b => { b.disabled = true; });
    if (await keyCall(id, 'PUT', `/api/settings/keys/${enc(row.provider)}`, { key, test })) input.value = '';
  };
  const remove = async () => {
    if (!confirm(t('Remove the {provider} API key? Agents using {provider} stop working until you add one again.', { provider: p.label }))) return;
    await keyCall(id, 'DELETE', `/api/settings/keys/${enc(row.provider)}`);
  };
  const buttons = [
    h('button', { type: 'button', class: 'btn btn-primary btn-sm', onclick: save(true) }, t('Save & test')),
    h('button', { type: 'button', class: 'btn btn-ghost btn-sm', onclick: save(false), title: t('Save without the test call') }, t('Save only')),
  ];
  input.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); save(true)(); } });
  const where = !SET.data ? '' : p && p.key_set ? t('Stored in the {source}.', { source: KEY_SOURCES[p.key_source] || p.key_source }) : t('Will be saved to {file}.', { file: SET.data.keys.env_file });
  return h('div', { class: 'set-row wide', dataset: { key: `custom:${id}` } }, h('div', null,
    h('div', { class: 'set-label' }, row.label, p ? h('span', { class: `pill ${p.key_set ? 'pill-ok' : 'pill-err'}` }, p.key_set ? t('key set') : t('no key')) : null),
    h('div', { class: 'set-desc' }, [where, t('Keys are kept only in that .env file (readable by your user alone) and are never shown again.'),
      t('Save & test first makes one tiny call to check the key; nothing is saved if it is rejected.'),
      row.provider === 'deepseek' ? t('Web search and fetch always use this key, also with HKGAI as the provider (HKGAI has no search API).') : ''].filter(Boolean).join(LANG === 'en' ? ' ' : '')),
    h('div', { class: 'key-form' }, input, ...buttons, busy,
      p && p.key_set ? h('button', { type: 'button', class: 'btn btn-ghost btn-sm key-remove', onclick: remove }, t('Remove')) : null),
    noteEl(id)));
}

function endpointRow(row) {
  const p = providerInfo(row.provider);
  const id = `${row.provider}-${row.field}`;
  const value = p ? (row.field === 'base_url' ? p.base_url : p.model) || '' : '';
  const input = h('input', { type: 'text', value, placeholder: row.placeholder, 'aria-label': row.label, spellcheck: 'false',
    onchange: e => keyCall(id, 'PATCH', '/api/settings/provider', { endpoint: { provider: row.provider, [row.field]: e.target.value.trim() } }) });
  return h('div', { class: 'set-row', dataset: { key: `custom:${id}` } },
    h('div', null, h('div', { class: 'set-label' }, row.label), h('div', { class: 'set-desc' }, row.desc), noteEl(id)),
    h('div', { class: 'set-control' }, p ? input : h('span', { class: 'set-unit' }, t('loading…'))));
}

function foldersRow() {
  const list = SET.recent || [];
  return h('div', { class: 'set-row wide' }, h('div', null,
    h('div', { class: 'set-label' }, t('Conversation folders')),
    h('div', { class: 'set-desc' }, t('Each chat and group can work in a folder of your choice: click the folder name under the conversation title. A bot keeps one Bot Chat per folder.')),
    list.length ? h('div', { class: 'recent-dirs', style: { marginTop: '10px' } }, list.map(d => h('span', { class: 'chip-btn', title: d }, d)))
      : h('div', { class: 'set-desc', style: { marginTop: '6px' } }, t('No folders used yet.')),
    S.status ? h('div', { class: 'set-desc', style: { marginTop: '10px' } }, t('PlanD’s own data (memory, transcripts, settings) lives in'), ' ', h('span', { class: 'set-code' }, S.status.home), t('.')) : null));
}

async function usageSection(box) {
  const ranges = [['today', t('Today')], ['7d', t('7 days')], ['30d', t('30 days')], ['all', t('All time')]];
  const day = 86400;
  const midnight = new Date(); midnight.setHours(0, 0, 0, 0);
  const since = { today: midnight / 1000, '7d': midnight / 1000 - 6 * day, '30d': midnight / 1000 - 29 * day, all: null }[SET.range];
  const seg = h('div', { class: 'seg', role: 'group', 'aria-label': t('Period') }, ranges.map(([v, label]) =>
    h('button', { type: 'button', class: v === SET.range ? 'on' : '', 'aria-pressed': String(v === SET.range), onclick: () => { SET.range = v; renderSettingsMain(); } }, label)));
  box.replaceChildren(seg, h('div', { class: 'set-empty' }, t('Loading…')));
  let u;
  try { u = await api('GET', `/api/usage${since ? `?since=${Math.floor(since)}` : ''}`); } catch (e) { box.replaceChildren(seg, h('div', { class: 'set-note err' }, e.message)); return; }
  if (!box.isConnected) return;
  const tokens = u.prompt_tokens + u.completion_tokens;
  const stat = (k, v, s) => h('div', { class: 'set-stat' }, h('div', { class: 'k' }, k), h('div', { class: 'v' }, v), h('div', { class: 's' }, s));
  const out = [seg, h('div', { class: 'set-stats' },
    stat(t('Calls'), fmtNum(u.calls), t('{time} of model time', { time: fmtDur(u.model_seconds) })),
    stat(t('Tokens'), fmtNum(tokens), t('{n} written', { n: fmtNum(u.completion_tokens) })),
    stat(t('Cache hits'), `${Math.round(u.cache_hit_rate * 100)}%`, t('of prompt tokens')),
    stat(t('Cost'), `$${u.cost_usd.toFixed(u.cost_usd < 10 ? 3 : 2)}`, (u.models || []).join(' · ') || t('no calls')))];
  if (SET.range !== 'today') {
    const days = new Map(u.by_day.map(d => [d.day, d]));
    const n = SET.range === '7d' ? 7 : 30;
    const keys = SET.range === 'all' ? u.by_day.map(d => d.day) : Array.from({ length: n }, (_, i) => {
      const d = new Date(midnight.getTime() - (n - 1 - i) * day * 1000);
      return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    });
    const peak = Math.max(1e-9, ...keys.map(k => (days.get(k) || {}).cost_usd || 0));
    if (keys.length) {
      out.push(h('section', { class: 'set-group' }, h('div', { class: 'set-group-title' }, t('Cost per day')),
        h('div', { class: 'u-days' }, keys.map(k => {
          const d = days.get(k) || { calls: 0, cost_usd: 0, prompt_tokens: 0, completion_tokens: 0 };
          return h('div', { class: 'u-day', style: { height: `${Math.max(d.calls ? 3 : 1, (d.cost_usd / peak) * 100)}%`, opacity: d.calls ? '' : '.25' },
            title: t('{day}: {calls} calls, {tokens} tokens, ${cost}', { day: k, calls: d.calls, tokens: fmtNum(d.prompt_tokens + d.completion_tokens), cost: d.cost_usd.toFixed(3) }) });
        })),
        h('div', { class: 'u-days-axis' }, h('span', null, keys[0]), h('span', null, keys[keys.length - 1]))));
    }
  }
  const rows = [...(u.by_profile || [])].sort((a, b) => b.cost_usd - a.cost_usd);
  const top = Math.max(1e-9, ...rows.map(r => r.cost_usd));
  out.push(h('section', { class: 'set-group' }, h('div', { class: 'set-group-title' }, t('By bot')),
    rows.length ? h('table', { class: 'u-table' },
      h('thead', null, h('tr', null, h('th', null, 'Bot'), h('th', { class: 'n' }, t('Calls')), h('th', { class: 'n' }, t('Tokens')), h('th', { class: 'n' }, t('Cache')), h('th', { class: 'n' }, t('Cost')), h('th', { style: { width: '22%' } }, ''))),
      h('tbody', null, rows.map(r => {
        const p = profileOf(r.profile);
        return h('tr', null,
          h('td', null, h('span', { class: 'u-who' }, avatar(p, 22), r.profile === 'default' ? t('Main chat') : `@${r.profile}`)),
          h('td', { class: 'n' }, fmtNum(r.calls)),
          h('td', { class: 'n' }, fmtNum(r.prompt_tokens + r.completion_tokens)),
          h('td', { class: 'n' }, r.prompt_tokens ? `${Math.round((r.cached_tokens / r.prompt_tokens) * 100)}%` : '—'),
          h('td', { class: 'n' }, `$${r.cost_usd.toFixed(3)}`),
          h('td', null, h('div', { class: 'u-bar', style: { width: `${(r.cost_usd / top) * 100}%` } })));
      })))
      : h('div', { class: 'set-empty' }, t('No model calls in this period.'))));
  box.replaceChildren(...out);
}

const SHORTCUTS = [
  [t('Show or hide the sidebar'), 'mod+b'], [t('Show or hide the details panel'), 'mod+.'], [t('Open settings'), 'mod+,'],
  [t('New chat'), 'shift+mod+o'], [t('Jump to the message box'), '/'], [t('Send'), 'enter'], [t('New line in a message'), 'shift+enter'],
  [t('Close settings, menus and dialogs'), 'escape'],
];
function keysSection(box) {
  box.replaceChildren(h('table', { class: 'keys' }, h('tbody', null, SHORTCUTS.map(([what, combo]) =>
    h('tr', null, h('td', null, what), h('td', null, h('kbd', null, combo.length === 1 ? combo : keyLabel(combo))))))),
  h('p', { class: 'set-desc', style: { marginTop: '14px' } }, t('In a group, type @ to mention a bot; ↑ ↓ pick one and Enter inserts it.')));
}

function aboutSection(box) {
  const st = S.status || {};
  const docker = st.docker === true ? t('available') : st.docker === false ? t('not available') : t('checking…');
  const kv = (k, v) => [h('dt', null, k), h('dd', null, v)];
  box.replaceChildren(
    h('div', { class: 'wordmark', style: { fontSize: '44px', margin: '6px 0 18px' } }, h('span', null, 'Plan'), h('span', { class: 'seal', 'aria-hidden': 'true' }, 'D')),
    h('dl', { class: 'set-kv' },
      kv(t('Version'), st.version || '—'),
      kv(t('Model'), st.provider ? `${PROVIDER_NAMES[st.provider] || st.provider} · ${st.model || t('not set')}` : '—'),
      kv(t('Data folder'), h('code', null, st.home || '—')),
      kv(t('Global settings'), h('code', null, SET.data ? SET.data.file : 'settings.yaml')),
      kv(t('Server'), st.uptime != null ? t('running for {time}', { time: fmtDur(st.uptime) }) : '—'),
      kv('Docker', docker),
      kv('macOS Seatbelt', st.seatbelt ? t('available (local commands are confined)') : t('not available on this system'))),
    h('section', { class: 'set-group' }, h('div', { class: 'set-group-title' }, t('Command line')),
      h('table', { class: 'keys' }, h('tbody', null, [
        ['pland', t('Chat in the terminal, working in the current folder')], ['pland desktop', t('Open this app (starts the server if needed)')],
        ['pland setup', t('Provider, key, model and thinking intensity')], ['pland team', t('Install a ready-made team of bots')],
      ].map(([cmd, what]) => h('tr', null, h('td', null, what), h('td', null, h('code', { class: 'set-code' }, cmd))))))),
    h('p', { class: 'set-desc', style: { marginTop: '16px' } }, t('Source and documentation:'), ' ',
      h('a', { href: 'https://github.com/victoryuanxichen/nlp_final_pland', target: '_blank', rel: 'noopener' }, 'github.com/victoryuanxichen/nlp_final_pland'), t('.')));
}

// ====================================================================== dialogs
function dialog({ title, subtitle, body, submitLabel, onSubmit }) {
  const err = h('span', { class: 'form-error' });
  const submit = h('button', { type: 'submit', class: 'btn btn-primary' }, submitLabel);
  const dlg = h('dialog', { class: 'dialog' });
  const form = h('form', { class: 'dialog-form', method: 'dialog' },
    h('div', { class: 'dialog-head' }, h('h2', null, title), subtitle ? h('p', null, subtitle) : null),
    h('div', { class: 'dialog-body' }, body),
    h('div', { class: 'dialog-foot' }, err,
      h('button', { type: 'button', class: 'btn', onclick: () => dlg.close() }, t('Cancel')), submit));
  form.addEventListener('submit', async e => {
    e.preventDefault();
    err.textContent = '';
    submit.disabled = true;
    try {
      if (await onSubmit() !== false) dlg.close();
    } catch (ex) { err.textContent = ex.message; } finally { submit.disabled = false; }
  });
  dlg.append(form);
  dlg.addEventListener('close', () => dlg.remove());
  document.body.append(dlg);
  dlg.showModal();
  return dlg;
}

const slug = s => s.toLowerCase().normalize('NFKD').replace(/[^a-z0-9_-]+/g, '-').replace(/^[-_]+|[-_]+$/g, '').slice(0, 32);
const PALETTE = ['#c8462a', '#33508c', '#4e7a4a', '#b07a1e', '#7a3e6a', '#2b7a78', '#5b6472', '#9a4a2e', '#6e7b2f', '#3a4fb8'];  // pigments (pland/profiles.py)

async function templatesDialog() {
  let list;
  try { list = await api('GET', '/api/team-templates'); } catch (e) { toast(e.message, 'error'); return; }
  if (!list.length) { toast(t('No team templates are installed.')); return; }
  let chosen = list[0].id;
  const overwrite = h('input', { type: 'checkbox' });
  const card = tpl => h('label', { class: 'tpl-card' },
    list.length > 1 ? h('input', { type: 'radio', name: 'tpl', value: tpl.id, checked: tpl.id === chosen, onchange: () => { chosen = tpl.id; } }) : null,
    h('div', { class: 'tpl-body' },
      h('div', { class: 'tpl-title' }, tsExact(tpl.title)), h('div', { class: 'help muted' }, tsExact(tpl.description)),
      h('table', { class: 'tpl-table' }, h('tbody', null, tpl.bots.map(b => h('tr', null,
        h('td', { class: 'handle' }, `@${b.name}`), h('td', null, b.title),
        h('td', { class: 'muted' }, t('thinking {level}', { level: reasoningName(b.reasoning || 'default') })),
        h('td', { class: 'muted' }, b.backend || 'local'),
        h('td', { class: 'muted tpl-tools' }, (b.toolsets || []).join(', ')))))),
      tpl.groups.map(g => h('div', { class: 'help' }, t('Group “{name}”: {members} · lead @{lead}', { name: g.name, members: g.members.map(m => '@' + m).join(', '), lead: g.lead })))));
  dialog({
    title: t('Team templates'),
    subtitle: t('Ready-made bots and groups for trying Bot Mode. Each bot gets its own memory, sessions and workspace; you can edit or delete them afterwards.'),
    submitLabel: t('Add team'),
    body: h('div', null, list.map(card),
      h('label', { class: 'check', style: { marginTop: '10px' } }, overwrite, t('Overwrite the settings of bots that already exist'))),
    onSubmit: async () => {
      const r = await api('POST', `/api/team-templates/${enc(chosen)}/apply${overwrite.checked ? '?update=true' : ''}`);
      await Promise.allSettled([loadProfiles(), loadRooms()]);
      S.tab = 'bots';
      renderSidebar();
      const made = r.groups.filter(g => g.status === 'created').map(g => g.name);
      const parts = [r.created.length && t('added {names}', { names: r.created.map(n => '@' + n).join(', ') }), r.updated.length && t('updated {n}', { n: r.updated.length }),
        r.skipped.length && t('kept {n} existing', { n: r.skipped.length }), made.length && t('created {names}', { names: made.join(t(' and ')) })];
      toast(parts.filter(Boolean).join(' \u00b7 ') || t('Nothing to add: the team is already here.'));
      r.notes.forEach(n => toast(n, 'warn'));
      const first = r.groups[0];
      if (first) go(`#/room/${enc(first.id)}`);
    },
  });
}

async function importTeamFile(file) {
  if (!file) return;
  const button = $('#import-team');
  button.disabled = true;
  try {
    if (file.size > 256 * 1024) throw new Error(t('Team files must be 256 KiB or smaller.'));
    let content;
    const bytes = await file.arrayBuffer();
    try { content = new TextDecoder('utf-8', { fatal: true }).decode(bytes); }
    catch { throw new Error(t('Save the team file as UTF-8 Markdown.')); }
    const team = await api('POST', '/api/team-templates/import', { content });
    S.tab = 'bots';
    await Promise.all([loadProfiles(), loadRooms()]);
    go(`#/room/${enc(team.group)}`);
    toast(team.created_group ? t('Created {name} with {count} bots.', { name: team.name, count: team.members.length })
      : t('Opened existing group {name}.', { name: team.name }));
  } catch (e) { toast(e.message, 'error'); }
  finally { button.disabled = false; }
}

function newBotDialog() {
  const title = h('input', { type: 'text', placeholder: t('e.g. Code Reviewer'), required: true, autofocus: true });
  const name = h('input', { type: 'text', placeholder: 'code-reviewer', pattern: '[a-z0-9][a-z0-9_\\-]{0,31}', required: true });
  let nameTouched = false;
  title.addEventListener('input', () => { if (!nameTouched) name.value = slug(title.value); });
  name.addEventListener('input', () => { nameTouched = true; });
  const desc = h('input', { type: 'text', placeholder: t('Reviews Python code for bugs and style') });
  const soul = h('textarea', { rows: 6, placeholder: t('Who is this bot and how should it work? e.g. "You are a meticulous reviewer. Read the code, run the tests, and report concrete issues with file:line references."') });
  const provider = S.status && S.status.provider;
  const model = modelSelect(provider && provider !== 'deepseek' ? '' : 'deepseek-flash', provider);
  const thinking = reasoningSelect('default', provider);
  const backend = backendSelect('local');
  const color = h('input', { type: 'color', class: 'color-input', value: PALETTE[Math.floor(Math.random() * PALETTE.length)] });
  const clone = h('select', null, h('option', { value: '' }, t('— start fresh —')),
    S.profiles.map(p => h('option', { value: p.name }, `${p.title} (@${p.name})`)));
  dialog({
    title: t('New bot'),
    subtitle: t('A bot is an agent with its own identity, memory, sessions and workspace. It gets a private Bot Chat and can join groups.'),
    submitLabel: t('Create bot'),
    body: h('div', null,
      h('div', { class: 'field-row' }, field(t('Name'), title), field(t('Handle'), name, t('Used for @mentions.'))),
      field(t('Description'), desc, t('One line; teammates and leads see it when deciding who should do what.')),
      field('SOUL', soul, t('Optional. Persona and standing instructions (SOUL.md).')),
      h('div', { class: 'field-row' }, field(t('Model'), model), field(t('Sandbox backend'), backend)),
      backendHelpLine(backend),
      field(t('Thinking intensity'), thinking, t('Deeper thinking is slower but plans multi-step work better.')),
      h('div', { class: 'field-row', style: { marginTop: '10px' } }, field(t('Color'), color), field(t('Clone memory & skills from'), clone))),
    onSubmit: async () => {
      const p = await api('POST', '/api/profiles', {
        name: name.value.trim(), title: title.value.trim(), description: desc.value.trim(), soul: soul.value.trim() || null,
        model: model.value, reasoning: thinking.value, backend: backend.value, avatar: color.value,
        clone_from: clone.value || null, bot: true,
      });
      await loadProfiles();
      S.tab = 'bots';
      go(`#/bot/${enc(p.name)}`);
    },
  });
}

async function setFastMode(room, on) {
  try {
    await api('PATCH', `/api/rooms/${enc(room.id)}`, { fast_mode: on });
    toast(on ? t('Fast Mode on — it applies from the next message.') : t('Fast Mode off — it applies from the next message.'));
    loadRooms();
    await loadRoom();
    renderHead();
  } catch (e) { toast(e.message, 'error'); }
}

function groupForm(room) {
  const name = h('input', { type: 'text', value: room ? room.name : '', placeholder: t('e.g. Build team'), required: true });
  const roster = bots();
  const current = room ? room.members : [];
  const boxes = roster.map(p => h('label', { class: 'check' },
    h('input', { type: 'checkbox', value: p.name, checked: current.includes(p.name) }), avatar(p, 22), h('span', null, p.title), h('span', { class: 'handle' }, `@${p.name}`)));
  const lead = h('select');
  const maxRounds = h('input', { type: 'number', min: 1, max: 10, value: room ? (room.settings && room.settings.max_rounds) || 3 : 3 });
  const fast = h('input', { type: 'checkbox', checked: room ? !!room.fast_mode : true });
  const checked = () => boxes.map(b => b.querySelector('input')).filter(c => c.checked).map(c => c.value);
  const fillLead = () => {
    const prev = lead.value || (room && room.lead) || '';
    const opts = checked();
    lead.replaceChildren(h('option', { value: '' }, t('Auto — first bot addressed')),
      ...opts.map(n => h('option', { value: n, selected: n === prev }, `@${n}`)));
  };
  boxes.forEach(b => b.querySelector('input').addEventListener('change', fillLead));
  fillLead();
  const el = h('div', null,
    field(t('Group name'), name),
    h('div', { class: 'field' }, h('div', { class: 'label' }, t('Members')),
      roster.length ? h('div', { class: 'member-picks' }, boxes) : h('div', { class: 'p-empty' }, t('Create a bot first.'))),
    h('div', { class: 'field-row' },
      field(t('Lead'), lead, t('Coordinates and delegates when addressed.')),
      field(t('Max rounds per message'), maxRounds)),
    h('div', { class: 'field' },
      h('label', { class: 'check' }, fast, h('span', null, t('Fast Mode'))),
      h('div', { class: 'help' }, t('Each bot keeps its reasoning level. Commands get 25 s each and 90 s per team request. Review limits for initial and revised work are set in Settings. Each card allows one revision and one continuation of unfinished work. A verdict applies to its criterion and file versions.'))));
  return { el, values: () => ({ name: name.value.trim(), members: checked(), lead: lead.value || null, maxRounds: parseInt(maxRounds.value, 10) || 3, fast: fast.checked }) };
}

function newGroupDialog() {
  if (!bots().length) {
    toast(t('Create a bot first — groups are made of bots.'), 'warn', { label: t('New bot'), fn: newBotDialog });
    return;
  }
  const form = groupForm(null);
  dialog({
    title: t('New group'),
    subtitle: t('Bots in a group share one conversation and a task board. Give the team a goal; the lead decomposes it and delegates to teammates.'),
    submitLabel: t('Create group'),
    body: form.el,
    onSubmit: async () => {
      const v = form.values();
      if (!v.name) throw new Error(t('Give the group a name.'));
      if (!v.members.length) throw new Error(t('Pick at least one bot.'));
      const room = await api('POST', '/api/rooms', { name: v.name, members: v.members, lead: v.lead, fast_mode: v.fast });
      if (v.maxRounds !== 3 || room.fast_mode !== v.fast) await api('PATCH', `/api/rooms/${enc(room.id)}`, { max_rounds: v.maxRounds, fast_mode: v.fast });
      await loadRooms();
      S.tab = 'bots';
      go(`#/room/${enc(room.id)}`);
    },
  });
}

// ====================================================================== events
function trackRun(ev) {
  const key = runKey(ev.profile, ev.session_id);
  const run = S.runs.get(key);
  switch (ev.type) {
    case 'run.started':
      S.runs.set(key, { profile: ev.profile, session_id: ev.session_id, room_id: ev.room_id, run_id: ev.run_id,
        role: ev.role, depth: ev.depth, state: 'thinking', tool: null, origin: ev.origin, plan_idle: 0, started: ev.ts });
      break;
    case 'run.finished': case 'run.failed':
      S.runs.delete(key);
      faceReact(ev.profile, ev.type === 'run.failed' ? 'error' : ev.status);
      break;
    case 'llm.request': if (run) Object.assign(run, { state: 'thinking', tool: null, iteration: ev.iteration }); break;
    case 'tool.started': if (run) Object.assign(run, { state: 'tool', tool: ev.tool }); break;
    case 'tool.finished':
      if (run) Object.assign(run, { state: 'thinking', tool: null, plan_idle: (run.plan_idle || 0) + (ev.tool === 'todo' ? 0 : 1) });
      break;
    case 'hitl.requested': if (run) run.state = 'waiting'; break;
    case 'hitl.resolved': if (run && run.state === 'waiting') run.state = 'tool'; break;
    case 'todo.updated': if (run) Object.assign(run, { todos: ev.todos || [], plan_idle: 0 }); break;
    case 'assistant.delta': if (run && run.state !== 'waiting') run.state = ev.kind === 'content' ? 'writing' : 'thinking'; break;
    case 'room.drive':
      if (ev.state === 'started') S.drives.set(ev.room_id, ev); else S.drives.delete(ev.room_id);
      break;
    default: break;
  }
}

/** How a run ended, for the toast (run.finished / run.failed `status`). */
const RUN_STATUS = { error: t('error'), budget_exceeded: t('budget exceeded'), loop_detected: t('loop detected') };
function onEvent(ev) {
  const type = ev.type;
  if (type === 'assistant.delta') {  // frequent: touch only the streaming bubble and, on a state change, the status
    const run = S.runs.get(runKey(ev.profile, ev.session_id));
    const before = run && run.state;
    trackRun(ev);
    onDelta(ev);
    if (run && run.state !== before) { renderLive(); renderSidebar(); renderBoardLive(); }
    return;
  }
  trackRun(ev);
  if (type === 'assistant.message' || type === 'tool.started' || type === 'run.finished' || type === 'run.failed') finishStream(ev);
  const v = C && C.view;
  const inConv = v && v.type !== 'room' && v.sid && ev.profile === v.profile && ev.session_id === v.sid;
  switch (type) {
    case 'run.started': case 'assistant.message': case 'tool.finished': case 'context.compacted':
      if (inConv) refreshConv();
      break;
    case 'run.finished': case 'run.failed':
      if (inConv) {
        refreshConv();
        if (type === 'run.failed' || ['error', 'budget_exceeded', 'loop_detected'].includes(ev.status)) {
          toast(`${t('Run ended: {status}', { status: RUN_STATUS[ev.status || 'error'] || ev.status })}${ev.error ? ' — ' + String(ev.error).split('\n')[0].slice(0, 140) : ''}`, 'error');
        }
      }
      refreshLists();
      refreshUsage();
      refreshPanel(['memory', 'sessions', 'tasks', 'files'], ev.profile);  // files: shell commands write files too
      break;
    case 'exec.finished':
      if (v?.type === 'room' && ev.room_id === v.roomId && C.room?.fast_mode && v.board) refreshTasks();
      break;
    case 'file.changed': {
      const shared = !!ev.room_id && /^shared(\/|$)/.test(String(ev.path || ''));
      if (v && v.type === 'room') {
        if (shared && ev.room_id === v.roomId) {
          refreshPanel(['files', 'board']);
          if (C.room?.fast_mode || C.tasks?.some(task => task.review)) refreshTasks();
        }
      } else if (!shared) refreshPanel(['files'], ev.profile);
      break;
    }
    case 'tool.started':
      if (inConv) markToolRunning(ev.call_id, ev.tool);
      break;
    case 'room.message':
      if (v && v.type === 'room' && v.roomId === ev.room_id) refreshRoom();
      refreshLists();
      break;
    case 'room.created': case 'room.updated': case 'room.deleted':
      refreshLists();
      if (v && v.type === 'room' && v.roomId === ev.room_id) {
        if (type === 'room.deleted') { toast(t('This group was deleted.')); go('#/chat'); } else { if (ev.room) C.room = { ...(C.room || {}), ...ev.room }; renderHead(); refreshPanel(['members']); }
      }
      break;
    case 'room.drive':
      if (ev.state === 'settled') {
        refreshLists();
        if (v && v.type === 'room' && v.roomId === ev.room_id) refreshPanel(['files']);
      }
      break;
    case 'task.updated':
      if (v && v.type === 'room' && ev.room_id === v.roomId) {
        refreshPanel(['board']); upsertTask(ev.task);
        if (C.room?.fast_mode) refreshTasks();
      }
      else if (v && v.type !== 'room' && ev.room_id === `dm:${v.profile}`) refreshPanel(['tasks']);
      break;
    case 'hitl.requested':
      refreshHitl();
      notifyHitl(ev);
      break;
    case 'hitl.resolved':
      refreshHitl();
      break;
    case 'memory.changed': case 'memory.corrected': case 'experience.added': case 'experience.retrieved':
      refreshPanel(['memory'], ev.profile);
      break;
    case 'todo.updated':
      if (inConv) C.todos = ev.todos || [];
      refreshPanel(['sessions'], ev.profile);
      break;
    case 'profile.created': case 'profile.updated': case 'profile.deleted':
      refreshLists();
      if (type === 'profile.deleted' && v && v.type !== 'room' && v.profile === ev.profile) {
        toast(t('@{name} was deleted.', { name: ev.profile }));
        go('#/chat');
      }
      break;
    case 'session.created': case 'session.updated': case 'session.deleted':
      if (ev.profile === 'default') refreshLists();
      refreshPanel(['sessions'], ev.profile);
      if (inConv && type === 'session.updated') loadConv();
      break;
    case 'stream.overflow':
      resync();
      break;
    case 'settings.updated':  // global defaults changed (here or in another window)
      refreshLists();
      if (SET.open) loadSettings(true);
      break;
    default: break;
  }
  if (HINT_EVENTS.has(type)) {
    // Rows for the open session come with the next fetch; everything else is a passing hint.
    if (inConv && ROW_EVENTS.has(type)) refreshConv();
    else if (eventInView(ev)) flashHint(ev);
  }
  if (type !== 'hello') {
    renderLive();
    renderPlan();
    updateComposer();
    renderSidebar();
    renderBoardLive();
  }
}

function renderConn() {
  const el = $('#conn');
  el.classList.toggle('down', !S.wsOk);
  el.replaceChildren(h('span', { class: 'dot' }), S.wsOk ? t('live') : t('reconnecting…'));
  el.title = S.wsOk ? t('Receiving live events') : t('Lost the event stream; retrying');
}

function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/api/events`);
  S.ws = ws;
  ws.onopen = () => {
    S.wsOk = true;
    S.wsRetry = 0;
    renderConn();
    if (S.wsWasDown) { S.wsWasDown = false; resync(); }
  };
  ws.onmessage = msg => {
    let ev;
    try { ev = JSON.parse(msg.data); } catch { return; }
    try { onEvent(ev); } catch (e) { console.error('event handler failed', ev, e); }
  };
  ws.onclose = () => {
    S.wsOk = false;
    S.wsWasDown = true;
    renderConn();
    const delay = Math.min(10000, 500 * 2 ** S.wsRetry++);
    setTimeout(connectWS, delay);
  };
  ws.onerror = () => { try { ws.close(); } catch { /* already closed */ } };
}

async function resync() {
  const c = C;
  await Promise.allSettled([loadStatus(), loadProfiles(), loadRooms(), loadChats(), loadHitl(), loadActivity(), loadUsage()]);
  if (C && C === c) openView(C.view, keepState(C));  // if the user moved on meanwhile, that view is fresh already
}

// ====================================================================== boot
/** Global shortcuts (Settings → Keyboard lists them). ⌘ on macOS, Ctrl elsewhere. */
function onShortcut(e) {
  const mod = IS_MAC ? e.metaKey : e.ctrlKey;
  const k = e.key.toLowerCase();
  if (e.key === 'Escape' && SET.open && !e.defaultPrevented) {
    if (document.activeElement && document.activeElement.type === 'search' && SET.q) return;  // first Esc clears the search
    e.preventDefault();
    closeSettings();
    return;
  }
  if (mod && !e.altKey) {
    if (k === ',' && !e.shiftKey) { e.preventDefault(); if (SET.open) closeSettings(); else openSettings(); return; }
    if (SET.open) return;
    if (k === 'b' && !e.shiftKey) { e.preventDefault(); toggleSidebar(); return; }
    if (k === '.' && !e.shiftKey) { e.preventDefault(); if (C) togglePanel(); return; }
    if (k === 'o' && e.shiftKey) { e.preventDefault(); go('#/chat'); return; }
    return;
  }
  const typing = e.target.closest && e.target.closest('input, textarea, select, [contenteditable="true"]');
  if (e.key === '/' && !typing && !SET.open && !document.querySelector('dialog[open]') && !$('#input').disabled && !(C && C.view.board)) {
    e.preventDefault();
    $('#input').focus();
  }
}

function bind() {
  applyUi();
  translateStatic();
  $('#side-collapse').innerHTML = ICON.sidebar;
  $('#side-collapse').title = t('Hide sidebar ({key})', { key: keyLabel('mod+b') });
  $('#side-collapse').addEventListener('click', toggleSidebar);
  $('#open-settings').replaceChildren(h('span', { html: ICON.gear }), t('Settings'), h('kbd', null, keyLabel('mod+,')));
  $('#open-settings').title = t('Settings ({key})', { key: keyLabel('mod+,') });
  $('#open-settings').addEventListener('click', () => openSettings());
  $('#usage').addEventListener('click', () => openSettings('usage'));
  $('#new-chat kbd').textContent = keyLabel('shift+mod+o');
  $('#new-chat').title = t('New chat ({key})', { key: keyLabel('shift+mod+o') });
  $$('.composer-hint kbd').forEach(k => { if (k.textContent === '⌘B') k.textContent = keyLabel('mod+b'); });
  makeResizer($('#side-resizer'), { key: 'sideWidth', min: 220, max: 440, collapse: true, fromPointer: e => e.clientX });
  makeResizer(P.resizer, { key: 'panelWidth', min: 300, max: 640, fromPointer: e => window.innerWidth - e.clientX });
  $('#settings').addEventListener('mousedown', e => { if (e.target === e.currentTarget) closeSettings(); });
  document.addEventListener('keydown', onShortcut);
  window.addEventListener('resize', debounce(() => { if (C) renderHead(); }, 150));
  $$('.side-tabs .tab').forEach(tab => tab.addEventListener('click', () => { S.tab = tab.dataset.tab; renderSidebar(); }));
  $('.side-tabs').addEventListener('keydown', e => {  // the ARIA tabs pattern: left/right (Home/End) select and focus a tab
    const tabs = $$('.side-tabs .tab');
    const i = tabs.indexOf(e.target);
    if (i < 0) return;
    const j = e.key === 'ArrowRight' ? (i + 1) % tabs.length : e.key === 'ArrowLeft' ? (i - 1 + tabs.length) % tabs.length
      : e.key === 'Home' ? 0 : e.key === 'End' ? tabs.length - 1 : -1;
    if (j < 0) return;
    e.preventDefault();
    S.tab = tabs[j].dataset.tab;
    renderSidebar();
    tabs[j].focus();
  });
  $('#new-chat').addEventListener('click', () => go('#/chat'));
  $('#new-bot').addEventListener('click', newBotDialog);
  $('#new-group').addEventListener('click', newGroupDialog);
  $('#team-templates').addEventListener('click', templatesDialog);
  $('#import-team').addEventListener('click', () => $('#team-file').click());
  $('#team-file').addEventListener('change', e => {
    const file = e.target.files[0];
    e.target.value = '';
    importTeamFile(file);
  });
  $('#hitl-badge').addEventListener('click', toggleTray);
  $('#tray').addEventListener('keydown', e => { if (e.key === 'Escape' && !e.defaultPrevented) { e.preventDefault(); closeTray(); } });
  $('#stop').addEventListener('click', stopRun);
  $('#composer').addEventListener('submit', e => { e.preventDefault(); send(); });
  $('#attach').addEventListener('click', () => $('#file-input').click());
  $('#file-input').addEventListener('change', e => { uploadFiles(e.target.files); e.target.value = ''; });
  const composer = $('#composer');
  composer.addEventListener('dragover', e => {
    if (!Array.from(e.dataTransfer.types || []).includes('Files') || $('#input').disabled) return;
    e.preventDefault();
    composer.classList.add('dropping');
  });
  composer.addEventListener('dragleave', e => { if (!composer.contains(e.relatedTarget)) composer.classList.remove('dropping'); });
  composer.addEventListener('drop', e => {
    composer.classList.remove('dropping');
    if (!e.dataTransfer.files.length) return;
    e.preventDefault();
    uploadFiles(e.dataTransfer.files);
  });
  $('#input').addEventListener('paste', e => {
    const pasted = Array.from((e.clipboardData && e.clipboardData.files) || []);
    if (pasted.length) { e.preventDefault(); uploadFiles(pasted); }
  });
  $('#think').addEventListener('click', () => togglePicker('reasoning'));
  $('#model-pick').addEventListener('click', () => togglePicker('model'));
  for (const kind of Object.keys(PICKERS)) {
    const k = PICKERS[kind];
    $(k.menu).addEventListener('keydown', e => pickerKey(kind, e));
    $(k.pill).addEventListener('keydown', e => {  // down / up on the pill opens the menu, like Enter
      if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && $(k.menu).classList.contains('hidden')) { e.preventDefault(); togglePicker(kind); }
    });
  }
  document.addEventListener('keydown', e => { if (e.key === 'Escape') Object.keys(PICKERS).forEach(k => closePicker(k)); });
  const input = $('#input');
  input.addEventListener('input', () => { autosize(); updateMentions(); });
  input.addEventListener('click', updateMentions);
  input.addEventListener('blur', () => setTimeout(closeMentions, 120));
  input.addEventListener('keydown', e => {
    if (M.open) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        M.sel = (M.sel + (e.key === 'ArrowDown' ? 1 : -1) + M.items.length) % M.items.length;
        updateMentions();
        return;
      }
      if ((e.key === 'Enter' || e.key === 'Tab') && !e.isComposing) { e.preventDefault(); pickMention(M.sel); return; }
      if (e.key === 'Escape') { closeMentions(); return; }
    }
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && e.keyCode !== 229) {
      e.preventDefault();
      send();
    }
  });
  document.addEventListener('click', e => {
    const btn = e.target.closest('.code-copy');
    if (btn) {
      const code = btn.closest('.code').querySelector('code').textContent;
      navigator.clipboard.writeText(code).then(() => { btn.textContent = t('Copied'); setTimeout(() => { btn.textContent = t('Copy'); }, 1200); }, () => toast(t('Copy failed'), 'error'));
    }
    if (document.body.classList.contains('sidebar-open') && !e.target.closest('.sidebar') && !e.target.closest('.menu-btn')) {
      document.body.classList.remove('sidebar-open');
    }
    const tray = $('#tray');
    if (!tray.classList.contains('hidden') && !e.target.closest('.tray') && !e.target.closest('#hitl-badge')) closeTray(false);
    if (!e.target.closest('.pick-wrap')) Object.keys(PICKERS).forEach(k => closePicker(k, false));
  });
  window.addEventListener('hashchange', route);
  scroller().addEventListener('scroll', () => { if (C && C.more && !C.loadingEarlier && scroller().scrollTop < 80) loadEarlier(); }, { passive: true });
  setInterval(() => { if (S.ws && S.ws.readyState === 1) S.ws.send('ping'); }, 25000);
  setInterval(() => { renderSidebar(); renderBoardLive(); }, 60000);  // keep relative times fresh
  setInterval(() => { if (S.runs.size) renderLive(); }, 5000);
  setInterval(faceTick, 120);
}

async function boot() {
  bind();
  renderConn();
  // not through t(): this is the message for when the dictionary itself is missing
  if (window.PLAND_DICT_FAILED) toast('The translation could not be loaded, so the interface is in English. Reload to try again.', 'warn');
  await Promise.allSettled([loadStatus(), loadProfiles(), loadRooms(), loadChats(), loadHitl(), loadActivity(), loadUsage()]);
  connectWS();
  route();
  const recovered = (S.status && S.status.recovered) || [];
  if (recovered.length) {
    const first = recovered[0];
    const target = first.kind === 'bot_chat' ? `#/bot/${enc(first.profile)}`
      : first.profile === 'default' && first.kind === 'chat' ? `#/chat/${enc(first.session_id)}` : `#/session/${enc(first.profile)}/${enc(first.session_id)}`;
    toast(plural(recovered.length, '{n} conversation was interrupted by the last shutdown and can be resumed.', '{n} conversations were interrupted by the last shutdown and can be resumed.'), 'warn',
      { label: t('Open'), fn: () => go(target) });
  }
}

boot();
