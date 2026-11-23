/* PlanD web UI — vanilla JS, no build step, no external dependencies.
 *
 * Layout (Hermes Desktop–style Bot Mode):
 *   sidebar   Chats (single-agent sessions of the default profile) | Bots (roster + group rooms)
 *   main      the conversation: messages, tool-call cards, activity rows, the streaming reply,
 *             HITL cards, the agent's plan (todo list), live status, composer
 *   panel     room: task board / members / settings; bot: memory / tasks / sessions / settings
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

async function api(method, path, body) {
  const opt = { method, headers: {} };
  if (body !== undefined) {
    opt.headers['Content-Type'] = 'application/json';
    opt.body = JSON.stringify(body);
  }
  const r = await fetch(path, opt);
  const text = await r.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!r.ok) {
    let detail = data && data.detail !== undefined ? data.detail : `${r.status} ${r.statusText}`;
    if (Array.isArray(detail)) detail = detail.map(d => d.msg || JSON.stringify(d)).join('; ');
    const err = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    err.status = r.status;
    throw err;
  }
  return data;
}

function relTime(ts) {
  if (!ts) return '';
  const s = Date.now() / 1000 - ts;
  if (s < 45) return 'now';
  if (s < 3600) return `${Math.round(s / 60)}m`;
  if (s < 86400) return `${Math.round(s / 3600)}h`;
  if (s < 7 * 86400) return `${Math.round(s / 86400)}d`;
  return new Date(ts * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}
const clock = ts => ts ? new Date(ts * 1000).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) : '';
const fullTime = ts => ts ? new Date(ts * 1000).toLocaleString() : '';
const fmtDur = s => s == null ? '' : s < 1 ? `${Math.round(s * 1000)}ms` : s < 60 ? `${s.toFixed(1)}s` : `${Math.floor(s / 60)}m${Math.round(s % 60)}s`;
const fmtNum = n => n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : String(n || 0);
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
const cap = s => (s ? s[0].toUpperCase() + s.slice(1) : s);
const ago = ts => { const r = relTime(ts); return /^\d+[mhd]$/.test(r) ? `${r} ago` : r; };

function initials(title, name) {
  const t = String(title || name || '?').trim();
  if (/^[㐀-鿿豈-﫿]/.test(t)) return t.slice(0, 1);
  const words = t.split(/[\s_\-.]+/).filter(Boolean);
  const s = words.length > 1 ? words[0][0] + words[1][0] : t.slice(0, 2);
  return s.toUpperCase();
}

function debounce(fn, ms) {
  let t = null;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
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

const ICON = {
  panel: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M15 4v16"/></svg>',
  close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/></svg>',
  edit: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h4L19 9l-4-4L4 16v4z"/><path d="M13.5 6.5l4 4"/></svg>',
  tool: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4 2.6-2.6z"/></svg>',
  menu: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h16"/></svg>',
  chat: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M5 18l-2 3V6a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5z"/></svg>',
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
    let s = String(text);
    s = s.replace(/(`+)(?!`)([\s\S]*?[^`])\1(?!`)/g, (_, t, code) => keep(`<code>${esc(code.replace(/^ (.*) $/, '$1'))}</code>`));
    s = s.replace(/!?\[([^\]\n]*)\]\(\s*<?([^)\s>]+)>?(?:\s+"[^"]*")?\s*\)/g, (m, label, url) => {
      const href = safeUrl(url);
      return href ? keep(`<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${emph(esc(label)) || esc(href)}</a>`) : m;
    });
    s = s.replace(/\bhttps?:\/\/[^\s<>"'`\u0000]+[^\s<>"'`.,;:!?)\]\u0000]/g,
      u => keep(`<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(u)}</a>`));
    s = emph(esc(s));
    for (let pass = 0; pass < 3 && s.includes('\u0000'); pass++) s = s.replace(/\u0000(\d+)\u0000/g, (_, i) => slots[+i]);
    return s;
  }

  const isTableStart = (lines, i) => lines[i].includes('|') && i + 1 < lines.length && lines[i + 1].includes('-') && RE_TSEP.test(lines[i + 1]);
  const isBlockStart = (lines, i) => {
    const l = lines[i];
    return RE_FENCE.test(l) || RE_HEAD.test(l) || RE_HR.test(l) || RE_QUOTE.test(l) || RE_LIST.test(l) || isTableStart(lines, i);
  };

  function codeBlock(code, lang) {
    return `<div class="code"><div class="code-head"><span>${esc(lang || 'text')}</span>` +
      `<button type="button" class="code-copy">Copy</button></div><pre><code>${esc(code)}</code></pre></div>`;
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
    const cell = (tag, c, k) => `<${tag}${aligns[k] ? ` style="text-align:${aligns[k]}"` : ''}>${inline(c)}</${tag}>`;
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
      let t = it.text.map(inline).join('<br>');
      t = t.replace(/^\[( |x|X)\]\s+/, (_, x) => `<input type="checkbox" disabled${x.trim() ? ' checked' : ''}> `);
      const sub = it.sub.some(l => l.trim()) ? block(dedent(it.sub)) : '';
      return `<li>${t}${sub}</li>`;
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

  return src => block(String(src ?? '').replace(/\r\n?/g, '\n'));
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
  panelOpen: !isNarrow() && prefs.get('panelOpen', true),
  ws: null,
  wsOk: false,
  wsRetry: 0,
  wsWasDown: false,
};
let C = null;          // the open conversation (see openView)
const P = { tab: { room: 'board', agent: 'memory' }, token: null };

const runKey = (profile, sid) => `${profile}\u0000${sid}`;
const profileOf = name => S.profiles.find(p => p.name === name) || { name, title: name, avatar: '#9ca3af', missing: true };
const bots = () => S.profiles.filter(p => p.bot);

function avatar(p, size = 32, ring = false) {
  return h('span', {
    class: 'avatar' + (ring ? ' ring' : ''),
    title: `${p.title || p.name} (@${p.name})`,
    style: { background: p.avatar || '#9ca3af', width: `${size}px`, height: `${size}px`, fontSize: `${Math.round(size * 0.4)}px` },
  }, initials(p.title, p.name));
}
const userAvatar = (size = 32) => h('span', { class: 'avatar avatar-user', style: { width: `${size}px`, height: `${size}px`, fontSize: `${Math.round(size * 0.4)}px` } }, 'You');

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
  setTimeout(() => el.remove(), action ? 9000 : 4500);
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
}
async function loadActivity() {
  const a = await api('GET', '/api/activity');
  S.runs = new Map(a.runs.map(r => [runKey(r.profile, r.session_id), r]));
  S.drives = new Map(a.drives.map(d => [d.room_id, d]));
}
async function loadUsage() {
  try { S.usage = await api('GET', '/api/usage'); } catch { return; }
  const u = S.usage;
  $('#usage').textContent = `${u.calls} calls · ${fmtNum(u.prompt_tokens + u.completion_tokens)} tok · $${u.cost_usd.toFixed(3)}`;
  $('#usage').title = `Model usage (ledger): ${u.calls} calls, ${u.prompt_tokens} prompt tokens (${Math.round(u.cache_hit_rate * 100)}% cache hits), ${u.completion_tokens} completion tokens, ≈ $${u.cost_usd}`;
}
const refreshLists = debounce(() => { loadProfiles().catch(() => {}); loadRooms().catch(() => {}); loadChats().catch(() => {}); }, 250);
const refreshHitl = debounce(() => loadHitl().catch(() => {}), 80);
const refreshUsage = debounce(loadUsage, 800);

// ====================================================================== sidebar
function renderBrand() {
  const st = S.status;
  const sub = $('#brand-sub');
  if (!st) sub.textContent = 'offline';
  else {
    sub.replaceChildren(`${st.provider} · ${st.model || '?'}`);
    if (!st.api_key_set) sub.append(' · ', h('span', { class: 'warn' }, 'no API key'));
  }
  const n = S.hitl.length;
  const badge = $('#hitl-badge');
  badge.classList.toggle('hidden', !n);
  badge.textContent = `${n} waiting`;
  document.title = n ? `(${n}) PlanD` : 'PlanD';
}

const renderSidebar = rafOnce(() => {
  $$('.side-tabs .tab').forEach(t => t.classList.toggle('active', t.dataset.tab === S.tab));
  $('#side-chats').classList.toggle('hidden', S.tab !== 'chats');
  $('#side-bots').classList.toggle('hidden', S.tab !== 'bots');
  const v = C && C.view;

  // chats
  const chatList = $('#chat-list');
  chatList.replaceChildren(...S.chats.map(s => {
    const active = v && v.type === 'chat' && v.sid === s.id;
    const busy = sessionBusy('default', s.id);
    const waiting = hitlFor({ type: 'chat', profile: 'default', sid: s.id }).length;
    return h('div', { class: 'row' + (active ? ' active' : ''), onclick: () => go(`#/chat/${enc(s.id)}`) },
      h('div', { class: 'row-main' },
        h('div', { class: 'row-title' }, h('span', { class: 't' }, s.title || 'New chat')),
        h('div', { class: 'row-sub' }, s.preview ? s.preview.text : 'No messages yet')),
      h('div', { class: 'row-meta' }, h('span', { class: 'row-time' }, relTime(s.updated)),
        waiting ? h('span', { class: 'dot need', title: 'Waiting for you' }) : busy ? h('span', { class: 'dot busy', title: 'Working' })
          : s.interrupted ? h('span', { class: 'pill pill-amber', title: 'Interrupted — open it to resume' }, 'interrupted') : null),
      iconBtn('trash', 'Delete chat', e => { e.stopPropagation(); deleteChat(s); }, 'row-del'));
  }));
  if (!S.chats.length) chatList.append(h('div', { class: 'list-empty' }, 'No chats yet. Say hello to get started.'));

  // bots
  const botList = $('#bot-list');
  const roster = bots();
  botList.replaceChildren(...roster.map(p => {
    const active = v && v.type === 'bot' && v.profile === p.name;
    const waiting = S.hitl.filter(r => r.profile === p.name).length;
    const busy = profileBusy(p.name);
    const preview = p.preview ? (p.preview.role === 'user' ? `You: ${p.preview.text}` : p.preview.text) : (p.description || 'No messages yet');
    return h('div', { class: 'row' + (active ? ' active' : ''), onclick: () => go(`#/bot/${enc(p.name)}`) },
      avatar(p, 34, busy),
      h('div', { class: 'row-main' },
        h('div', { class: 'row-title' }, h('span', { class: 't' }, p.title), h('span', { class: 'handle' }, `@${p.name}`)),
        h('div', { class: 'row-sub' }, busy ? workingText(p.name) : preview)),
      h('div', { class: 'row-meta' }, h('span', { class: 'row-time' }, p.preview ? relTime(p.preview.created) : ''),
        waiting ? h('span', { class: 'pill pill-warn' }, waiting)
          : !busy && p.bot_chat_status === 'interrupted' ? h('span', { class: 'pill pill-amber', title: 'Bot Chat was interrupted — open it to resume' }, 'interrupted') : null));
  }));
  if (!roster.length) botList.append(h('div', { class: 'list-empty' }, 'No bots yet. A bot is an agent with its own identity, memory and workspace.'));

  // groups
  const groupList = $('#group-list');
  groupList.replaceChildren(...S.rooms.map(r => {
    const active = v && v.type === 'room' && v.roomId === r.id;
    const waiting = S.hitl.filter(x => x.room_id === r.id).length;
    const needs = r.needs_you || waiting > 0;
    const driving = S.drives.has(r.id);
    const members = (r.member_info || []).slice(0, 3);
    const preview = r.preview ? `${r.preview.speaker === 'user' ? 'You' : '@' + r.preview.speaker}: ${r.preview.text}` : `${r.members.length} member${r.members.length === 1 ? '' : 's'}`;
    return h('div', { class: 'row' + (active ? ' active' : ''), onclick: () => go(`#/room/${enc(r.id)}`) },
      h('span', { class: 'stack' }, members.map(m => avatar(m, 24))),
      h('div', { class: 'row-main' },
        h('div', { class: 'row-title' }, h('span', { class: 't' }, r.name), h('span', { class: 'handle' }, `${r.members.length}`)),
        h('div', { class: 'row-sub' }, driving ? 'Team is working…' : preview)),
      h('div', { class: 'row-meta' }, h('span', { class: 'row-time' }, relTime(r.updated)),
        needs ? h('span', { class: 'pill pill-warn', title: 'Needs you' }, 'needs you') : driving ? h('span', { class: 'dot busy' }) : null));
  }));
  if (!S.rooms.length) groupList.append(h('div', { class: 'list-empty' }, 'No groups yet. Put bots in a room and give the team a goal.'));
});

function workingText(name) {
  const r = runsFor(x => x.profile === name)[0];
  if (!r) return '';
  if (r.state === 'waiting') return 'Waiting for you…';
  if (r.state === 'writing') return 'Writing…';
  if (r.state === 'tool') return `Running ${r.tool}…`;
  return 'Thinking…';
}

async function deleteChat(s) {
  if (!confirm(`Delete "${s.title || 'New chat'}"? This removes its transcript.`)) return;
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
    case 'bot': return parts[1] ? { type: 'bot', profile: parts[1], sid: null } : null;
    case 'session': return parts[2] ? { type: 'session', profile: parts[1], sid: parts[2] } : null;
    case 'room': return parts[1] ? { type: 'room', roomId: parts[1] } : null;
    default: return null;
  }
}

function go(hash) {
  document.body.classList.remove('sidebar-open');
  if (location.hash === hash) route(); else location.hash = hash;
}

async function route() {
  const v = parseHash() || { type: 'chat', profile: 'default', sid: null };
  if (v.type === 'bot') {
    try {
      v.sid = (await api('GET', `/api/profiles/${enc(v.profile)}/bot-chat`)).session_id;
    } catch (e) {
      toast(e.status === 404 ? `There is no bot @${v.profile}` : e.message, 'error');
      return go('#/chat');
    }
  }
  S.tab = v.type === 'chat' || (v.type === 'session' && v.profile === 'default') ? 'chats' : 'bots';
  openView(v);
}

// ====================================================================== conversation
function openView(view) {
  if (isNarrow()) S.panelOpen = false;  // the panel is an overlay on narrow screens: start each view without it
  C = { view, lastId: 0, lastEventId: 0, callEls: new Map(), group: null, lastSpeaker: null, busy: false, interrupted: false,
    session: null, room: null, fetching: false, again: false, optimistic: null, seen: new Set(), empty: null,
    todos: [], planOpen: null, hint: null, streams: new Map() };
  $('#messages').replaceChildren();
  $('#hitl-cards').replaceChildren();
  closeMentions();
  renderHead();
  renderSidebar();
  renderPanel();
  renderBanner();
  updateComposer();
  renderLive();
  renderPlan();
  if (view.type === 'room') loadRoom(true);
  else if (view.sid) loadConv(true);
  else showEmpty();
  if (window.innerWidth > 760) $('#input').focus();
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
      if (room && room.lead === m.name) sub.append(h('span', { class: 'lead', title: 'Lead' }, ' ★'));
    });
    titles = h('div', { class: 'titles' }, h('div', { class: 'conv-title' }, room ? room.name : 'Group'), sub);
  } else {
    const p = viewProfile();
    lead = avatar(p, 34, sessionBusy(v.profile, v.sid));
    let title = p.title;
    let sub = `@${p.name}${p.model ? ' · ' + p.model : ''}`;
    if (v.type === 'chat') {
      title = (C.session && C.session.title) || 'New chat';
      sub = `${p.title} · single agent${p.model ? ' · ' + p.model : ''}`;
    } else if (v.type === 'bot') {
      sub = `@${p.name} · Bot Chat${p.description ? ' · ' + p.description : ''}`;
    } else if (C.session) {
      title = C.session.title || C.session.kind;
      sub = `@${p.name} · ${kindLabel(C.session.kind)}`;
    }
    const backend = p.missing ? null : h('span', { class: 'pill pill-backend', title: `Execution backend: ${BACKEND_HELP[p.backend_effective] || backendLabel(p)}` }, backendLabel(p));
    titles = h('div', { class: 'titles' }, h('div', { class: 'conv-title' }, h('span', { class: 'conv-title-t' }, title), backend), h('div', { class: 'conv-sub' }, sub));
    if (v.type === 'chat' && v.sid) {
      actions.append(iconBtn('edit', 'Rename chat', renameChat), iconBtn('trash', 'Delete chat', () => deleteChat({ id: v.sid, title: C.session && C.session.title })));
    }
    if (v.type === 'session' && p.bot) actions.append(h('button', { type: 'button', class: 'btn btn-ghost btn-sm', onclick: () => go(`#/bot/${enc(p.name)}`) }, 'Open Bot Chat'));
  }
  actions.append(iconBtn('panel', S.panelOpen ? 'Hide details' : 'Show details', togglePanel, S.panelOpen ? 'active' : ''));
  head.replaceChildren(iconBtn('menu', 'Conversations', () => document.body.classList.toggle('sidebar-open'), 'menu-btn'), lead, titles, actions);
}

const kindLabel = k => ({ chat: 'chat', bot_chat: 'Bot Chat', room_member: 'group work log', delegation: 'delegated task', subagent: 'subagent', eval: 'evaluation' }[k] || k);

async function renameChat() {
  const cur = (C.session && C.session.title) || '';
  const title = prompt('Rename chat', cur);
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
    b.replaceChildren(h('span', null, `No API key found for ${st.provider}. Add it to .env (e.g. DEEPSEEK_API_KEY=…) and restart the server.`));
    b.classList.remove('hidden');
    return;
  }
  if (C && C.view.type !== 'room' && C.interrupted && !C.busy && !sessionBusy(C.view.profile, C.view.sid) &&
      !(C.session && C.session.kind === 'room_member')) {
    b.replaceChildren(h('span', null, 'This conversation was interrupted (the server stopped while it was working). Resume continues from where it stopped — unfinished tool calls run first, and questions are asked again.'),
      h('button', { type: 'button', class: 'btn btn-sm', onclick: resumeRun }, 'Resume'));
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

function showEmpty() {
  const box = $('#messages');
  if (C.empty || box.children.length) return;
  const v = C.view;
  let el;
  if (v.type === 'room') {
    const room = C.room || S.rooms.find(r => r.id === v.roomId) || { member_info: [] };
    const lead = room.lead ? `@${room.lead}` : 'the first bot you address';
    el = h('div', { class: 'empty' },
      h('span', { class: 'stack' }, (room.member_info || []).map(m => avatar(m, 40))),
      h('h1', null, room.name || 'Group'),
      h('p', null, `Give the team a goal. Mention @name to address one bot, or write to everyone; ${lead} leads, breaks the work down on the board and delegates to teammates.`));
  } else {
    const p = viewProfile();
    if (v.type === 'chat') {
      el = h('div', { class: 'empty' }, avatar(p, 48), h('h1', null, 'What can I do for you?'),
        h('p', null, 'One agent with files, code execution, web search and git. It asks you when something is ambiguous and before anything risky.'),
        h('div', { class: 'chips' }, [
          'Write a Python script that prints the first 10 primes and run it',
          'Search the web for the latest Python release and summarise it in notes.md',
          'What do you remember about me?',
        ].map(t => h('button', { type: 'button', class: 'chip', onclick: () => { $('#input').value = t; autosize(); $('#input').focus(); } }, t))));
    } else {
      el = h('div', { class: 'empty' }, avatar(p, 48), h('h1', null, p.title),
        h('p', null, v.type === 'bot' ? `Your private Bot Chat with @${p.name}. ${p.description || ''}` : 'This session has no messages.'));
    }
  }
  C.empty = el;
  box.append(el);
}

function clearEmpty() {
  if (C && C.empty) { C.empty.remove(); C.empty = null; }
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
  try {
    const d = await api('GET', `/api/profiles/${enc(c.view.profile)}/sessions/${enc(c.view.sid)}/messages?after=${c.lastId}&events_after=${c.lastEventId}`);
    if (c !== C) return;
    c.session = d.session;
    c.busy = d.busy;
    c.interrupted = d.interrupted;
    c.todos = d.todos || [];
    for (const it of mergeByTime(d.items, d.activity)) appendConvItem(it);
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
    if (stick) scrollBottom();
  } catch (e) {
    if (c !== C) return;
    if (e.status === 404) { toast('That conversation no longer exists.'); go('#/chat'); } else toast(e.message, 'error');
  } finally {
    c.fetching = false;
    if (c.again && c === C) { c.again = false; loadConv(); }
  }
}
const refreshConv = debounce(() => loadConv(), 60);

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
  const box = $('#messages');
  if (it.role === 'event') {
    const info = activityInfo(it);
    // Inside the open assistant turn (next to the tool card it belongs to), else as its own row.
    if (info) (C.group ? C.group.body : box).append(activityRow(info, it.created));
    return;
  }
  if (it.role === 'user') {
    if (C.optimistic) { C.optimistic.remove(); C.optimistic = null; }
    C.group = null;
    if (it.kind === 'note') box.append(h('div', { class: 'note', title: fullTime(it.created) }, it.content.replace(/^\[system\]\s*/, '')));
    else if (it.kind === 'room_turn') {
      box.append(h('details', { class: 'turn' }, h('summary', null, `Group update for this turn${it.turn_role ? ` (as ${it.turn_role})` : ''} · ${clock(it.created)}`), h('pre', null, it.content)));
    } else if (it.kind === 'agent_message') {
      const p = profileOf(it.from_agent);
      box.append(h('div', { class: 'msg', title: fullTime(it.created) }, avatar(p, 30),
        h('div', { class: 'msg-main msg-from' }, h('div', { class: 'label' }, `Message from @${p.name}`),
          h('div', { class: 'md', html: md(it.content.replace(/^Message from[^\n]*\n/, '')) }))));
    } else {
      box.append(h('div', { class: 'msg msg-user', title: fullTime(it.created) }, h('div', { class: 'bubble' }, it.content)));
    }
    if (it.recalled && it.recalled.length) {
      box.append(activityRow({ icon: '↺', text: `recalled ${plural(it.recalled.length, 'past experience')} for this task`, more: it.recalled }, it.created));
    }
    return;
  }
  if (it.role === 'assistant') {
    const g = assistantGroup(it.created);
    if (it.reasoning) g.body.append(h('details', { class: 'reasoning' }, h('summary', null, 'Thinking'), h('div', null, it.reasoning)));
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
  $('#messages').append(el);
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
  if (name === 'delegate_task' && Array.isArray(a.tasks)) return a.tasks.map(t => (t.to ? `@${String(t.to).replace(/^@/, '')}` : 'subagent') + ': ' + (t.goal || '')).join(' · ');
  if (name === 'todo') return Array.isArray(a.todos) ? `${a.merge ? 'update' : 'write'} ${plural(a.todos.length, 'item')}` : 'read the plan';
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
  const result = h('pre', null);
  const det = h('details', { class: 'tool' },
    h('summary', null,
      h('span', { class: 'tool-icon', html: ICON.tool }),
      h('span', { class: 'tool-name' }, call.name),
      h('span', { class: 'tool-arg' }, argSummary(call.name, call.args)),
      state),
    h('div', { class: 'tool-body' },
      call.args ? [h('div', { class: 'tool-label' }, 'Arguments'), h('pre', null, prettyArgs(call.args))] : null,
      h('div', { class: 'tool-label' }, 'Result'), result));
  const el = { det, state, result };
  if (call.id) C.callEls.set(call.id, el);
  updateToolCard(el, call);
  return det;
}

function updateToolCard(el, r) {
  if (r.result == null) {
    el.det.classList.add('running');
    el.state.replaceChildren(h('span', { class: 'spinner' }), 'running');
    el.result.textContent = 'Waiting for the result…';
    return;
  }
  el.det.classList.remove('running', 'stale');
  el.det.classList.toggle('ok', !!r.ok);
  el.det.classList.toggle('err', !r.ok);
  el.state.textContent = `${r.ok ? '✓' : '✗ error'}${r.duration != null ? ' · ' + fmtDur(r.duration) : ''}`;
  el.result.textContent = r.result || '(empty)';
}

function markStaleTools() {
  for (const el of C.callEls.values()) {
    if (el.det.classList.contains('running')) {
      el.det.classList.replace('running', 'stale');
      el.state.textContent = 'no result';
      el.result.textContent = 'This call did not finish (the run was stopped or interrupted).';
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
  try {
    const d = await api('GET', `/api/rooms/${enc(c.view.roomId)}/messages?after=${c.lastId}`);
    if (c !== C) return;
    c.room = d.room;
    for (const m of d.messages) appendRoomMsg(m);
    const posted = new Set(d.messages.filter(m => m.kind === 'message').map(m => m.speaker));
    settleStreams(st => posted.has(st.profile));
    c.lastId = d.last_id;
    if (!$('#messages').children.length) showEmpty();
    if (initial) { renderHead(); renderPanel(); }
    updateComposer();
    renderLive();
    renderPlan();
    renderHitlCards();
    if (stick) scrollBottom();
  } catch (e) {
    if (c !== C) return;
    if (e.status === 404) { toast('That group no longer exists.'); go('#/chat'); } else toast(e.message, 'error');
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
  const box = $('#messages');
  if (m.kind === 'system') {
    box.append(h('div', { class: 'note', title: fullTime(m.created) }, m.content));
    C.lastSpeaker = null;
    return;
  }
  if (m.kind === 'activity') {
    const p = profileOf(m.speaker);
    const [first, ...rest] = m.content.split('\n');
    const cls = first.startsWith('✓') ? 'ok' : first.startsWith('✗') || first.startsWith('⚠') ? 'err' : first.startsWith('→') ? 'start' : '';
    const line = h('div', { class: 'a-line' }, h('span', { class: 'who' }, `@${m.speaker} `), first);
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
        isLead ? h('span', { class: 'star', title: 'Lead' }, '★') : null, h('span', { class: 'time' }, clock(m.created))),
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
  const who = `@${r.profile}`;
  if (r.state === 'waiting') return `${who} is waiting for you`;
  if (r.state === 'writing') return `${who} is writing…`;
  if (r.state === 'tool') {
    if (r.tool === 'delegate_task') return `${who} is waiting on teammates`;
    if (r.tool === 'message_agent') return `${who} is messaging a teammate`;
    return `${who} is running ${r.tool}…`;
  }
  return `${who} is thinking…`;
}

const renderLive = rafOnce(() => {
  const el = $('#live');
  if (!C) return el.classList.add('hidden');
  const runs = relevantRuns().sort((a, b) => (a.depth || 0) - (b.depth || 0));
  let texts = runs.map(runText);
  if (C.view.type === 'room' && S.drives.has(C.view.roomId) && !texts.length) texts = ['The team is working…'];
  if (C.view.type !== 'room' && !texts.length && C.busy) texts = ['Working…'];
  const hint = C.hint && C.hint.until > Date.now() ? C.hint : null;
  if (!texts.length && !hint) return el.classList.add('hidden');
  el.replaceChildren(texts.length ? h('span', { class: 'spinner' }) : h('span', { class: 'live-icon', 'aria-hidden': 'true' }, hint.icon),
    h('span', { class: 'txt' }, texts.join(' · '),
      hint ? h('span', { class: 'live-hint' + (hint.cls ? ' ' + hint.cls : '') }, (texts.length ? ' · ' : '') + hint.text) : null));
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
      cont ? null : h('div', { class: 'msg-name' }, p.title, h('span', { class: 'handle' }, `@${p.name}`), h('span', { class: 'time' }, 'writing…')),
      body));
  box.append(el);
  return { profile: ev.profile, iteration: ev.iteration, el, body, content, text: '', reasoning: null, room, done: false };
}

function streamVisible(st) {
  const t = st.text.trim().toLowerCase().replace(/[ .]+$/, '');
  if (!t) return !!st.reasoning;
  // a room member that has nothing to add answers [PASS]; that is never posted, so never shown
  return !(st.room && (t.startsWith('[pass]') || PASS_TOKENS.some(p => p.startsWith(t))));
}

function onDelta(ev) {
  if (!ev.text || !streamTarget(ev)) return;
  const key = runKey(ev.profile, ev.session_id);
  let st = C.streams.get(key);
  if (st && (st.iteration !== ev.iteration || st.done)) { st.el.remove(); st = null; }
  if (!st) { st = createStream(ev); C.streams.set(key, st); }
  const stick = nearBottom();
  if (ev.kind === 'reasoning') {
    if (st.room) return;  // members' private reasoning stays out of the group view
    if (!st.reasoning) {
      st.reasoning = document.createTextNode('');
      st.body.prepend(h('details', { class: 'reasoning' }, h('summary', null, 'Thinking…'), h('div', null, st.reasoning)));
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
const ROW_EVENTS = new Set(['memory.session_search', 'context.pruned', 'context.compacted', 'loop.detected', 'experience.added', 'approval.auto']);
const HINT_EVENTS = new Set([...ROW_EVENTS, 'experience.retrieved', 'budget.checkpoint']);

function activityInfo(ev) {
  switch (ev.type) {
    case 'memory.session_search':
      return { icon: '⌕', text: `searched past conversations for “${ev.query || ''}” — ${plural(ev.hits || 0, 'hit')}` };
    case 'context.pruned':
      return { icon: '✂', text: 'cleared old tool output to keep the context small' };
    case 'context.compacted':
      return { icon: '✂', text: `compacted the context — ${plural(ev.folded || 0, 'earlier message')} summarised` };
    case 'loop.detected':
      return { icon: '⚠', text: `loop guard stopped the run: ${ev.reason || 'no progress'}`, cls: 'warn' };
    case 'experience.added':
      return { icon: '✎', text: `recorded an experience (${ev.outcome || 'partial'})`, more: ev.lessons || [] };
    case 'approval.auto':
      return { icon: '✓', text: `auto-approved ${ev.summary || ev.category} — ${ev.grant === 'always' ? 'always allowed' : 'allowed for this session'}`,
        title: `Permission scope: ${ev.category}` };
    case 'experience.retrieved':
      return { icon: '↺', text: `recalled ${plural((ev.ids || []).length, 'past experience')}` };
    case 'budget.checkpoint':
      return { icon: '⏱', text: `${plural(ev.steps_left || 0, 'step')} left in the step budget` };
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
  const counted = todos.filter(t => t.status !== 'cancelled');
  const done = counted.filter(t => t.status === 'completed').length;
  return { done, total: counted.length, cancelled: todos.length - counted.length, cur: todos.find(t => t.status === 'in_progress') };
}
const planTitle = st => `${st.done} of ${st.total} done${st.cancelled ? ` · ${st.cancelled} cancelled` : ''}`;

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
    kids.push(h('button', { type: 'button', class: 'plan-head', 'aria-expanded': String(open), title: open ? 'Hide the plan' : 'Show the plan',
      onclick: () => { C.planOpen = !open; renderPlan(); } },
      h('span', { class: 'plan-chev', 'aria-hidden': 'true' }),
      h('span', { class: 'plan-label' }, 'Plan'),
      h('span', { class: 'plan-count', title: planTitle(st) }, `${st.done}/${st.total}`),
      h('span', { class: 'bar plan-bar' + (complete ? ' ok' : '') }, h('span', { style: { width: `${pct}%` } })),
      h('span', { class: 'plan-cur' }, open ? '' : st.cur ? `▸ ${st.cur.content}` : complete ? 'All done' : '')));
    if (open) {
      kids.push(h('ol', { class: 'plan-list' }, own.map(t => h('li', { class: `plan-item s-${t.status}`, title: t.status.replace('_', ' ') },
        h('span', { class: 'plan-mark', 'aria-hidden': 'true' }, PLAN_MARK[t.status] || '○'),
        h('span', { class: 'plan-text' }, t.content)))));
    }
  }
  for (const r of others) {
    const st = planStats(r.todos);
    const open = () => go(`#/session/${enc(r.profile)}/${enc(r.session_id)}`);
    kids.push(h('div', { class: 'plan-sub', role: 'button', tabindex: '0', title: `@${r.profile}'s plan — ${planTitle(st)}. Open its work log.`,
      onclick: open, onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } } },
      avatar(profileOf(r.profile), 18),
      h('span', { class: 'plan-who' }, `@${r.profile}`),
      h('span', { class: 'plan-count' }, `${st.done}/${st.total}`),
      h('span', { class: 'plan-cur' }, st.cur ? `▸ ${st.cur.content}` : st.done === st.total ? 'all done' : '')));
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
  let placeholder = 'Message PlanD…';
  let readOnly = false;
  let running = false;
  if (v.type === 'room') {
    const room = C.room || S.rooms.find(r => r.id === v.roomId);
    placeholder = room ? `Message ${room.name} — @mention a bot to address it` : 'Message the group…';
    running = S.drives.has(v.roomId) || relevantRuns().length > 0;
  } else {
    const p = viewProfile();
    if (v.type === 'bot') placeholder = `Message ${p.title}…`;
    if (v.type === 'session' && C.session && !['chat', 'bot_chat'].includes(C.session.kind)) {
      readOnly = true;
      placeholder = `This ${kindLabel(C.session.kind)} is a read-only work log.`;
    }
    running = C.busy || runsFor(r => r.profile === v.profile && r.session_id === v.sid).length > 0;
  }
  input.placeholder = placeholder;
  input.disabled = readOnly;
  send.disabled = readOnly || (v.type !== 'room' && running);
  stop.classList.toggle('hidden', !running);
}

function autosize() {
  const el = $('#input');
  el.style.height = 'auto';
  el.style.height = `${Math.min(el.scrollHeight, 240)}px`;
}

async function send() {
  const input = $('#input');
  const text = input.value.trim();
  if (!text || !C) return;
  const v = C.view;
  if (v.type === 'room') {
    input.value = '';
    autosize();
    try {
      const r = await api('POST', `/api/rooms/${enc(v.roomId)}/messages`, { text });
      if (r.queued) toast('The team is still busy; your message is queued for the next turn.');
      refreshRoom();
    } catch (e) {
      toast(e.message, 'error');
      input.value = text;
      autosize();
    }
    return;
  }
  if ($('#send').disabled) return;
  const c = C;
  try {
    if (!v.sid) {
      const s = await api('POST', `/api/profiles/${enc(v.profile)}/sessions`, {});
      v.sid = s.id;
      c.session = s;
      history.replaceState(null, '', `#/chat/${enc(s.id)}`);
    }
    input.value = '';
    autosize();
    clearEmpty();
    c.optimistic = h('div', { class: 'msg msg-user' }, h('div', { class: 'bubble pending' }, text));
    c.group = null;
    $('#messages').append(c.optimistic);
    scrollBottom();
    c.busy = true;
    updateComposer();
    renderLive();
    await api('POST', `/api/profiles/${enc(v.profile)}/sessions/${enc(v.sid)}/messages`, { text });
    if (v.type === 'chat') loadChats().catch(() => {});
  } catch (e) {
    if (c.optimistic) { c.optimistic.remove(); c.optimistic = null; }
    c.busy = false;
    updateComposer();
    renderLive();
    input.value = text;
    autosize();
    toast(e.message, 'error');
  }
}

async function stopRun() {
  if (!C) return;
  const v = C.view;
  try {
    if (v.type === 'room') await api('POST', `/api/rooms/${enc(v.roomId)}/stop`);
    else if (v.sid) await api('POST', `/api/profiles/${enc(v.profile)}/sessions/${enc(v.sid)}/stop`);
    toast('Stopping…');
  } catch (e) { toast(e.message, 'error'); }
}

// --- @mention autocomplete (rooms)
const M = { open: false, items: [], sel: 0, start: 0 };

function mentionCandidates() {
  if (!C || C.view.type !== 'room') return [];
  const room = C.room || S.rooms.find(r => r.id === C.view.roomId);
  if (!room) return [];
  return [...(room.member_info || []), { name: 'all', title: 'Everyone in the group', avatar: '#9ca3af' }];
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
    class: 'mention-item' + (i === M.sel ? ' sel' : ''), role: 'option',
    onmousedown: e => { e.preventDefault(); pickMention(i); },
  }, avatar(c, 22), h('strong', null, `@${c.name}`), h('span', { class: 'handle' }, c.title))));
  pop.classList.remove('hidden');
}

function closeMentions() {
  M.open = false;
  M.sel = 0;
  $('#mention-pop').classList.add('hidden');
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
      h('span', { class: 'hitl-kind' }, approval ? 'needs your permission' : 'has a question'),
      h('span', { class: `pill hitl-kind-tag ${approval ? 'pill-amber' : 'pill-accent'}` }, approval ? 'Approval' : 'Clarification')));
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
    if (q.category) card.append(h('div', { class: 'hitl-cat' }, `Permission scope: ${q.category}`));
    card.append(h('div', { class: 'hitl-actions' },
      h('button', { type: 'button', class: 'btn btn-primary', title: 'Allow this one operation', onclick: () => submit({ choice: 'once' }) }, 'Allow once'),
      h('button', { type: 'button', class: 'btn', title: 'Allow this kind of operation for the rest of this session', onclick: () => submit({ choice: 'session' }) }, 'Session'),
      h('button', { type: 'button', class: 'btn', title: `Always allow "${q.category || 'this'}" for @${p.name}`, onclick: () => submit({ choice: 'always' }) }, 'Always'),
      h('button', { type: 'button', class: 'btn btn-danger', onclick: () => submit({ choice: 'deny' }) }, 'Deny')));
  } else {
    card.append(h('div', { class: 'hitl-q md', html: md(q.question || '') }));
    if (q.detail) card.append(h('div', { class: 'hitl-detail-text' }, q.detail));
    if (q.options && q.options.length) {
      card.append(h('div', { class: 'hitl-options' }, q.options.map(o => h('button', { type: 'button', class: 'btn btn-option', onclick: () => submit({ text: o }) }, o))));
    }
    const ta = h('textarea', { rows: 1, placeholder: q.options && q.options.length ? 'Or type another answer…' : 'Type your answer…' });
    const go = () => { const t = ta.value.trim(); if (t) submit({ text: t }); };
    ta.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && e.keyCode !== 229) { e.preventDefault(); go(); }
    });
    ta.addEventListener('input', () => { ta.style.height = 'auto'; ta.style.height = `${Math.min(ta.scrollHeight, 140)}px`; });
    card.append(h('div', { class: 'hitl-answer' }, ta, h('button', { type: 'button', class: 'btn btn-primary', onclick: go }, 'Answer')));
  }
  if (!r.live) card.append(h('div', { class: 'hitl-warn' }, 'The run that asked this is no longer waiting; answering only records it.'));
  if (inTray) {
    card.append(h('a', { class: 'hitl-open', href: hitlTarget(r), onclick: () => $('#tray').classList.add('hidden') }, 'Open conversation →'));
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
    if (ta && document.activeElement !== $('#input')) ta.focus({ preventScroll: true });
  }
}

function renderTray() {
  const tray = $('#tray');
  if (tray.classList.contains('hidden')) return;
  if (!S.hitl.length) { tray.classList.add('hidden'); return; }
  tray.replaceChildren(
    h('div', { class: 'tray-head' }, h('span', null, `Waiting for you (${S.hitl.length})`), iconBtn('close', 'Close', () => tray.classList.add('hidden'))),
    ...S.hitl.map(r => hitlCard(r, { inTray: true })));
}

function toggleTray() {
  const tray = $('#tray');
  tray.classList.toggle('hidden');
  renderTray();
}

function notifyHitl(ev) {
  const req = ev.request || {};
  const visible = C && (C.view.type === 'room' ? ev.room_id === C.view.roomId
    : (ev.profile === C.view.profile && ev.session_id === C.view.sid) ||
      (ev.origin && ev.origin.profile === C.view.profile && ev.origin.session_id === C.view.sid));
  if (visible && document.hasFocus()) return;
  const what = req.kind === 'approval' ? 'needs your permission' : 'has a question';
  toast(`@${ev.profile} ${what}`, 'warn', {
    label: 'Open',
    fn: () => go(hitlTarget({ room_id: ev.room_id, origin: ev.origin, profile: ev.profile, session_id: ev.session_id })),
  });
}

// ====================================================================== right panel
function togglePanel() {
  S.panelOpen = !S.panelOpen;
  if (!isNarrow()) prefs.set('panelOpen', S.panelOpen);
  renderHead();
  renderPanel();
}

const panelKind = () => (C && C.view.type === 'room' ? 'room' : 'agent');
const PANEL_TABS = {
  room: [['board', 'Board'], ['members', 'Members'], ['settings', 'Settings']],
  agent: [['memory', 'Memory'], ['tasks', 'Tasks'], ['sessions', 'Sessions'], ['settings', 'Settings']],
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
  if (!keepScroll || !oldBody) body.append(h('div', { class: 'muted pad' }, 'Loading…'));
  const tabs = h('div', { class: 'tabs tabs-sm' }, PANEL_TABS[kind].map(([k, label]) =>
    h('button', { type: 'button', class: 'tab' + (k === cur ? ' active' : ''), onclick: () => { P.tab[kind] = k; renderPanel(); } }, label)));
  const token = (P.token = Symbol('panel'));
  const build = PANEL_BUILDERS[kind][cur];
  let content;
  try { content = await build(); } catch (e) { content = h('div', { class: 'muted pad' }, e.message); }
  if (P.token !== token) return;
  body.replaceChildren(content);
  el.replaceChildren(h('div', { class: 'panel-head' }, tabs, iconBtn('close', 'Hide details', togglePanel)), body);
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
const statusPill = s => h('span', { class: `pill status-${s}` }, s.replace('_', ' '));

async function memoryPanel() {
  const name = C.view.profile;
  const m = await api('GET', `/api/profiles/${enc(name)}/memory`);
  const notes = (target, label) => {
    const n = m.notes[target];
    const pct = n.limit ? Math.min(100, Math.round((n.used / n.limit) * 100)) : 0;
    return section(label,
      h('div', { class: 'usage-line' }, h('div', { class: 'bar' }, h('span', { style: { width: `${pct}%` } })), `${n.used}/${n.limit} chars`),
      n.entries.length ? n.entries.map(e => h('div', { class: 'p-entry' }, e)) : h('div', { class: 'p-empty' }, 'Empty.'));
  };
  const exps = m.experiences.map(e => {
    const cls = e.outcome === 'success' ? 'pill-ok' : e.outcome === 'failure' ? 'pill-err' : 'pill-amber';
    return h('div', { class: 'p-card' },
      h('div', { class: 'exp-head' }, h('span', { class: `pill ${cls}` }, e.outcome), h('span', { class: 'time', title: fullTime(e.created) }, relTime(e.created))),
      h('div', { class: 'exp-task' }, e.task),
      e.summary ? h('div', { class: 'exp-sum' }, e.summary) : null,
      e.lessons && e.lessons.length ? h('details', null, h('summary', null, `${e.lessons.length} lesson${e.lessons.length > 1 ? 's' : ''}${e.procedure ? ' + procedure' : ''}`),
        h('ul', null, e.lessons.map(l => h('li', null, l))), e.procedure ? h('pre', null, e.procedure) : null) : null,
      h('div', { class: 'exp-meta', title: 'Utility = smoothed success rate of tasks that reused this experience; it weights retrieval.' },
        `used ${e.uses}× · ${e.helpful} helpful · ${e.unhelpful} unhelpful`,
        h('div', { class: 'bar ok' }, h('span', { style: { width: `${Math.round(e.utility * 100)}%` } })), e.utility.toFixed(2)));
  });
  const skills = m.skills.map(s => {
    const views = s.views || 0;
    const saves = s.saves || 0;
    const usage = [`viewed ${views}×`, `saved ${saves}×`];
    if (s.last_view) usage.push(`last used ${ago(s.last_view)}`);
    return h('div', { class: 'p-card' },
      h('details', null, h('summary', null, h('strong', null, s.name), s.description ? ` — ${s.description}` : ''), h('pre', null, s.content)),
      h('div', { class: 'skill-meta' + (views ? '' : ' unused'),
        title: [s.last_view ? `Last viewed ${fullTime(s.last_view)}` : 'Never viewed by the agent', s.last_save ? `Last saved ${fullTime(s.last_save)}` : '']
          .filter(Boolean).join('\n') }, usage.join(' · ')));
  });
  const events = m.events.slice(0, 30).map(ev => {
    const d = ev.detail || {};
    const what = d.content || d.task || d.name || (d.ids ? `${d.ids.length} item(s)` : '') || d.after || (d.removed && d.removed.join('; ')) || '';
    return h('div', { class: 'ev-row', title: fullTime(ev.ts) }, h('span', { class: 'time' }, relTime(ev.ts)),
      h('span', { class: 'what' }, h('strong', null, `${ev.store} ${ev.op}`), what ? ` · ${what}` : ''));
  });
  return h('div', null,
    notes('memory', 'Agent notes (MEMORY.md)'),
    notes('user', 'About the user (USER.md)'),
    section([`Experiences (${m.experience_count})`],
      exps.length ? exps : h('div', { class: 'p-empty' }, 'No experiences yet. After each task the agent reflects and records what worked; relevant ones are recalled before similar tasks.')),
    section(`Skills (${m.skills.length})`, skills.length ? skills : h('div', { class: 'p-empty' }, 'No skills saved yet.')),
    section('Recent memory activity', events.length ? h('div', null, events) : h('div', { class: 'p-empty' }, 'Nothing yet.')));
}

function taskList(tasks, emptyText) {
  if (!tasks.length) return h('div', { class: 'p-empty pad' }, emptyText);
  const order = ['in_progress', 'todo', 'blocked', 'failed', 'done'];
  const counts = order.map(s => [s, tasks.filter(t => t.status === s).length]).filter(([, n]) => n);
  const sorted = [...tasks].sort((a, b) => order.indexOf(a.status) - order.indexOf(b.status) || a.created - b.created);
  return h('div', null,
    h('div', { class: 'board-summary' }, counts.map(([s, n]) => h('span', { class: `pill status-${s}` }, `${n} ${s.replace('_', ' ')}`))),
    sorted.map(t => {
      const who = t.assignee ? profileOf(t.assignee) : null;
      return h('div', { class: 'task' },
        h('div', { class: 'task-head' }, h('div', { class: 'task-title' }, t.title), statusPill(t.status)),
        h('div', { class: 'task-meta' },
          who ? [avatar(who, 18), `@${t.assignee}`] : 'unassigned',
          h('span', null, `· by @${t.created_by}`), h('span', { title: fullTime(t.updated) }, `· ${relTime(t.updated)}`)),
        t.description ? h('details', null, h('summary', null, 'Details'), h('div', null, t.description)) : null,
        t.result ? h('details', null, h('summary', null, t.status === 'failed' ? 'Error' : 'Result'), h('div', null, t.result)) : null);
    }));
}

async function agentTasksPanel() {
  const name = C.view.profile;
  const tasks = await api('GET', `/api/board/${enc('dm:' + name)}`);
  return h('div', null, section(`Delegated by @${name}`,
    taskList(tasks, `When @${name} delegates work outside a group, the subtasks and their results are tracked here.`)));
}

async function sessionsPanel() {
  const name = C.view.profile;
  const list = await api('GET', `/api/profiles/${enc(name)}/sessions?limit=200`);
  if (!list.length) return h('div', { class: 'p-empty pad' }, 'No sessions yet.');
  const open = s => {
    if (s.kind === 'bot_chat') return go(`#/bot/${enc(name)}`);
    if (name === 'default' && s.kind === 'chat') return go(`#/chat/${enc(s.id)}`);
    return go(`#/session/${enc(name)}/${enc(s.id)}`);
  };
  return section(`Sessions of @${name}`, list.map(s => h('div', { class: 'sess-row' + (C.view.sid === s.id ? ' active' : ''), onclick: () => open(s), title: fullTime(s.updated) },
    h('span', { class: 'pill' }, kindLabel(s.kind)), h('span', { class: 't' }, s.title || '(untitled)'),
    s.todos && s.todos.length ? (st => h('span', { class: 'plan-mini', title: `Plan: ${planTitle(st)}` }, `${st.done}/${st.total}`))(planStats(s.todos)) : null,
    s.busy ? h('span', { class: 'dot busy' }) : s.interrupted ? h('span', { class: 'pill pill-amber' }, 'interrupted') : null,
    h('span', { class: 'time' }, relTime(s.updated)))));
}

function field(label, input, help) {
  return h('div', { class: 'field' }, h('label', null, label), input, help ? h('div', { class: 'help' }, help) : null);
}

function modelSelect(current) {
  const models = (S.status && S.status.models) || ['deepseek-flash', 'deepseek-v4-pro'];
  const opts = models.includes(current) || !current ? models : [current, ...models];
  return h('select', null, opts.map(m => h('option', { value: m, selected: m === current }, m)));
}

const BACKEND_HELP = {
  'local+seatbelt': 'Commands run on this machine in the bot’s workspace, confined by macOS Seatbelt: no file access elsewhere in your home folder or PlanD’s data.',
  local: 'Commands run on this machine with your user’s permissions (not an OS sandbox); risky commands ask first.',
  docker: 'Commands run in an isolated Docker container that only sees the bot’s workspace.',
};
const backendLabel = p => p.backend_label || (p.backend === 'docker' ? 'docker' : 'local');

/** "local (sandboxed)" pill + one-line explanation under a backend select, following its value. */
function backendHelpLine(select, osSandbox = 'auto') {
  const line = h('div', { class: 'help muted backend-help' });
  const update = () => {
    const eff = select.value === 'docker' ? 'docker' : S.status && S.status.seatbelt && osSandbox !== 'off' ? 'local+seatbelt' : 'local';
    const label = ((S.status && S.status.backend_labels) || {})[eff] || eff;
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
      sandboxed ? 'local (sandboxed)' : 'local — this machine'),
    h('option', { value: 'docker', selected: current === 'docker', disabled: docker === false && current !== 'docker', title: BACKEND_HELP.docker },
      `docker${docker === false ? ' (not available)' : ' — container'}`));
}

async function agentSettingsPanel() {
  const name = C.view.profile;
  const p = await api('GET', `/api/profiles/${enc(name)}`);
  const s = p.settings;
  const title = h('input', { type: 'text', value: p.title });
  const desc = h('input', { type: 'text', value: p.description || '', placeholder: 'What this bot is good at (teammates see this)' });
  const soul = h('textarea', { rows: 8 });
  soul.value = p.soul || '';
  const model = modelSelect(s.model);
  const thinking = h('input', { type: 'checkbox', checked: !!s.thinking });
  const backend = backendSelect(s.backend, s.os_sandbox);
  const approvals = h('select', null,
    h('option', { value: 'manual', selected: s.approvals !== 'off' }, 'Ask me before risky operations'),
    h('option', { value: 'off', selected: s.approvals === 'off' }, 'Never ask (hard safety floor still applies)'));
  const color = h('input', { type: 'color', class: 'color-input', value: p.avatar });
  const toolsets = (S.status && S.status.toolsets) || s.toolsets;
  const tsBoxes = toolsets.map(t => h('label', { class: 'check' }, h('input', { type: 'checkbox', value: t, checked: s.toolsets.includes(t) }), t));
  const err = h('span', { class: 'form-error' });
  const save = h('button', { type: 'button', class: 'btn btn-primary' }, 'Save');
  save.onclick = async () => {
    save.disabled = true;
    err.textContent = '';
    try {
      await api('PATCH', `/api/profiles/${enc(name)}`, {
        title: title.value.trim() || name, description: desc.value.trim(), soul: soul.value, model: model.value,
        thinking: thinking.checked, backend: backend.value, approvals: approvals.value, avatar: color.value,
        toolsets: tsBoxes.map(l => l.firstChild).filter(c => c.checked).map(c => c.value),
      });
      toast('Saved');
      await loadProfiles();
      renderHead();
    } catch (e) { err.textContent = e.message; } finally { save.disabled = false; }
  };
  const form = h('div', { class: 'p-section' },
    h('div', { class: 'field-row' }, field('Name', title), field('Color', color)),
    field('Description', desc),
    field('SOUL (persona & standing instructions)', soul, 'Changes apply to new sessions; existing sessions keep the prompt they started with.'),
    h('div', { class: 'field-row' }, field('Model', model), field('Sandbox', backend)),
    backendHelpLine(backend, s.os_sandbox),
    h('label', { class: 'check' }, thinking, 'Thinking mode (slower; better multi-step planning)'),
    field('Approvals', approvals),
    h('div', { class: 'field' }, h('div', { class: 'label' }, 'Toolsets'), h('div', { class: 'checks' }, tsBoxes)),
    h('div', { class: 'help muted', style: { fontSize: '11.5px', marginBottom: '10px' } }, `Workspace: ${p.workspace}`),
    h('div', { class: 'form-actions' }, err, save));
  if (name !== 'default') {
    form.append(h('div', { class: 'danger-zone' }, h('div', { class: 'form-actions' },
      h('span', { class: 'help muted spacer', style: { fontSize: '12px' } }, 'Deleting removes this bot’s memory, sessions and workspace.'),
      h('button', {
        type: 'button', class: 'btn btn-danger', onclick: async () => {
          if (!confirm(`Delete @${name}? Its memory, sessions and workspace are removed permanently.`)) return;
          try { await api('DELETE', `/api/profiles/${enc(name)}`); await loadProfiles(); loadRooms(); go('#/chat'); } catch (e) { toast(e.message, 'error'); }
        },
      }, 'Delete bot'))));
  }
  return form;
}

async function boardPanel() {
  const tasks = await api('GET', `/api/rooms/${enc(C.view.roomId)}/tasks`);
  return taskList(tasks, 'No tasks yet. When the lead breaks the goal down, subtasks, owners and results appear here.');
}

async function membersPanel() {
  const room = await api('GET', `/api/rooms/${enc(C.view.roomId)}`);
  if (C && C.view.type === 'room') C.room = { ...(C.room || {}), ...room };
  return section(`Members (${room.member_info.length})`, room.member_info.map(m => h('div', { class: 'member' },
    avatar(m, 32, profileBusy(m.name)),
    h('div', { class: 'm-main' },
      h('div', { class: 'm-title' }, m.title, h('span', { class: 'handle' }, `@${m.name}`), room.lead === m.name ? h('span', { class: 'star', title: 'Lead' }, '★ lead') : null),
      h('div', { class: 'm-desc' }, profileBusy(m.name) ? workingText(m.name) : (m.description || ''))),
    m.missing ? null : h('button', { type: 'button', class: 'btn btn-ghost btn-sm', onclick: () => go(`#/bot/${enc(m.name)}`) }, 'Chat'),
    room.lead === m.name || m.missing ? null : h('button', {
      type: 'button', class: 'btn btn-ghost btn-sm', title: 'Make this bot the default lead',
      onclick: async () => { try { await api('PATCH', `/api/rooms/${enc(room.id)}`, { lead: m.name }); renderPanel({ keepScroll: true }); loadRooms(); } catch (e) { toast(e.message, 'error'); } },
    }, 'Make lead'))),
  h('div', { class: 'p-empty', style: { marginTop: '10px' } }, 'Each member works in its own workspace with its own memory; the group shares only the room transcript, the board and the shared/ folder.'));
}

async function roomSettingsPanel() {
  const room = await api('GET', `/api/rooms/${enc(C.view.roomId)}`);
  const form = groupForm(room);
  const err = h('span', { class: 'form-error' });
  const save = h('button', { type: 'button', class: 'btn btn-primary' }, 'Save');
  save.onclick = async () => {
    err.textContent = '';
    const v = form.values();
    if (!v.members.length) { err.textContent = 'Pick at least one bot.'; return; }
    save.disabled = true;
    try {
      await api('PATCH', `/api/rooms/${enc(room.id)}`, { name: v.name, members: v.members, lead: v.lead, max_rounds: v.maxRounds });
      toast('Saved');
      loadRooms();
      loadRoom();
      C.room = null;
      renderHead();
    } catch (e) { err.textContent = e.message; } finally { save.disabled = false; }
  };
  return h('div', { class: 'p-section' }, form.el, h('div', { class: 'form-actions' }, err, save),
    h('div', { class: 'danger-zone' }, h('div', { class: 'form-actions' },
      h('span', { class: 'help muted spacer', style: { fontSize: '12px' } }, 'Deleting removes the group transcript and board link; bots keep their own memory.'),
      h('button', {
        type: 'button', class: 'btn btn-danger', onclick: async () => {
          if (!confirm(`Delete the group "${room.name}"?`)) return;
          try { await api('DELETE', `/api/rooms/${enc(room.id)}`); loadRooms(); go('#/chat'); } catch (e) { toast(e.message, 'error'); }
        },
      }, 'Delete group'))));
}

const PANEL_BUILDERS = {
  room: { board: boardPanel, members: membersPanel, settings: roomSettingsPanel },
  agent: { memory: memoryPanel, tasks: agentTasksPanel, sessions: sessionsPanel, settings: agentSettingsPanel },
};

// ====================================================================== dialogs
function dialog({ title, subtitle, body, submitLabel, onSubmit }) {
  const err = h('span', { class: 'form-error' });
  const submit = h('button', { type: 'submit', class: 'btn btn-primary' }, submitLabel);
  const dlg = h('dialog', { class: 'dialog' });
  const form = h('form', { class: 'dialog-form', method: 'dialog' },
    h('div', { class: 'dialog-head' }, h('h2', null, title), subtitle ? h('p', null, subtitle) : null),
    h('div', { class: 'dialog-body' }, body),
    h('div', { class: 'dialog-foot' }, err,
      h('button', { type: 'button', class: 'btn', onclick: () => dlg.close() }, 'Cancel'), submit));
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
const PALETTE = ['#6366f1', '#0ea5e9', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6', '#84cc16', '#f97316'];

function newBotDialog() {
  const title = h('input', { type: 'text', placeholder: 'e.g. Code Reviewer', required: true, autofocus: true });
  const name = h('input', { type: 'text', placeholder: 'code-reviewer', pattern: '[a-z0-9][a-z0-9_-]{0,31}', required: true });
  let nameTouched = false;
  title.addEventListener('input', () => { if (!nameTouched) name.value = slug(title.value); });
  name.addEventListener('input', () => { nameTouched = true; });
  const desc = h('input', { type: 'text', placeholder: 'Reviews Python code for bugs and style' });
  const soul = h('textarea', { rows: 6, placeholder: 'Who is this bot and how should it work? e.g. "You are a meticulous reviewer. Read the code, run the tests, and report concrete issues with file:line references."' });
  const model = modelSelect('deepseek-flash');
  const thinking = h('input', { type: 'checkbox' });
  const backend = backendSelect('local');
  const color = h('input', { type: 'color', class: 'color-input', value: PALETTE[Math.floor(Math.random() * PALETTE.length)] });
  const clone = h('select', null, h('option', { value: '' }, '— start fresh —'),
    S.profiles.map(p => h('option', { value: p.name }, `${p.title} (@${p.name})`)));
  dialog({
    title: 'New bot',
    subtitle: 'A bot is an agent with its own identity, memory, sessions and workspace. It gets a private Bot Chat and can join groups.',
    submitLabel: 'Create bot',
    body: h('div', null,
      h('div', { class: 'field-row' }, field('Name', title), field('Handle', name, 'Used for @mentions.')),
      field('Description', desc, 'One line; teammates and leads see it when deciding who should do what.'),
      field('SOUL', soul, 'Optional. Persona and standing instructions (SOUL.md).'),
      h('div', { class: 'field-row' }, field('Model', model), field('Sandbox backend', backend)),
      backendHelpLine(backend),
      h('label', { class: 'check' }, thinking, 'Thinking mode (slower; better for planning-heavy bots)'),
      h('div', { class: 'field-row', style: { marginTop: '10px' } }, field('Color', color), field('Clone memory & skills from', clone))),
    onSubmit: async () => {
      const p = await api('POST', '/api/profiles', {
        name: name.value.trim(), title: title.value.trim(), description: desc.value.trim(), soul: soul.value.trim() || null,
        model: model.value, thinking: thinking.checked, backend: backend.value, avatar: color.value,
        clone_from: clone.value || null, bot: true,
      });
      await loadProfiles();
      S.tab = 'bots';
      go(`#/bot/${enc(p.name)}`);
    },
  });
}

function groupForm(room) {
  const name = h('input', { type: 'text', value: room ? room.name : '', placeholder: 'e.g. Build team', required: true });
  const roster = bots();
  const current = room ? room.members : [];
  const boxes = roster.map(p => h('label', { class: 'check' },
    h('input', { type: 'checkbox', value: p.name, checked: current.includes(p.name) }), avatar(p, 22), h('span', null, p.title), h('span', { class: 'handle' }, `@${p.name}`)));
  const lead = h('select');
  const maxRounds = h('input', { type: 'number', min: 1, max: 10, value: room ? (room.settings && room.settings.max_rounds) || 3 : 3 });
  const checked = () => boxes.map(b => b.querySelector('input')).filter(c => c.checked).map(c => c.value);
  const fillLead = () => {
    const prev = lead.value || (room && room.lead) || '';
    const opts = checked();
    lead.replaceChildren(h('option', { value: '' }, 'Auto — first bot addressed'),
      ...opts.map(n => h('option', { value: n, selected: n === prev }, `@${n}`)));
  };
  boxes.forEach(b => b.querySelector('input').addEventListener('change', fillLead));
  fillLead();
  const el = h('div', null,
    field('Group name', name),
    h('div', { class: 'field' }, h('div', { class: 'label' }, 'Members'),
      roster.length ? h('div', { class: 'member-picks' }, boxes) : h('div', { class: 'p-empty' }, 'Create a bot first.')),
    h('div', { class: 'field-row' },
      field('Lead', lead, 'Coordinates and delegates when addressed.'),
      field('Max rounds per message', maxRounds)));
  return { el, values: () => ({ name: name.value.trim(), members: checked(), lead: lead.value || null, maxRounds: parseInt(maxRounds.value, 10) || 3 }) };
}

function newGroupDialog() {
  if (!bots().length) {
    toast('Create a bot first — groups are made of bots.', 'warn', { label: 'New bot', fn: newBotDialog });
    return;
  }
  const form = groupForm(null);
  dialog({
    title: 'New group',
    subtitle: 'Bots in a group share one conversation and a task board. Give the team a goal; the lead decomposes it and delegates to teammates.',
    submitLabel: 'Create group',
    body: form.el,
    onSubmit: async () => {
      const v = form.values();
      if (!v.name) throw new Error('Give the group a name.');
      if (!v.members.length) throw new Error('Pick at least one bot.');
      const room = await api('POST', '/api/rooms', { name: v.name, members: v.members, lead: v.lead });
      if (v.maxRounds !== 3) await api('PATCH', `/api/rooms/${enc(room.id)}`, { max_rounds: v.maxRounds });
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
        role: ev.role, depth: ev.depth, state: 'thinking', tool: null, origin: ev.origin });
      break;
    case 'run.finished': case 'run.failed': S.runs.delete(key); break;
    case 'llm.request': if (run) Object.assign(run, { state: 'thinking', tool: null }); break;
    case 'tool.started': if (run) Object.assign(run, { state: 'tool', tool: ev.tool }); break;
    case 'tool.finished': if (run) Object.assign(run, { state: 'thinking', tool: null }); break;
    case 'hitl.requested': if (run) run.state = 'waiting'; break;
    case 'hitl.resolved': if (run && run.state === 'waiting') run.state = 'tool'; break;
    case 'todo.updated': if (run) run.todos = ev.todos || []; break;
    case 'assistant.delta': if (run && run.state !== 'waiting') run.state = ev.kind === 'content' ? 'writing' : 'thinking'; break;
    case 'room.drive':
      if (ev.state === 'started') S.drives.set(ev.room_id, ev); else S.drives.delete(ev.room_id);
      break;
    default: break;
  }
}

function onEvent(ev) {
  const t = ev.type;
  if (t === 'assistant.delta') {  // frequent: touch only the streaming bubble and, on a state change, the status
    const run = S.runs.get(runKey(ev.profile, ev.session_id));
    const before = run && run.state;
    trackRun(ev);
    onDelta(ev);
    if (run && run.state !== before) { renderLive(); renderSidebar(); }
    return;
  }
  trackRun(ev);
  if (t === 'assistant.message' || t === 'tool.started' || t === 'run.finished' || t === 'run.failed') finishStream(ev);
  const v = C && C.view;
  const inConv = v && v.type !== 'room' && v.sid && ev.profile === v.profile && ev.session_id === v.sid;
  switch (t) {
    case 'run.started': case 'assistant.message': case 'tool.finished': case 'context.compacted':
      if (inConv) refreshConv();
      break;
    case 'run.finished': case 'run.failed':
      if (inConv) {
        refreshConv();
        if (t === 'run.failed' || ['error', 'budget_exceeded', 'loop_detected'].includes(ev.status)) {
          toast(`Run ended: ${ev.status || 'error'}${ev.error ? ' — ' + String(ev.error).split('\n')[0].slice(0, 140) : ''}`, 'error');
        }
      }
      refreshLists();
      refreshUsage();
      refreshPanel(['memory', 'sessions', 'tasks'], ev.profile);
      break;
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
        if (t === 'room.deleted') { toast('This group was deleted.'); go('#/chat'); } else { if (ev.room) C.room = { ...(C.room || {}), ...ev.room }; renderHead(); refreshPanel(['members']); }
      }
      break;
    case 'room.drive':
      if (ev.state === 'settled') refreshLists();
      break;
    case 'task.updated':
      if (v && v.type === 'room' && ev.room_id === v.roomId) refreshPanel(['board']);
      else if (v && v.type !== 'room' && ev.room_id === `dm:${v.profile}`) refreshPanel(['tasks']);
      break;
    case 'hitl.requested':
      refreshHitl();
      notifyHitl(ev);
      break;
    case 'hitl.resolved':
      refreshHitl();
      break;
    case 'memory.changed': case 'experience.added': case 'experience.retrieved':
      refreshPanel(['memory'], ev.profile);
      break;
    case 'todo.updated':
      if (inConv) C.todos = ev.todos || [];
      refreshPanel(['sessions'], ev.profile);
      break;
    case 'profile.created': case 'profile.updated': case 'profile.deleted':
      refreshLists();
      if (t === 'profile.deleted' && v && v.type !== 'room' && v.profile === ev.profile) {
        toast(`@${ev.profile} was deleted.`);
        go('#/chat');
      }
      break;
    case 'session.created': case 'session.updated': case 'session.deleted':
      if (ev.profile === 'default') refreshLists();
      refreshPanel(['sessions'], ev.profile);
      if (inConv && t === 'session.updated') loadConv();
      break;
    case 'stream.overflow':
      resync();
      break;
    default: break;
  }
  if (HINT_EVENTS.has(t)) {
    // Rows for the open session come with the next fetch; everything else is a passing hint.
    if (inConv && ROW_EVENTS.has(t)) refreshConv();
    else if (eventInView(ev)) flashHint(ev);
  }
  if (t !== 'hello') {
    renderLive();
    renderPlan();
    updateComposer();
    renderSidebar();
  }
}

function renderConn() {
  const el = $('#conn');
  el.classList.toggle('down', !S.wsOk);
  el.replaceChildren(h('span', { class: 'dot' }), S.wsOk ? 'live' : 'reconnecting…');
  el.title = S.wsOk ? 'Receiving live events' : 'Lost the event stream; retrying';
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
  await Promise.allSettled([loadStatus(), loadProfiles(), loadRooms(), loadChats(), loadHitl(), loadActivity(), loadUsage()]);
  if (C) openView(C.view);
}

// ====================================================================== boot
function bind() {
  $$('.side-tabs .tab').forEach(t => t.addEventListener('click', () => { S.tab = t.dataset.tab; renderSidebar(); }));
  $('#new-chat').addEventListener('click', () => go('#/chat'));
  $('#new-bot').addEventListener('click', newBotDialog);
  $('#new-group').addEventListener('click', newGroupDialog);
  $('#hitl-badge').addEventListener('click', toggleTray);
  $('#stop').addEventListener('click', stopRun);
  $('#composer').addEventListener('submit', e => { e.preventDefault(); send(); });
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
      navigator.clipboard.writeText(code).then(() => { btn.textContent = 'Copied'; setTimeout(() => { btn.textContent = 'Copy'; }, 1200); }, () => toast('Copy failed', 'error'));
    }
    if (document.body.classList.contains('sidebar-open') && !e.target.closest('.sidebar') && !e.target.closest('.menu-btn')) {
      document.body.classList.remove('sidebar-open');
    }
    const tray = $('#tray');
    if (!tray.classList.contains('hidden') && !e.target.closest('.tray') && !e.target.closest('#hitl-badge')) tray.classList.add('hidden');
  });
  window.addEventListener('hashchange', route);
  setInterval(() => { if (S.ws && S.ws.readyState === 1) S.ws.send('ping'); }, 25000);
  setInterval(() => renderSidebar(), 60000);  // keep relative times fresh
}

async function boot() {
  bind();
  renderConn();
  await Promise.allSettled([loadStatus(), loadProfiles(), loadRooms(), loadChats(), loadHitl(), loadActivity(), loadUsage()]);
  connectWS();
  route();
  const recovered = (S.status && S.status.recovered) || [];
  if (recovered.length) {
    const first = recovered[0];
    const target = first.kind === 'bot_chat' ? `#/bot/${enc(first.profile)}`
      : first.profile === 'default' && first.kind === 'chat' ? `#/chat/${enc(first.session_id)}` : `#/session/${enc(first.profile)}/${enc(first.session_id)}`;
    toast(`${recovered.length} conversation${recovered.length > 1 ? 's were' : ' was'} interrupted by the last shutdown and can be resumed.`, 'warn',
      { label: 'Open', fn: () => go(target) });
  }
}

boot();
