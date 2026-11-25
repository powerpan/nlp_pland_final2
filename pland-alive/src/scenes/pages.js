// pages.js — the five logbook pages (1600×1000 UI px each) and the cards that fly between them.
// Each page is a list of sheets {rect, S, key(t), paint(x, t)}: a sheet is repainted (and its texture re-uploaded) only when
// its key changes, so static chrome costs nothing per frame. Faces get their own small, sharp sheets.
// Content is the real product's (paths, models, commands, labels); chat contents, task titles, counts and hashes are
// illustrative (示意) unless noted. Labels quoted from the app: pland/server/static/app.js at 4c5a769.
import { TAU, clamp, lerp, seg, ease, easeOut, easeIn, easeInOut, backOut, spring, hash, rng, mix, rgba, text, measure, beatPulse } from '../engine.js';
import { C, BOT, F, rr, T, M, hline, vline, paperTex, seal, avatar, youTile, sendBtn, kbd, chip, check, eyelet, icon, bar, wrap, stamp } from './ui.js';
import { faceKey, stateAt, workLine, busyAt, ringPulse } from './faces.js';
import { TL, B } from './tl.js';

export const PW = 1600, PH = 1000, PIV = [30, 972];
const q = (v, n = 30) => Math.round(v * n);                // quantise a 0..1 progress for sheet keys
const f30 = t => Math.floor(t * 30) / 30;                  // board animations step once per frame (sub-frames share a repaint)
const paper = (x, seed) => x.drawImage(paperTex(PW, PH, seed), 0, 0);
const pad = s => Math.ceil(3.5 * s / 34) + 4;   // room for the busy ring
// a face that lives in its own small sheet: {rect, S, key, paint}
const faceSheet = (name, X, Y, s, { from = -1, to = 1e9, ring = false, gap = C.bg, fade = null } = {}) => ({
  rect: [X - pad(s), Y - pad(s), s + 2 * pad(s), s + 2 * pad(s)], S: s >= 60 ? 5.5 : Math.max(4, 150 / s),
  key: t => t < from ? 'off' : (fade ? q(fade(t), 12) : '') + faceKey(name, t) + (ring && busyAt(name, t) ? ':' + q(ringPulse(t), 16) : ''),
  paint: (x, t) => { if (t < from) return; avatar(x, X, Y, s, name, t, { ring, gap, alpha: fade ? fade(t) : 1 }); } });

// ───────────────────────── page 0: the PlanD window ─────────────────────────
export const PROMPT = '@lead Write up the eval results, run the tests, push to main.';
const typedN = t => Math.floor(clamp((t - TL.typeA) / (TL.typeB - TL.typeA)) * PROMPT.length);
const MCX = 936, COLX = 556, COLR = 1316;                  // message column
// the lead's 'think high' chip on its Team card (page 2): the thinking menus open above it, left-aligned
export const MENU_AT = { x0: 242, y: 298, chip: [286, 320] };

function chatBase(x) {
  paper(x, 11);
  // title bar
  x.fillStyle = '#E9E4D8'; x.beginPath(); x.roundRect(0, 0, PW, 38, [14, 14, 0, 0]); x.fill(); hline(x, 0, PW, 38, C.border2);
  [22, 42, 62].forEach(cx => { x.fillStyle = '#DED7C7'; x.strokeStyle = '#CBC3B1'; x.lineWidth = 1; x.beginPath(); x.arc(cx, 19, 6, 0, TAU); x.fill(); x.stroke(); });
  const tw = M(x, 'PlanD', { size: 13, family: F.serif, weight: 600 });
  T(x, 'PlanD', 800 - 70, 19, { size: 13, family: F.serif, weight: 600, col: C.text2 }); T(x, '—  127.0.0.1:8765', 800 - 70 + tw + 8, 19.5, { size: 11, family: F.mono, weight: 400, col: C.muted });
  // sidebar
  x.fillStyle = C.side; x.fillRect(0, 38, 272, PH - 38 - 14); x.beginPath(); x.roundRect(0, PH - 30, 272, 30, [0, 0, 0, 14]); x.fill(); vline(x, 272, 38, PH, C.border);
  seal(x, 35, 76, 30, { ink: .35 }); T(x, 'PlanD', 62, 70, { size: 19, family: F.serif, weight: 600, col: C.ink });
  T(x, 'DEEPSEEK · DEEPSEEK-FLASH', 62, 91, { size: 10, family: F.mono, weight: 500, col: C.muted, track: .5 });
  T(x, 'Chats', 22, 130, { size: 13.5, family: F.sans, weight: 500, col: C.muted });
  T(x, 'Bots & groups', 72, 130, { size: 13.5, family: F.sans, weight: 600, col: C.ink }); rr(x, 72, 142, M(x, 'Bots & groups', { size: 13.5, family: F.sans, weight: 600 }), 2, 1, C.acc); hline(x, 0, 272, 146, C.border);
  T(x, 'BOTS', 22, 172, { size: 10, family: F.mono, weight: 600, col: C.muted, track: 1.2 }); T(x, 'Templates', 134, 172, { size: 11.5, family: F.sans, weight: 500, col: C.text2 }); T(x, '+ New bot', 200, 172, { size: 11.5, family: F.sans, weight: 500, col: C.text2 });
  T(x, 'GROUPS', 22, 488, { size: 10, family: F.mono, weight: 600, col: C.muted, track: 1.2 }); T(x, '+ New group', 186, 488, { size: 11.5, family: F.sans, weight: 500, col: C.text2 });
  rr(x, 10, 506, 252, 52, 8, C.bg3); rr(x, 10, 568, 252, 52, 8, null);
  T(x, 'Research desk', 76, 586, { size: 13.5, family: F.sans, weight: 600, col: C.ink }); T(x, '2 members', 76, 604, { size: 11, family: F.mono, weight: 400, col: C.muted });
  hline(x, 0, 272, 896, C.border);
  icon(x, 'gear', 30, 918, 14, C.text2, 1.4); T(x, 'Settings', 46, 918.5, { size: 13, family: F.sans, weight: 500, col: C.text2 });
  x.fillStyle = C.ok; x.beginPath(); x.arc(186, 918, 3.5, 0, TAU); x.fill(); T(x, 'LIVE', 196, 918.5, { size: 10.5, family: F.mono, weight: 500, col: C.muted, track: .8 });
  T(x, '312 calls · 4.8M tok · $0.41', 52, 944, { size: 10.5, family: F.mono, weight: 400, col: C.muted });
  // conversation header: the bot's face (its own sheet), the title, the subtitle
  // room header (.conv-head): a stack of four member faces (their own sheets), the room name, members, the shared folder; Chat | Board
  hline(x, 272, PW, 98, C.border);
  T(x, 'Build team', 408, 61, { size: 18, family: F.serif, weight: 600, col: C.ink });
  let sx = 408 + T(x, '@lead', 408, 83, { size: 10.5, family: F.mono, weight: 400, col: C.muted }); sx += T(x, ' ★', sx, 82.5, { size: 10.5, family: F.sans, weight: 600, col: C.warn });
  T(x, ' · @researcher · @coder · @reviewer · @writer · ~/nlp_final_pland', sx, 83, { size: 10.5, family: F.mono, weight: 400, col: C.muted });
  { const X1 = 1446, w1 = 58, w2 = 74; rr(x, X1, 54, w1 + w2 + 6, 30, 8, C.bg, C.border2); rr(x, X1 + 3, 57, w1, 24, 6, C.sheet, C.border2);
    T(x, 'Chat', X1 + 16, 69.5, { size: 12.5, family: F.sans, weight: 600, col: C.ink }); const bw = T(x, 'Board', X1 + w1 + 16, 69.5, { size: 12.5, family: F.sans, weight: 500, col: C.text2 }); }
}

// a room activity row (.activity): 18 px face, bold @who, the line; a 2 px left rule (accent →, ok ✓, err ✗); the time
function activity(x, y, who, line, kind, t, k = 1) {
  if (k <= 0) return; x.save(); x.globalAlpha *= clamp(k * 1.5); x.translate(0, (1 - easeOut(k)) * 8);
  const col = kind === 'ok' ? C.ok : kind === 'err' ? C.err : C.acc; x.fillStyle = col; x.fillRect(COLX + 42, y, 2, 28);
  avatar(x, COLX + 54, y + 5, 18, who, t, { still: true });
  const ww = T(x, '@' + who, COLX + 80, y + 14.5, { size: 12.5, family: F.sans, weight: 600, col: C.ink });
  T(x, line, COLX + 88 + ww, y + 14.5, { size: 12.5, family: F.sans, weight: 400, col: C.text2 });
  text(x, '10:43', COLR - 8, y + 14.5, { size: 10.5, family: F.mono, weight: 400, col: C.muted, align: 'right' });
  x.restore();
}
const LEAD_SAYS = "On it. I'll write a plan, hand the write-up to the team, run the tests, and ask you before pushing anything.";
const DONE_SAYS = 'Done. report.md is in docs/, the tests pass (188 passed, 2 skipped), and main is pushed (a1c9e2f).';

export function chatMsgsKey(t) {
  if (t < TL.send - .05) return 'empty';
  if (t < TL.bubbleLand + 1.0) return 'fly' + q(t, 60);
  if (t < TL.lead + 2.2) return 'lead' + q(t, 30);
  return ['rows', ...[TL.slip(0), TL.slip(1), TL.done1, TL.done1 + .1, TL.redo2, TL.done3].map(a => q(seg(t, a, a + .4), 12)), t > TL.pushed ? q(seg(t, TL.pushed, TL.pushed + 1.4), 30) : -1].join(':');
}
export function chatMsgs(x, t) {
  paper(x, 11);
  const fly = seg(t, TL.send + .12, TL.bubbleLand + .35), emptyK = 1 - easeInOut(seg(t, TL.send + .05, TL.send + .55));
  if (emptyK > 0) {   // the empty state, exactly as the app shows it
    x.save(); x.globalAlpha = emptyK; x.translate(0, -(1 - emptyK) * 30);
    x.fillStyle = 'rgba(28,26,22,.09)'; for (let gx = 283; gx < PW; gx += 22) for (let gy = 109; gy < 788; gy += 22) { x.beginPath(); x.arc(gx, gy, 1.15, 0, TAU); x.fill(); }
    const X = 656; T(x, 'GROUP · 5 MEMBERS', X, 250, { size: 10.5, family: F.mono, weight: 600, col: C.muted, track: 1.1 });
    ['lead', 'researcher', 'coder', 'reviewer', 'writer'].forEach((n, i) => { x.fillStyle = C.bg; x.beginPath(); x.roundRect(X + i * 32 - 2, 274, 44, 44, 13); x.fill(); avatar(x, X + i * 32, 276, 40, n, 0, { still: true }); });
    T(x, 'Build team', X, 360, { size: 52, family: F.serif, weight: 600, col: C.ink, track: -1.4 });
    ['Give the team a goal. Mention @name to address one bot, or write to everyone;', '@lead leads, breaks the work down on the board and delegates to teammates.'].forEach((s, i) => T(x, s, X, 412 + i * 24, { size: 15, family: F.sans, weight: 400, col: C.text2 }));
    x.restore();
  }
  if (t < TL.send) return;
  // the user's bubble rises from the composer and lands top right
  const bw = M(x, PROMPT, { size: 14.5, family: F.sans, weight: 400 }) + 28, k = easeInOut(fly), lift = easeOut(seg(t, TL.send, TL.send + .12)), sp = spring(t - TL.bubbleLand - .18, 2.2, 7);
  const by = lerp(760, 124, k) - lift * 12 * (1 - k) + (fly >= 1 ? (1 - sp) * 6 : 0), bs = lerp(.94, 1, k);
  x.save(); x.translate(COLR, by + 20); x.scale(bs, bs); x.translate(-COLR, -(by + 20));
  x.fillStyle = C.user; x.beginPath(); x.roundRect(COLR - bw, by, bw, 40, [14, 14, 3, 14]); x.fill();
  T(x, PROMPT, COLR - bw + 14, by + 20.5, { size: 14.5, family: F.sans, weight: 400, col: C.ink }); x.restore();
  if (t < TL.lead) return;
  // lead answers (its face is a sheet of its own, see PAGES)
  const la = easeOut(seg(t, TL.lead, TL.lead + .4)); x.save(); x.globalAlpha = la;
  const nw = T(x, 'Team Lead', COLX + 42, 208, { size: 13.5, family: F.sans, weight: 600, col: C.ink }); T(x, '@lead', COLX + 50 + nw, 209, { size: 11.5, family: F.mono, weight: 400, col: C.muted });
  T(x, '10:42', COLR - 32, 209, { size: 10.5, family: F.mono, weight: 400, col: C.muted });
  const n = Math.floor(clamp((t - TL.lead - .3) / 1.6) * LEAD_SAYS.length), lines = wrap(x, LEAD_SAYS, COLR - COLX - 42, { size: 14.5, family: F.sans, weight: 400 });
  let left = n; lines.forEach((s, i) => { const part = s.slice(0, Math.max(0, left)); left -= s.length + 1; T(x, part, COLX + 42, 236 + i * 23, { size: 14.5, family: F.sans, weight: 400, col: C.ink }); });
  x.restore();
  // the room's activity rows (the lead posts them as it delegates; delegation.py)
  const A = (tt, i, who, line, kind) => activity(x, 292 + i * 32, who, line, kind, t, seg(t, tt, tt + .4));
  A(TL.slip(0), 0, 'lead', '→ delegated to @writer: Draft report.md', 'start'); A(TL.slip(1), 1, 'lead', '→ delegated to @coder: Check the numbers', 'start');
  A(TL.done1, 2, 'lead', '✗ delegated task failed: Check the numbers', 'err'); A(TL.done1 + .1, 3, 'lead', '✓ finished delegated task: Draft report.md', 'ok');
  A(TL.redo2, 4, 'lead', '→ delegated to @coder: Check the numbers', 'start'); A(TL.done3, 5, 'lead', '✓ finished delegated task: Review report.md', 'ok');
  if (t > TL.pushed) {   // the finished answer
    const k3 = seg(t, TL.pushed, TL.pushed + 1.4); x.save(); x.globalAlpha = easeOut(seg(t, TL.pushed, TL.pushed + .3));
    const n2 = Math.floor(k3 * DONE_SAYS.length), ls = wrap(x, DONE_SAYS, COLR - COLX - 42, { size: 14.5, family: F.sans, weight: 400 });
    let l2 = n2; ls.forEach((s, i) => { T(x, s.slice(0, Math.max(0, l2)), COLX + 42, 506 + i * 23, { size: 14.5, family: F.sans, weight: 400, col: C.ink }); l2 -= s.length + 1; });
    if (k3 >= 1) { let cx = COLX + 42; [['report.md', C.ink], ['188 passed', C.ok], ['main ← a1c9e2f', C.accInk]].forEach(([s, col]) => { cx += chip(x, cx, 564, s, { size: 11.5, col, h: 26 }) + 8; }); }
    x.restore();
  }
}

// composer strip: plan widget, live line, the input itself (as style.css draws it), hints
const LIVE = t0 => { const t = f30(t0); return t < TL.lead ? '' : t < TL.pushAsk ? 'Team is working…' : t < TL.click ? 'lead is waiting for you' : t < TL.pushed ? 'Team is working…' : t < TL.pushed + 1.4 ? 'lead is writing…' : '✓ done · 176 calls · $0.33'; };
export function chatCompKey(t) {
  const typing = t < TL.send + .6 ? `${typedN(t)}:${Math.floor(t * 2.4) % 2}:${q(seg(t, TL.send - .08, TL.send + .2), 20)}` : 'x';
  return [typing, LIVE(t), planDone(t), t > TL.planItems, q(seg(t, TL.lead, TL.lead + .4), 12)].join('|');
}
export const planDone = t => t < TL.planCheck(0) ? 0 : t < TL.planCheck(1) ? 1 : t < TL.done3 ? 2 : t < TL.testsPass ? 3 : t < TL.pushed ? 4 : 5;
// a picker chip (.pick): 32 px, transparent, 12 px mono, label + ⌄; returns its left edge
function pick(x, xr, y, label, { open = false, press = 0 } = {}) {
  const lw = M(x, label, { size: 12, family: F.mono, weight: 500 }), w = lw + 8 + 14 + 8, X = xr - w;
  x.save(); x.translate(X + w / 2, y); x.scale(1 - press * .06, 1 - press * .06); x.translate(-(X + w / 2), -y);
  if (open) rr(x, X, y - 16, w, 32, 8, C.bg3);
  T(x, label, X + 8, y + .5, { size: 12, family: F.mono, weight: 500, col: C.text2 }); T(x, '⌄', X + 8 + lw + 4, y - 2.5, { size: 12, family: F.mono, weight: 500, col: C.muted });
  x.restore(); return X;
}
export function chatComp(x, t) {
  paper(x, 11);
  if (t > TL.planItems) {   // the plan widget above the composer
    rr(x, COLX, 796, COLR - COLX, 36, 8, C.sheet, C.border); const d = planDone(t);
    T(x, '›', COLX + 12, 814, { size: 14, family: F.mono, weight: 600, col: C.muted });
    let px = COLX + 28 + T(x, 'PLAN', COLX + 28, 814.5, { size: 10.5, family: F.mono, weight: 600, col: C.ink, track: .8 }) + 8;
    px += T(x, `lead · ${d}/5`, px, 814.5, { size: 11, family: F.mono, weight: 600, col: C.muted }) + 12; bar(x, px, 811, 56, 5, d / 5, C.acc); px += 68;
    T(x, PLAN_ITEMS[Math.min(4, d)][0], px, 814.5, { size: 12.5, family: F.sans, weight: 400, col: C.muted });
  }
  const live = LIVE(t);
  if (live) { const a = easeOut(seg(t, TL.lead, TL.lead + .4)); x.save(); x.globalAlpha = a;
    const done = live[0] === '✓'; if (!done) T(x, '◐◓◑◒'[Math.floor(f30(t) * 8) % 4], COLX + 4, 851, { size: 11.5, family: F.mono, weight: 500, col: C.acc });
    T(x, live, done ? COLX + 4 : COLX + 22, 851.5, { size: 11.5, family: F.mono, weight: 400, col: done ? C.ok : C.text2 }); x.restore(); }
  // the composer card (style.css .composer): 1 px #C9C2B2, radius 14, sheet, soft shadow; the border darkens while focused
  const press = seg(t, TL.send - .08, TL.send) * (1 - seg(t, TL.send + .02, TL.send + .2));
  x.save(); x.shadowColor = 'rgba(28,26,22,.12)'; x.shadowBlur = 24; x.shadowOffsetY = 8; rr(x, COLX, 866, COLR - COLX, 56, 14, C.sheet); x.restore();
  rr(x, COLX, 866, COLR - COLX, 56, 14, null, t < TL.send + .3 && t > TL.typeA - .3 ? C.text2 : C.border2, 1.2);
  T(x, '+', COLX + 16, 893, { size: 24, family: F.sans, weight: 300, col: C.text2 });
  const n = typedN(t), sent = t >= TL.send;
  if (!sent && n > 0) { const s = PROMPT.slice(0, n), w = T(x, s, COLX + 50, 894.5, { size: 14.5, family: F.sans, weight: 400, col: C.ink });
    if (Math.floor(t * 2.4) % 2 === 0 || t < TL.typeB + .1) { x.fillStyle = C.acc; x.fillRect(COLX + 51 + w, 884, 1.6, 21); } }
  else { T(x, 'Message Build team — @mention a bot to address it', COLX + 50, 894.5, { size: 14.5, family: F.sans, weight: 400, col: C.muted, alpha: sent ? easeOut(seg(t, TL.send + .25, TL.send + .6)) : 1 });
    if (!sent && Math.floor(t * 2.4) % 2 === 0) { x.fillStyle = C.acc; x.fillRect(COLX + 50, 884, 1.6, 21); } }
  sendBtn(x, COLR - 30, 894, 16, { press, dim: n === 0 && !sent });
  // hints
  let hx = 750; [['↵', 'send'], ['⇧↵', 'new line'], ['@', 'mention a bot'], ['⌘B', 'sidebar']].forEach(([k, s]) => { hx += kbd(x, hx, 944, k, 10) + 5; hx += T(x, s, hx, 944.5, { size: 11, family: F.sans, weight: 400, col: C.muted }) + 18; });
}

// the sidebar's Bots & groups list (live): face, title, handle, what it is doing; the group row with its face stack
const SIDE = [['lead', 'Team Lead'], ['researcher', 'Researcher'], ['coder', 'Python Engineer'], ['reviewer', 'QA Reviewer'], ['writer', 'Tech Writer']];
const SIDE_IDLE = { lead: 'Breaks goals into board tasks…', researcher: 'Finds current facts on the web…', coder: 'Writes and tests Python code…', reviewer: 'Independently tests and revi…', writer: 'Writes clear Markdown or pla…' };
export const sideKey = t => SIDE.map(([n]) => faceKey(n, t) + (busyAt(n, t) ? workLine(n, t) + q(ringPulse(t), 8) : stateAt(n, t).s)).join('|');
export function sidePaint(x, t) {
  SIDE.forEach(([n, title], i) => { const y = 190 + i * 56;
    avatar(x, 22, y, 34, n, t, { ring: true, gap: C.side });
    const nw = T(x, title, 68, y + 11, { size: 13.5, family: F.sans, weight: 600, col: C.ink }); T(x, '@' + n, 74 + nw, y + 11.5, { size: 11, family: F.mono, weight: 400, col: C.muted });
    const busy = busyAt(n, t); T(x, busy ? workLine(n, t) : SIDE_IDLE[n], 68, y + 29, { size: 11.5, family: busy ? F.mono : F.sans, weight: busy ? 500 : 400, col: busy ? C.accInk : C.muted }); });
  ['lead', 'researcher', 'coder'].forEach((n, i) => { x.fillStyle = C.bg3; x.beginPath(); x.roundRect(20 + i * 14, 518, 28, 28, 8); x.fill(); avatar(x, 22 + i * 14, 520, 24, n, t); });
  const nw = T(x, 'Build team', 76, 524, { size: 13.5, family: F.sans, weight: 600, col: C.ink }); T(x, '5', 82 + nw, 524.5, { size: 11, family: F.mono, weight: 500, col: C.muted });
  const any = SIDE.some(([n]) => busyAt(n, t)); T(x, any ? 'Team is working…' : t < TL.lead ? 'No messages yet' : 'lead: Done. report.md is in docs/…', 76, 542, { size: 11.5, family: any ? F.mono : F.sans, weight: 400, col: any ? C.accInk : C.muted });
}
// the thread on the window page: from the send button, down and left along the bottom margin to the binding eyelet
export const threadPathPts = [[COLR - 30, 910], [COLR - 30, 972], [PIV[0], PIV[1]]];
export function chatThreadKey(t) { return q(seg(t, TL.send + .02, TL.send + .5), 40) + ':' + (t > TL.send && t < TL.send + .7 ? Math.floor(t * 30) : 'z') + ':' + q(eyeFlare(t), 12); }
// the eyelet flares when the foreign needle strikes it (S6b)
export const eyeFlare = t => t < TL.fHit ? 0 : Math.exp(-(t - TL.fHit) * 3.2) * (t < TL.fHit + 1.8 ? 1 : 0);
export function chatThread(x, t) {
  eyelet(x, PIV[0], PIV[1], 10);
  const fl = eyeFlare(t); if (fl > .02) { x.save(); x.globalCompositeOperation = 'lighter'; const g = x.createRadialGradient(PIV[0], PIV[1], 4, PIV[0], PIV[1], 30); g.addColorStop(0, `rgba(255,214,140,${(.9 * fl).toFixed(3)})`); g.addColorStop(1, 'rgba(255,170,90,0)'); x.fillStyle = g; x.fillRect(PIV[0] - 30, PIV[1] - 30, 60, 60); x.restore(); }
  const k = easeInOut(seg(t, TL.send + .02, TL.send + .5)); if (k <= 0) return;
  const [a, b, c] = threadPathPts, L1 = b[1] - a[1], L2 = b[0] - c[0], L = (L1 + L2) * k;
  const pts = [a]; if (L <= L1) pts.push([a[0], a[1] + L]); else { pts.push(b); pts.push([b[0] - (L - L1), b[1]]); }
  x.save(); x.lineCap = 'round'; x.lineJoin = 'round';
  x.strokeStyle = 'rgba(90,30,10,.22)'; x.lineWidth = 3.4; x.beginPath(); pts.forEach((p, i) => i ? x.lineTo(p[0] + 1, p[1] + 1.6) : x.moveTo(p[0] + 1, p[1] + 1.6)); x.stroke();   // its shadow on the paper
  x.strokeStyle = C.acc; x.lineWidth = 2.6; x.beginPath(); pts.forEach((p, i) => i ? x.lineTo(p[0], p[1]) : x.moveTo(p[0], p[1])); x.stroke();
  x.strokeStyle = 'rgba(255,190,160,.55)'; x.lineWidth = .9; x.setLineDash([3, 4]); x.beginPath(); pts.forEach((p, i) => i ? x.lineTo(p[0], p[1] - .5) : x.moveTo(p[0], p[1] - .5)); x.stroke();   // the twist of the thread
  x.restore();
  if (k < 1) { const p = pts[pts.length - 1]; const g = x.createRadialGradient(p[0], p[1], 0, p[0], p[1], 16); g.addColorStop(0, 'rgba(255,170,120,.9)'); g.addColorStop(1, 'rgba(255,120,60,0)'); x.fillStyle = g; x.fillRect(p[0] - 16, p[1] - 16, 32, 32); }
}

// ───────────────────────── shared chrome for the pages beneath ─────────────────────────
function chrome(x, num, kicker, title, zh, sub, seed) {
  paper(x, seed);
  rr(x, 60, 46, 26, 3, 1.5, C.acc); T(x, `${num} / ${kicker}`, 98, 48, { size: 14, family: F.mono, weight: 700, col: C.acc, track: 2.4 });
  T(x, title, 56, 118, { size: 66, family: F.serif, weight: 600, col: C.ink, track: -1.4 });
  T(x, zh, 60, 171, { size: 25, family: F.tcs, weight: 500, col: C.text2, track: 3 });
  text(x, sub, 1540, 171, { size: 13.5, family: F.mono, weight: 400, col: C.muted, align: 'right' });
  text(x, `p. 0${+num + 1}`, 1540, 48, { size: 13, family: F.mono, weight: 500, col: C.muted, align: 'right' });
  hline(x, 60, 1540, 198, C.border2); hline(x, 60, 1540, 202, C.border);
  hline(x, 60, 1540, 950, C.border); text(x, 'PlanD · logbook', 1540, 972, { size: 11, family: F.mono, weight: 400, col: C.muted, align: 'right' });
  eyelet(x, PIV[0], PIV[1], 10);
}

// ───────────────────────── page 1: Plan ─────────────────────────
export const PLAN_ITEMS = [
  ['Read the eval results', 'docs/eval_results/final/results.json'],
  ['Split the write-up across the team', '@writer drafts · @coder checks the numbers · @reviewer reads'],
  ['Draft report.md', 'inbox/from-writer/report.md'],
  ['Run the tests', 'pytest -q  ·  190 tests'],
  ['Push to main', 'git push origin main  ·  needs your approval'],
];
function planBase(x) {
  chrome(x, '01', 'PLAN', 'It plans before it acts.', '先寫計畫，再動手。', 'todo · lead · deepseek-flash · thinking High', 21);
  rr(x, 60, 228, 960, 694, 16, C.sheet, C.border);
  T(x, 'PLAN', 96, 270, { size: 13, family: F.mono, weight: 600, col: C.ink, track: 1.5 }); T(x, 'lead · todo', 160, 270, { size: 13, family: F.mono, weight: 400, col: C.muted });
  hline(x, 96, 984, 300, C.border, 1, [4, 5]);
  // right column: the run
  rr(x, 1068, 228, 472, 324, 16, C.sheet, C.border);
  T(x, 'RUN', 1100, 270, { size: 13, family: F.mono, weight: 600, col: C.ink, track: 1.5 }); T(x, 'limits keep long runs honest', 1160, 270, { size: 13, family: F.mono, weight: 400, col: C.muted });
  rr(x, 1068, 584, 472, 338, 16, C.bg2, C.border);
  T(x, '“', 1094, 650, { size: 80, family: F.serif, weight: 500, col: C.acc });
  ['A plan that goes stale', 'gets flagged: the agent', 'is reminded, and the UI', 'marks it “not updated”.'].forEach((s, i) => T(x, s, 1100, 672 + i * 40, { size: 27, family: F.serif, weight: 500, italic: true, col: C.text2 }));
  T(x, 'todo tool · plan reminders', 1100, 880, { size: 12, family: F.mono, weight: 400, col: C.muted });
}
export function planDynKey(t) { return [q(seg(t, TL.planItems - .2, TL.planItems + 2.2), 40), planDone(t), q(seg(t, TL.planCheck(0), TL.planCheck(0) + .35), 12), q(seg(t, TL.planCheck(1), TL.planCheck(1) + .35), 12), q(clamp((t - TL.s3) / 5), 25)].join(':'); }
export function planDyn(x, t) {
  x.fillStyle = C.sheet; x.fillRect(70, 304, 940, 600); x.fillRect(1078, 282, 452, 260);
  const d = planDone(t);
  text(x, `${d} / 5`, 920, 270, { size: 14, family: F.mono, weight: 600, col: C.ink, align: 'right' }); bar(x, 934, 266, 52, 7, d / 5, C.acc);
  PLAN_ITEMS.forEach(([a, b], i) => {
    const k = easeOut(seg(t, TL.planItems + i * .32, TL.planItems + i * .32 + .5)); if (k <= 0) return;
    const y = 352 + i * 112; x.save(); x.globalAlpha = k; x.translate((1 - k) * -24, 0);
    const state = i < d ? 'done' : i === d ? 'now' : 'todo';
    if (state === 'now') { rr(x, 84, y - 40, 912, 92, 12, C.accSoft); rr(x, 84, y - 40, 5, 92, 2.5, C.acc); }
    const ck = i < 2 ? easeOut(seg(t, TL.planCheck(i), TL.planCheck(i) + .3)) : 1;
    if (state === 'done') { x.save(); const s = i < 2 ? 1 + (1 - ck) * .8 : 1; x.translate(118, y); x.scale(s, s); check(x, 0, 0, 22, C.ok, 3.4); x.restore(); }
    else if (state === 'now') { x.fillStyle = C.acc; x.beginPath(); x.arc(118, y, 9 + beatPulse(t, 6) * 2, 0, TAU); x.fill(); }
    else { x.strokeStyle = C.border2; x.lineWidth = 2.4; x.beginPath(); x.arc(118, y, 10, 0, TAU); x.stroke(); }
    const w = T(x, a, 152, y - 4, { size: 30, family: F.sans, weight: state === 'now' ? 600 : 500, col: state === 'done' ? C.muted : C.ink });
    if (state === 'done') hline(x, 152, 152 + w * (i < 2 ? ck : 1), y - 3, C.border2, 2);
    T(x, b, 153, y + 30, { size: 15, family: F.mono, weight: 400, col: state === 'now' ? C.accInk : C.muted });
    x.restore();
  });
  // the run counters tick with the work
  const r = clamp((t - TL.s3) / 5), steps = Math.round(lerp(4, 9, r)), calls = Math.round(lerp(6, 18, r)), tok = lerp(.08, .31, r);
  [['steps', steps, 80, `${steps} / 80`], ['model calls', calls, 600, `${calls} / 600`], ['weighted tokens', tok, 16, `${tok.toFixed(2)}M / 16M`]].forEach(([lab, v, mx, s], i) => {
    const y = 330 + i * 72; T(x, lab, 1100, y, { size: 15, family: F.sans, weight: 500, col: C.text2 }); text(x, s, 1508, y, { size: 14, family: F.mono, weight: 600, col: C.ink, align: 'right' });
    bar(x, 1100, y + 20, 408, 8, Math.max(.015, v / mx), i ? C.ink : C.acc); });
}

// ───────────────────────── page 2: Team — living faces and the live board ─────────────────────────
// the requirements-team template: handle, title, thinking, tools
export const TEAM = [['lead', 'Team Lead', 'high', 'files · code · git · delegate_task', 'todo'], ['researcher', 'Researcher', 'low', 'web_search · web_fetch · files', 'web_search'],
  ['coder', 'Python Engineer', 'default', 'files · run_python · run_shell', 'run_python'], ['reviewer', 'QA Reviewer', 'max', 'files · run_shell · container', 'run_shell'], ['writer', 'Tech Writer', 'low', '.md / .txt only', 'write_file']];
export const teamCard = i => [60 + i * 298, 222, 276, 206];   // x, y, w, h (UI px)
export const FACE_S = 92, faceXY = i => { const [X, Y] = teamCard(i); return [X + 18, Y + 18]; };
// each bot's own description, shortened from its profile (pland/team_templates/requirements-team.yaml)
const IDLE_LINE = { lead: 'splits goals into board tasks', researcher: 'finds facts on the web, cites them', coder: 'writes and tests Python', reviewer: 'reviews; a PASS or FAIL verdict', writer: 'writes docs from the files' };
const landedBot = (i, t) => t >= TL.roll(i);
function teamBase(x) {
  chrome(x, '02', 'TEAM', 'Build your bot team.', '組建你自己的 Bot 團隊。', 'Bot Mode · each bot: its own model, memory and workspace', 31);
  // the team is yours to make: the Bots section head's own buttons (index.html: Templates, + New bot)
  let bx = 1540; [['+ New bot', C.ink], ['Templates', C.text2]].forEach(([s, col], i) => {
    bx -= chip(x, bx, 128, s, { size: 13, h: 32, r: 8, align: 'right', family: F.sans, weight: i ? 500 : 600, col, border: i ? C.border2 : C.ink }) + 10; });
  // the empty places the new bots are dealt into: a dashed outline, "+ New bot", and what you choose for each
  TEAM.forEach((_, i) => { const [X, Y, w, h] = teamCard(i); x.save(); x.setLineDash([5, 5]); rr(x, X + 1, Y + 1, w - 2, h - 2, 14, null, C.border2, 1); x.restore();
    const cx = X + w / 2; x.save(); x.strokeStyle = C.border2; x.lineWidth = 1.4; x.beginPath(); x.arc(cx, Y + 74, 21, 0, TAU); x.stroke();
    x.strokeStyle = C.muted; x.lineWidth = 2; x.lineCap = 'round'; x.beginPath(); x.moveTo(cx - 8, Y + 74); x.lineTo(cx + 8, Y + 74); x.moveTo(cx, Y + 66); x.lineTo(cx, Y + 82); x.stroke(); x.restore();
    text(x, 'New bot', cx, Y + 124, { size: 15, family: F.sans, weight: 600, col: C.text2, align: 'center' });
    text(x, 'name · model · thinking', cx, Y + 150, { size: 11.5, family: F.mono, weight: 400, col: C.muted, align: 'center' }); });
  // the board's frame: strip + five columns (style.css .board-cols, .kcol)
  hline(x, 60, 1540, 446, C.border2); T(x, 'TASK BOARD', 60, 470, { size: 12, family: F.mono, weight: 700, col: C.ink, track: 1.6 });
  BCOLS.forEach(([, name, col], i) => { const X = colX(i); rr(x, X, BOARD.y, BOARD.w, BOARD.h, 8, C.bg2, C.border);
    x.fillStyle = col; x.beginPath(); x.roundRect(X + 14, BOARD.y + 18, 9, 9, 2); x.fill();
    T(x, name.toUpperCase(), X + 32, BOARD.y + 23, { size: 11.5, family: F.mono, weight: 600, col: C.ink, track: 1 });
    hline(x, X + 1, X + BOARD.w - 1, BOARD.y + 42, C.border, 1, [3, 3]); });
}
// one bot card at (X, Y): name, title, model and thinking chips, status, tools. withFace: draw the face here (in flight)
export function drawBotCard(x, X, Y, i, t, { withFace = false } = {}) {
  const [n, title, think, tools, tool] = TEAM[i], w = 276, h = 206;
  x.save(); x.shadowColor = 'rgba(28,26,22,.08)'; x.shadowBlur = 14; x.shadowOffsetY = 4; rr(x, X, Y, w, h, 14, C.sheet); x.restore(); rr(x, X, Y, w, h, 14, null, C.border);
  if (withFace) avatar(x, X + 18, Y + 18, FACE_S, n, t, { ring: true, gap: C.sheet });
  const nw = T(x, n, X + 124, Y + 42, { size: 27, family: F.serif, weight: 600, col: C.ink }); if (n === 'lead') T(x, '★', X + 128 + nw, Y + 40, { size: 15, family: F.sans, weight: 600, col: C.warn });
  T(x, title, X + 125, Y + 68, { size: 13.5, family: F.sans, weight: 500, col: C.muted });
  let cx = X + 124; cx += chip(x, cx, Y + 98, 'flash', { size: 11.5, h: 24 }) + 5; chip(x, cx, Y + 98, `think ${think}`, { size: 11.5, h: 24 });
  hline(x, X + 18, X + w - 18, Y + 128, C.border, 1, [3, 4]);
  const { s } = stateAt(n, t), busy = busyAt(n, t), line = busy ? workLine(n, t, tool) : s === 'done' ? (n === 'reviewer' ? 'verdict: PASS · 0 issues' : 'finished · handed back') : s === 'error' ? 'stopped: max_iterations' : IDLE_LINE[n];
  x.fillStyle = busy ? C.acc : s === 'error' ? C.err : s === 'done' ? C.ok : C.border2; x.beginPath(); x.arc(X + 24, Y + 150, 4.5, 0, TAU); x.fill();
  T(x, line, X + 36, Y + 150.5, { size: 12.5, family: F.mono, weight: 500, col: busy ? C.accInk : s === 'error' ? C.err : s === 'done' ? C.ok : C.muted });
  const clr = n === 'reviewer' ? seg(t, TL.pass - .12, TL.pass + .02) : 0;
  if (clr < 1) T(x, tools, X + 18, Y + 186, { size: 11.5, family: F.mono, weight: 400, col: C.muted, alpha: 1 - clr });
  if (n === 'reviewer' && t > TL.pass) stamp(x, X + 150, Y + 184, 'PASS', { size: 21, col: C.ok, rot: -.12, k: easeOut(seg(t, TL.pass, TL.pass + .22)), seed: 17 });
}
// the back of a dealt bot card: logbook paper, a band in the bot's colour, the seal
export function drawBotBack(x, i) {
  const [n] = TEAM[i], w = 276, h = 206; x.save(); x.beginPath(); x.roundRect(0, 0, w, h, 14); x.clip();
  x.drawImage(paperTex(w, h, 60 + i, '#EFE9DC'), 0, 0); x.fillStyle = BOT[n]; x.fillRect(0, h - 26, w, 26); x.fillStyle = 'rgba(0,0,0,.12)'; x.fillRect(0, h - 26, w, 2);
  x.strokeStyle = 'rgba(120,100,70,.35)'; x.lineWidth = 1.2; x.setLineDash([4, 4]); x.beginPath(); x.roundRect(10, 10, w - 20, h - 46, 9); x.stroke(); x.setLineDash([]);
  seal(x, w / 2, (h - 26) / 2, 54, { ink: .45, seed: 20 + i }); text(x, 'BOT MODE', w / 2, h - 12.5, { size: 10.5, family: F.mono, weight: 700, col: '#FBF7EE', track: 2.4 });
  x.restore(); rr(x, .5, .5, w - 1, h - 1, 14, null, 'rgba(120,100,70,.4)', 1);
}
export function teamCardsKey(t) { return TEAM.map(([n], i) => landedBot(i, t) ? stateAt(n, t).s + (busyAt(n, t) ? workLine(n, t) : '') : '-').join(',') + q(seg(t, TL.pass - .12, TL.pass + .22), 16); }
export function teamCards(x, t) { TEAM.forEach((_, i) => { if (landedBot(i, t)) { const [X, Y] = teamCard(i); drawBotCard(x, X, Y, i, t); } }); }

// ── the board: five columns, three tasks, every move on the beat ──
export const BCOLS = [['todo', 'To do', C.border2, 'Nothing waiting'], ['in_progress', 'In progress', C.acc, 'Nobody on a task'], ['blocked', 'Blocked', C.warn, 'Nothing blocked'],
  ['failed', 'Failed', C.err, 'No failures'], ['done', 'Done', C.ok, 'Nothing finished yet']];
export const BOARD = { x: 60, y: 488, w: 288, h: 452, gap: 10, cardW: 268, cardH: 120, body: 488 + 52 };
export const colX = i => BOARD.x + i * (BOARD.w + BOARD.gap);
export const TASKS = [
  { n: 1, title: 'Draft report.md', desc: 'From results.json: suites, completion, cost.', who: 'writer', tool: 'write_file', res: { done: 'docs/report.md · 128 lines' },
    moves: [[TL.born(0), 0], [TL.slipLand(0), 1], [TL.done1, 4]] },
  { n: 2, title: 'Check the numbers', desc: 'Recompute completion and cost from the data.', who: 'coder', tool: 'run_python', res: { failed: 'stopped: max_iterations', done: '4 suites match · 0 mismatches' },
    moves: [[TL.born(1), 0], [TL.slipLand(1), 1], [TL.fail2, 3], [TL.redo2 + .3, 1], [TL.done2, 4]] },
  { n: 3, title: 'Review report.md', desc: 'Check report.md against the data.', who: 'reviewer', deps: [1, 2], tool: 'run_shell', res: { done: 'PASS · 0 issues' },
    moves: [[TL.born(2), 0], [TL.take3, 1], [TL.done3, 4]] },
];
export const FLY = .62;   // a move: the card lifts FLY s before it lands
// the column a task is in at t (layout switches at lift, the card's own look at landing)
export function colOf(task, t, { look = false } = {}) { let c = -1; for (const [T0, col] of task.moves) if (t >= (look ? T0 : T0 - FLY)) c = col; return c; }   // −1: not created yet
export function lastMove(task, t) { let m = null; for (const mv of task.moves) if (t >= mv[0] - FLY) m = mv; return m; }
export const inFlight = (task, t) => { const m = lastMove(task, t); return !!m && t < m[0] && t >= m[0] - FLY; };
// slot order: to do / in progress by number; failed / done newest on top
function slotsAt(t) {
  const out = {}; BCOLS.forEach((_, ci) => {
    const here = TASKS.filter(k => colOf(k, t) === ci);
    if (ci >= 3) here.sort((a, b) => (lastMove(b, t)?.[0] ?? 0) - (lastMove(a, t)?.[0] ?? 0)); else here.sort((a, b) => a.n - b.n);
    here.forEach((k, j) => { out[k.n] = [ci, j]; }); });
  return out;
}
const slotXY = ([ci, j]) => [colX(ci) + 10, BOARD.body + j * (BOARD.cardH + 8)];
const LAYOUT_T = [...new Set(TASKS.flatMap(k => k.moves.slice(1).map(m => m[0] - FLY)))].sort((a, b) => a - b);
// where a resting card sits: slides .32 s to its new slot when its column changes around it
export function restXY(task, t) {
  let tc = -1; for (const L of LAYOUT_T) if (L <= t) tc = L;
  const sl = slotsAt(t)[task.n] ?? slotsAt(t + FLY + .01)[task.n] ?? [0, task.n - 1], now = slotXY(sl); if (tc < 0) return now;
  const prev = slotXY(slotsAt(tc - .001)[task.n] ?? sl), k = easeInOut(seg(t, tc, tc + .32));
  return [lerp(prev[0], now[0], k), lerp(prev[1], now[1], k)];
}
const depsMet = (task, t) => (task.deps || []).map(d => colOf(TASKS[d - 1], t, { look: true }) === 4);
// one task card (.kcard), drawn at (X, Y) in UI px
export function drawCard(x, X, Y, task, t) {
  const col = Math.max(0, colOf(task, t, { look: true })), m = lastMove(task, t), landed = m ? t - m[0] : 99, bc = BCOLS[col][2];
  const who = col === 0 ? null : task.who, working = col === 1 && who && busyAt(who, t), w = BOARD.cardW, h = BOARD.cardH;
  const flash = landed >= 0 && landed < 1.6 ? (landed < .48 ? 1 : 1 - (landed - .48) / 1.12) : 0;
  x.save(); x.shadowColor = 'rgba(28,26,22,.08)'; x.shadowBlur = 3; x.shadowOffsetY = 1; rr(x, X, Y, w, h, 6, flash > 0 ? mix(C.sheet, C.accSoft, flash) : C.sheet); x.restore();
  rr(x, X, Y, w, h, 6, null, flash > 0 ? rgba(C.acc, .3 + .7 * flash) : C.border, flash > 0 ? 1 + flash : 1);
  x.save(); x.beginPath(); x.roundRect(X, Y, w, h, 6); x.clip(); x.fillStyle = bc; x.fillRect(X, Y, 3.5, h);
  if (working) { const u = ((t % 1.8) / 1.8), e = u < .5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2, sx = X + lerp(-.4, 1.5, e) * w;   // kc-scan light sweep
    const g = x.createLinearGradient(sx, 0, sx + w * .4, 0); g.addColorStop(0, 'rgba(212,68,28,0)'); g.addColorStop(.5, 'rgba(212,68,28,.9)'); g.addColorStop(1, 'rgba(212,68,28,0)'); x.fillStyle = g; x.fillRect(sx, Y, w * .4, 2.2); }
  x.restore();
  // top row: #n · part of / after · stamp
  let tx = X + 14 + T(x, `#${task.n}`, X + 14, Y + 17, { size: 11, family: F.mono, weight: 600, col: C.text2 }) + 9;
  if (task.deps) { tx += T(x, 'after', tx, Y + 17, { size: 11, family: F.mono, weight: 400, col: C.muted }) + 5; depsMet(task, t).forEach((ok, i) => { tx += T(x, `#${task.deps[i]}${ok ? ' ✓' : ''}`, tx, Y + 17, { size: 11, family: F.mono, weight: 600, col: ok ? C.ok : C.warn }) + 6; }); }
  if (col >= 3) { const sk = easeOut(seg(t, m[0], m[0] + .22)); stamp(x, X + w - 44, Y + 18, col === 4 ? 'DONE' : 'FAILED', { size: 11, col: bc, rot: -5 * Math.PI / 180, k: sk, seed: task.n * 3 + col }); }
  T(x, task.title, X + 14, Y + 42, { size: 17, family: F.serif, weight: 600, col: col === 4 ? C.text2 : C.ink });
  T(x, fit(x, task.desc, w - 28, { size: 11.5, family: F.sans, weight: 400 }), X + 14, Y + 62, { size: 11.5, family: F.sans, weight: 400, col: C.text2 });
  const res = col === 3 ? task.res.failed : col === 4 ? task.res.done : null;
  if (res) { x.fillStyle = bc; x.fillRect(X + 14, Y + 72, 2, 16); T(x, fit(x, res, w - 36, { size: 11, family: F.mono, weight: 500 }), X + 22, Y + 81, { size: 11, family: F.mono, weight: 500, col: col === 3 ? C.err : C.text2 }); }
  hline(x, X + 12, X + w - 12, Y + 93, C.border, 1, [3, 3]);
  if (who) avatar(x, X + 14, Y + 98, 18, who, t, { ring: working, gap: C.sheet });
  else rr(x, X + 14, Y + 98, 18, 18, 5, null, C.border2, 1);
  const hw = T(x, who ? '@' + who : 'unassigned', X + 40, Y + 107.5, { size: 11, family: F.mono, weight: 500, col: C.text2 });
  if (working) T(x, workLine(who, t, task.tool), X + 48 + hw, Y + 107.5, { size: 11, family: F.mono, weight: 500, col: C.accInk });
  text(x, landed < 60 ? 'now' : '1m', X + w - 12, Y + 107.5, { size: 11, family: F.mono, weight: 400, col: C.muted, align: 'right' });
}
// clamp one line to a width with an ellipsis (the app clamps previews with CSS)
function fit(x, s, w, o) { if (M(x, s, o) <= w) return s; let n = s.length; while (n > 1 && M(x, s.slice(0, n) + '…', o) > w) n--; return s.slice(0, n).trimEnd() + '…'; }
const boardTq = t => t < TL.born(0) - FLY - .1 ? 'pre' : t > TL.done3 + 2 && t < TL.s7 ? 'post' : f30(t);
export function boardKey(t) {
  const tq = boardTq(t); if (tq === 'pre' || tq === 'post') return tq + TASKS.map(k => colOf(k, t)).join('');
  return tq + ':' + TASKS.map(k => k.who + faceKey(k.who, t)).join(';');
}
export function boardDyn(x, t0) {
  const tq = boardTq(t0), t = typeof tq === 'number' ? tq : t0;
  // columns' bodies and counts
  BCOLS.forEach(([, , , empty], i) => { const X = colX(i);
    const n = TASKS.filter(k => colOf(k, t, { look: true }) === i).length; text(x, String(n), X + BOARD.w - 14, BOARD.y + 23, { size: 12, family: F.mono, weight: 600, col: C.muted, align: 'right' });
    if (!TASKS.some(k => colOf(k, t) === i)) { x.save(); x.setLineDash([4, 3]); rr(x, X + 10, BOARD.body, BOARD.cardW, 46, 6, null, C.border, 1); x.restore();
      text(x, empty, X + BOARD.w / 2, BOARD.body + 23, { size: 11.5, family: F.mono, weight: 400, col: C.muted }); } });
  // the cards at rest (a card in flight is the 3D object in world.js)
  TASKS.forEach(k => { if (inFlight(k, t) || colOf(k, t) < 0) return; const [X, Y] = restXY(k, t); drawCard(x, X, Y, k, t); });
  // the strip: "n/3 done", the segmented bar, who is working, the Chat | Board switch, read-only · live
  const cnt = [0, 0, 0, 0, 0]; TASKS.forEach(k => { const c0 = colOf(k, t, { look: true }); if (c0 >= 0) cnt[c0]++; });
  if (!TASKS.some(k => colOf(k, t, { look: true }) >= 0)) { T(x, 'No tasks yet. When @lead breaks a goal down, its subtasks appear here and move across as the team works.', 250, 469.5, { size: 12.5, family: F.mono, weight: 400, col: C.muted }); return; }
  const dw = T(x, `${cnt[4]}/3`, 250, 469, { size: 21, family: F.serif, weight: 600, col: C.ink }); T(x, 'done', 256 + dw, 471, { size: 12, family: F.mono, weight: 400, col: C.muted });
  { const X0 = 350, Wb = 420; rr(x, X0, 466, Wb, 7, 3.5, C.bg3); const segs = [[cnt[4], C.ok], [cnt[3], C.err], [cnt[2], C.warn], [cnt[1], C.acc], [cnt[0], C.border2]].filter(s => s[0] > 0);
    let sx = X0; const tot = segs.reduce((a, s) => a + s[0], 0); segs.forEach(([v, col], i) => { const sw = (Wb - 2 * (segs.length - 1)) * v / tot; rr(x, sx, 466, sw, 7, 3.5, col); sx += sw + 2; }); }
  const working = TASKS.map(k => k.who).filter((w, i) => colOf(TASKS[i], t, { look: true }) === 1 && busyAt(w, t));
  let wx = 800; working.forEach(w => { avatar(x, wx, 460, 18, w, t, { ring: true, gap: C.bg }); wx += 14; });
  if (working.length) T(x, `${working.length} working`, wx + 12, 469.5, { size: 12, family: F.mono, weight: 500, col: C.accInk });
  // Chat | Board (.seg.view-seg), Board on, with the count of unfinished tasks
  { const nf = cnt[0] + cnt[1] + cnt[2], X1 = 1196, w1 = 52, w2 = 76; rr(x, X1, 455, w1 + w2 + 6, 28, 8, C.bg, C.border2);
    rr(x, X1 + 3 + w1, 458, w2, 22, 6, C.sheet, C.border2); T(x, 'Chat', X1 + 13, 469.5, { size: 12.5, family: F.sans, weight: 500, col: C.text2 });
    const bw = T(x, 'Board', X1 + w1 + 14, 469.5, { size: 12.5, family: F.sans, weight: 600, col: C.ink }); if (nf) T(x, String(nf), X1 + w1 + 20 + bw, 470, { size: 10.5, family: F.mono, weight: 600, col: C.accInk }); }
  text(x, 'READ-ONLY · LIVE', 1540, 469.5, { size: 10.5, family: F.mono, weight: 600, col: C.muted, align: 'right', track: .7 });
}

// ───────────────────────── page 3: Sandbox ─────────────────────────
export const BOX = [60, 250, 1000, 670];    // the walled workspace (x, y, w, h); the wall itself is 3D (world.js)
const LOG = [['✓', 'read_file', 'docs/eval_results/final/results.json', 'DONE'], ['✓', 'write_file', 'docs/report.md  ·  +128 lines', 'DONE'], ['◐', 'run_shell', 'pytest -q', 'RUN'],
  ['', '', '', 'DOTS'], ['✓', 'git_commit', '“Add evaluation report”', 'DONE'], ['⏸', 'git_push', 'origin main', 'ASK']];
function sandBase(x) {
  chrome(x, '03', 'SANDBOX', 'Real code, fenced in.', '真的執行，但關在沙箱裡。', 'Seatbelt · your home folder is off limits, except the workspace', 41);
  const [X, Y, w, h] = BOX; rr(x, X, Y, w, h, 18, '#F8F6F0');
  const g = x.createLinearGradient(0, Y, 0, Y + 40); g.addColorStop(0, 'rgba(60,45,30,.16)'); g.addColorStop(1, 'rgba(60,45,30,0)'); x.fillStyle = g; x.fillRect(X + 10, Y + 10, w - 20, 40);   // the wall's own shade
  const g2 = x.createLinearGradient(X, 0, X + 40, 0); g2.addColorStop(0, 'rgba(60,45,30,.12)'); g2.addColorStop(1, 'rgba(60,45,30,0)'); x.fillStyle = g2; x.fillRect(X + 10, Y + 10, 40, h - 20);
  T(x, '~/nlp_final_pland', X + 40, Y + 52, { size: 14, family: F.mono, weight: 600, col: C.text2 }); T(x, 'workspace', X + 220, Y + 52, { size: 14, family: F.mono, weight: 400, col: C.muted });
  // outside the wall
  T(x, 'OUTSIDE THE SANDBOX', 1112, 640, { size: 12, family: F.mono, weight: 600, col: C.muted, track: 1.2 });
  [['~/.ssh/id_rsa', 'lock', 700], ['~/Documents', 'folder', 790], ['~/Library/Keychains', 'lock', 880]].forEach(([s, ic, y]) => { rr(x, 1112, y - 30, 428, 60, 10, C.bg2, C.border, 1); icon(x, ic, 1146, y, 20, C.muted, 1.6); T(x, s, 1172, y + 1, { size: 17, family: F.mono, weight: 500, col: C.text2 }); });
  rr(x, 1112, 226, 428, 370, 16, C.sheet, C.border);
  T(x, 'RUN BUDGET', 1140, 258, { size: 13, family: F.mono, weight: 600, col: C.ink, track: 1.4 });
}
const testK = t => clamp((t - TL.testsA) / (TL.testsPass - TL.testsA));
export function sandDynKey(t) { return [LOG.map((_, i) => q(seg(t, TL.logRow(i) - .2, TL.logRow(i) + .25), 10)).join(''), Math.floor(testK(t) * 46), t > TL.pushAsk ? Math.floor(t * 6) % 2 : 0, q(clamp((t - TL.s5) / 5.4), 30)].join(':'); }
export function sandDyn(x, t) {
  const [X, Y] = BOX; x.fillStyle = '#F8F6F0'; x.fillRect(X + 30, Y + 80, 960, 600); x.fillStyle = C.sheet; x.fillRect(1122, 280, 408, 300);
  LOG.forEach(([m, name, arg, st], i) => {
    const show = i === 3 ? seg(t, TL.testsA, TL.testsA + .3) : seg(t, TL.logRow(i) - .2, TL.logRow(i) + .25); if (show <= 0) return;
    const y = Y + 122 + i * 88, k = easeOut(show); x.save(); x.globalAlpha = k; x.translate(0, (1 - k) * 14);
    if (st === 'DOTS') { const n = Math.floor(testK(t) * 46); let dx = X + 100;   // pytest's progress line: two of the 190 are skipped ("s")
      for (let j = 0; j < n; j++) { const sk = j === 17 || j === 29; dx += T(x, sk ? 's' : '.', dx, y - 10, { size: 22, family: F.mono, weight: 700, col: sk ? C.warn : C.ok }) + 1; }
      if (t >= TL.testsPass) { const pw = T(x, '188 passed', X + 100, y + 22, { size: 22, family: F.mono, weight: 700, col: C.ok }); const sw = T(x, ', 2 skipped', X + 100 + pw, y + 22, { size: 22, family: F.mono, weight: 700, col: C.warn });
        T(x, ' in 13.46s', X + 100 + pw + sw, y + 22, { size: 22, family: F.mono, weight: 400, col: C.muted }); }
      x.restore(); return; }
    const running = st === 'RUN' && t < TL.testsPass, ask = st === 'ASK';
    rr(x, X + 40, y - 34, 920, 68, 12, ask ? C.warnSoft : C.sheet, ask ? '#D9B36A' : C.border);
    const mm = running ? '◐◓◑◒'[Math.floor(t * 8) % 4] : st === 'RUN' ? '✓' : m;
    T(x, mm, X + 64, y + 1, { size: 22, family: F.mono, weight: 700, col: ask ? C.warn : running ? C.acc : C.ok });
    const nw = T(x, name, X + 100, y + 1, { size: 20, family: F.mono, weight: 700, col: C.ink }); T(x, arg, X + 116 + nw, y + 1, { size: 19, family: F.mono, weight: 400, col: C.text2 });
    const lab = ask ? 'NEEDS YOU' : running ? 'RUNNING' : 'DONE', lw = M(x, lab, { size: 14, family: F.mono, weight: 700, track: 1 });
    if (!ask || Math.floor(t * 6) % 2 === 0 || t < TL.pushAsk) T(x, lab, X + 936 - lw, y + 1, { size: 14, family: F.mono, weight: 700, col: ask ? C.warn : running ? C.acc : C.ok, track: 1 });
    x.restore();
  });
  const r = clamp((t - TL.s5) / 5.4), calls = Math.round(lerp(152, 171, r)), tok = lerp(3.1, 3.55, r), steps = Math.round(lerp(21, 29, r));
  [['model calls', calls / 600, `${calls} / 600`], ['weighted tokens', tok / 16, `${tok.toFixed(2)}M / 16M`], ['steps · lead', steps / 80, `${steps} / 80`]].forEach(([lab, v, s], i) => {
    const y = 314 + i * 70; T(x, lab, 1140, y, { size: 16, family: F.sans, weight: 500, col: C.text2 }); text(x, s, 1512, y, { size: 15, family: F.mono, weight: 600, col: C.ink, align: 'right' }); bar(x, 1140, y + 22, 372, 8, Math.max(.02, v), i === 0 ? C.acc : C.ink); });
  let cx = 1140; [['loop guard', 'ok'], ['danger check', 'on']].forEach(([a, b]) => { cx += chip(x, cx, 538, `${a} · ${b}`, { size: 12.5, h: 30, col: C.ok, border: '#B9D3BE', bg: C.okSoft }) + 10; });
}

// ───────────────────────── page 4: Memory ─────────────────────────
export const EXP = [['Results live in docs/eval_results/<set>/', 'files · eval', 2], ['Writer only writes .md and .txt', 'team · writer', 5], ['Ask before git push, every time', 'git · approval', 7]];
function memBase(x) {
  chrome(x, '04', 'MEMORY', 'It remembers what worked.', '做對的事，記成經驗。', 'per bot · notes · experience · skills', 51);
  rr(x, 60, 226, 450, 694, 16, C.sheet, C.border);
  T(x, 'NOTES', 92, 258, { size: 13, family: F.mono, weight: 600, col: C.ink, track: 1.4 }); text(x, '1,284 / 2,000', 478, 258, { size: 12, family: F.mono, weight: 500, col: C.muted, align: 'right' }); bar(x, 92, 280, 386, 6, .64, C.ink);
  ['User wants reports under docs/', 'Repo: victoryuanxichen/nlp_final_pland', 'Models: DeepSeek or HKGAI only', 'Formal docs in Traditional Chinese', 'Eval sets: dev · midterm · final · hard', 'Commit at milestones, push to main'].forEach((s, i) => {
    const y = 336 + i * 80; x.fillStyle = C.acc; x.fillRect(92, y - 4, 6, 6); wrap(x, s, 340, { size: 19, family: F.sans, weight: 500 }).forEach((l, j) => T(x, l, 114, y + j * 25, { size: 19, family: F.sans, weight: 500, col: C.ink })); hline(x, 92, 478, y + 44, C.border, 1, [3, 4]); });
  rr(x, 540, 226, 560, 694, 16, C.bg2, C.border);
  T(x, 'EXPERIENCE', 572, 258, { size: 13, family: F.mono, weight: 600, col: C.ink, track: 1.4 }); T(x, 'reflected after each task', 708, 258, { size: 12, family: F.mono, weight: 400, col: C.muted });
  rr(x, 1130, 226, 410, 694, 16, C.sheet, C.border);
  T(x, 'MEMORY ON / OFF', 1162, 258, { size: 13, family: F.mono, weight: 600, col: C.ink, track: 1.4 }); T(x, 'memory_evolution · real eval run', 1162, 284, { size: 12, family: F.mono, weight: 400, col: C.muted });
  hline(x, 1162, 1508, 820, C.border2, 1.5); T(x, 'task completion rate', 1162, 880, { size: 13, family: F.mono, weight: 400, col: C.muted }); T(x, 'docs/EVALUATION_REPORT.md', 1162, 902, { size: 12, family: F.mono, weight: 400, col: C.muted });
}
export const expCard = (i, X = 572) => [X, 300 + i * 150, 496, 128];
export function memDynKey(t) { return [q(seg(t, TL.lessonLand - .5, TL.lessonLand + .5), 40), q(seg(t, TL.barsA, TL.barsA + 1.2), 40)].join(':'); }
export function memDyn(x, t) {
  x.fillStyle = C.bg2; x.fillRect(552, 290, 536, 620); x.fillStyle = C.sheet; x.fillRect(1142, 300, 386, 516);
  const shift = easeInOut(seg(t, TL.lessonLand - .5, TL.lessonLand - .05));
  if (shift > 0) { const [X, Y, w, h] = expCard(0); rr(x, X, Y, w, h, 12, null, rgba(C.acc, .5 * (1 - seg(t, TL.lessonLand + .3, TL.lessonLand + .6))), 2); }
  EXP.forEach(([a, tags, v], i) => { const [X, Y, w, h] = expCard(i + shift); if (Y + h > 905) { x.save(); x.globalAlpha = clamp((905 - Y) / 60); expCardDraw(x, X, Y, w, h, a, tags, v, false); x.restore(); } else expCardDraw(x, X, Y, w, h, a, tags, v, false); });
  if (t > TL.lessonLand + .02) expCardDraw(x, ...expCard(0), 'Push only after the tests pass', 'git · testing', 1, true);
  const k = easeOut(seg(t, TL.barsA, TL.barsA + 1.2));
  [['memory on', 1, C.acc, '100%'], ['memory off', .333, '#B4AC9C', '33.3%']].forEach(([lab, v, col, s], i) => { const X = 1176 + i * 176, h = 420 * v * k;
    rr(x, X, 820 - h, 128, h, 6, col); text(x, s, X + 64, 820 - h - 34, { size: 40, family: F.serif, weight: 600, col: i ? C.muted : C.ink, alpha: clamp(k * 3) });
    text(x, lab, X + 64, 846, { size: 13, family: F.mono, weight: 600, col: C.text2 }); });
}
export function expCardDraw(x, X, Y, w, h, title, tags, v, fresh) {
  x.save(); x.shadowColor = 'rgba(28,26,22,.07)'; x.shadowBlur = 10; x.shadowOffsetY = 3; rr(x, X, Y, w, h, 12, C.sheet); x.restore(); rr(x, X, Y, w, h, 12, null, fresh ? C.acc : C.border, fresh ? 1.6 : 1);
  T(x, fresh ? 'NEW · LESSON' : 'LESSON', X + 22, Y + 30, { size: 11, family: F.mono, weight: 600, col: fresh ? C.acc : C.muted, track: 1.2 });
  T(x, title, X + 22, Y + 64, { size: 21, family: F.sans, weight: 600, col: C.ink });
  T(x, tags, X + 22, Y + 100, { size: 13, family: F.mono, weight: 400, col: C.muted });
  const s = `verified ×${v}`; chip(x, X + w - 20, Y + 98, s, { size: 12, align: 'right', h: 26, col: C.ok, bg: C.okSoft, border: '#B9D3BE' });
}

// index tabs on the right edge: they peek out from under the window long before the deck opens
export const TABS = [['00', 'CHAT', C.ink], ['01', 'PLAN', BOT.lead], ['02', 'TEAM', BOT.researcher], ['03', 'SANDBOX', BOT.coder], ['04', 'MEMORY', BOT.writer]];
export const TAB = { w: 66, h: 148, y: i => 132 + i * 158, tuck: 18 };
export function paintTab(x, i) {
  const [n, s, col] = TABS[i], { w, h } = TAB;
  const g = x.createLinearGradient(0, 0, w, 0); g.addColorStop(0, col); g.addColorStop(1, mix(col, '#000000', .12));
  x.fillStyle = g; x.beginPath(); x.roundRect(0, 0, w, h, [0, 12, 12, 0]); x.fill();
  x.strokeStyle = 'rgba(255,255,255,.18)'; x.lineWidth = 1.5; x.beginPath(); x.moveTo(TAB.tuck + 4, 1.5); x.lineTo(w - 12, 1.5); x.stroke();
  x.save(); x.translate(TAB.tuck + (w - TAB.tuck) / 2 + 1, h / 2); x.rotate(Math.PI / 2);
  text(x, `${n}  ${s}`, 0, 0, { size: 14, family: F.mono, weight: 700, col: '#FBF7EE', track: 2 }); x.restore();
}

// ───────────────────────── page list ─────────────────────────
const leadIn = t => easeOut(seg(t, TL.lead, TL.lead + .4));
export const PAGES = [
  { id: 'chat', sheets: [{ rect: [0, 0, PW, PH], S: 2, paint: chatBase, full: true }, { rect: [272, 98, 1328, 690], S: 2, key: chatMsgsKey, paint: chatMsgs },
    { rect: [272, 788, 1328, 190], S: 3, key: chatCompKey, paint: chatComp }, { rect: [0, 892, 1336, 100], S: 2.5, key: chatThreadKey, paint: chatThread },
    ...['lead', 'researcher', 'coder', 'reviewer'].map((n, i) => faceSheet(n, 296 + i * 22, 46, 30, { gap: C.bg })),   // header stack: live
    { rect: [0, 180, 272, 380], S: 2.5, key: sideKey, paint: sidePaint },
    faceSheet('lead', COLX, 200, 30, { from: TL.lead, fade: leadIn, gap: C.bg })] },              // lead's streaming reply: live until the run ends
  { id: 'plan', sheets: [{ rect: [0, 0, PW, PH], S: 1.75, paint: planBase, full: true }, { rect: [60, 222, 1480, 700], S: 1.75, key: planDynKey, paint: planDyn }] },
  { id: 'team', sheets: [{ rect: [0, 0, PW, PH], S: 2, paint: teamBase, full: true }, { rect: [56, 214, 1488, 222], S: 2.2, key: teamCardsKey, paint: teamCards },
    { rect: [60, 450, 1480, 492], S: 2.2, key: boardKey, paint: boardDyn },
    ...TEAM.map(([n], i) => { const [fx, fy] = faceXY(i); return faceSheet(n, fx, fy, FACE_S, { ring: true, gap: C.sheet, from: TL.roll(i) }); })] },
  { id: 'sandbox', sheets: [{ rect: [0, 0, PW, PH], S: 1.75, paint: sandBase, full: true }, { rect: [60, 226, 1480, 694], S: 1.75, key: sandDynKey, paint: sandDyn }] },
  { id: 'memory', sheets: [{ rect: [0, 0, PW, PH], S: 1.75, paint: memBase, full: true }, { rect: [540, 226, 1000, 694], S: 1.75, key: memDynKey, paint: memDyn }] },
];

// ───────────────────────── flying cards ─────────────────────────
function slip(i) {
  const [task, who] = [['Draft report.md', 'writer'], ['Check the numbers', 'coder'], ['Review report.md', 'reviewer']][i];
  return { w: 300, h: 92, S: 3, key: t => faceKey(who, t), paint: (x, t) => { rr(x, 0, 0, 300, 92, 10, C.sheet); rr(x, 0, 0, 300, 92, 10, null, C.border2); rr(x, 0, 0, 6, 92, 3, C.acc);
    T(x, 'TASK', 22, 24, { size: 11, family: F.mono, weight: 600, col: C.acc, track: 1.2 }); text(x, `#${i + 1}`, 278, 24, { size: 11, family: F.mono, weight: 600, col: C.muted, align: 'right' });
    T(x, task, 22, 52, { size: 20, family: F.sans, weight: 600, col: C.ink });
    avatar(x, 22, 63, 20, who, t, { gap: C.sheet }); T(x, `→ @${who}`, 50, 74, { size: 12, family: F.mono, weight: 500, col: C.text2 }); } };
}
// the thinking-intensity menu (.pick-menu), as the app lists it for each provider. Help texts verbatim; line breaks are ours.
const MENU = {
  ds: { sel: 'High', items: [['Off', ['No thinking: fastest and cheapest']], ['Default', ['Thinking at DeepSeek’s default depth', '(what the evaluation used)']], ['Low', ['Short reasoning']],
    ['Medium', ['Moderate reasoning']], ['High', ['Thorough reasoning']], ['Max', ['Deepest: about twice the', 'thinking of High']]] },
  hk: { sel: 'High', fresh: ['Minimal', 'Extra high'], items: [['Off', ['No thinking: fastest and cheapest']], ['Default', ['Medium (HKGAI thinks only', 'when asked)']], ['Minimal', ['The shortest reasoning']],
    ['Low', ['Short reasoning']], ['Medium', ['Moderate reasoning']], ['High', ['Thorough reasoning']], ['Extra high', ['More thorough than High']], ['Max', ['Deepest reasoning']]] },
};
const rowH = it => it[1].length > 1 ? 44 : 30, MW = 360;
const menuH = m => 5 + 28 + m.items.reduce((a, it) => a + rowH(it), 0) + 8;
export const MENU_ROWS = {};   // y of each row (for the highlighter in shots.js)
function menuCard(id) {
  const m = MENU[id], h = menuH(m);
  return { w: MW, h, S: 3, key: t => id === 'hk' ? q(seg(t, TL.hkNew, TL.hkNew + .7), 20) : '', paint: (x, t) => {
    rr(x, 0, 0, MW, h, 10, C.sheet); rr(x, .5, .5, MW - 1, h - 1, 10, null, C.border2, 1);
    T(x, id === 'ds' ? 'THINKING · @LEAD · DEEPSEEK' : 'THINKING · @LEAD · HKGAI', 13, 21, { size: 10, family: F.mono, weight: 600, col: C.muted, track: .8 });
    let y = 33; MENU_ROWS[id] = {};
    m.items.forEach(it => { const [name, help] = it, rh = rowH(it), sel = name === m.sel, cy = y + 15;
      MENU_ROWS[id][name] = [y, rh];
      if (m.fresh && m.fresh.includes(name)) {   // the film's highlighter: the two levels HKGAI added (not part of the app's UI)
        const k = easeOut(seg(t, TL.hkNew + (name === 'Minimal' ? 0 : .22), TL.hkNew + (name === 'Minimal' ? .45 : .67)));
        if (k > 0) { x.fillStyle = rgba('#F2B84B', .32); x.beginPath(); x.roundRect(6, y + 3, (MW - 12) * k, rh - 6, 6); x.fill(); } }
      if (sel) T(x, '✓', 13, cy, { size: 12, family: F.sans, weight: 600, col: C.acc });
      T(x, name, 31, cy + .5, { size: 13, family: F.sans, weight: sel ? 600 : 500, col: sel ? C.accInk : C.ink });
      help.forEach((l, j) => T(x, l, 116, cy + .5 + j * 15, { size: 11.5, family: F.sans, weight: 400, col: C.muted }));
      y += rh; });

  } };
}
// one board card in flight (the same drawing as at rest)
const flyCard = n => ({ w: BOARD.cardW, h: BOARD.cardH, S: 3, key: t => { const m = lastMove(TASKS[n - 1], t); return `${colOf(TASKS[n - 1], t, { look: true })}:${m ? q(seg(t, m[0] - .18, m[0] + 1.6), 24) : 0}:${faceKey(TASKS[n - 1].who, t)}`; },
  paint: (x, t) => { const tk = TASKS[n - 1], m = lastMove(tk, t), T1 = m ? m[0] : 0, k = m ? seg(t, T1 - .18, T1) : 0;
    if (k <= 0 || t >= T1) { drawCard(x, 0, 0, tk, t); return; } drawCard(x, 0, 0, tk, T1 - .19); x.save(); x.globalAlpha = k; drawCard(x, 0, 0, tk, T1 + .001); x.restore(); } });
export const CARDS = {
  slip0: slip(0), slip1: slip(1), slip2: slip(2),
  file: { w: 300, h: 92, S: 3, paint: x => { rr(x, 0, 0, 300, 92, 10, C.sheet); rr(x, 0, 0, 300, 92, 10, null, C.border2); rr(x, 0, 0, 6, 92, 3, C.ok); icon(x, 'file', 34, 46, 30, C.ink, 2);
    T(x, 'report.md', 62, 38, { size: 21, family: F.mono, weight: 700, col: C.ink }); T(x, 'inbox/from-writer/', 62, 64, { size: 12.5, family: F.mono, weight: 400, col: C.muted }); } },
  ...Object.fromEntries(TEAM.map(([n], i) => ['bot' + i, { w: 276, h: 206, S: 2.5, key: t => faceKey(n, t), paint: (x, t) => drawBotCard(x, 0, 0, i, t, { withFace: true }), back: x => drawBotBack(x, i) }])),
  k1: flyCard(1), k2: flyCard(2), k3: flyCard(3),
  menuDS: menuCard('ds'), menuHK: menuCard('hk'),
  rogue: { w: 440, h: 64, S: 3, key: t => t > TL.rogueHit ? 'hit' + q(seg(t, TL.rogueHit, TL.rogueHit + .3), 10) : 'go', paint: (x, t) => { const hit = t > TL.rogueHit;
    rr(x, 0, 0, 440, 64, 10, hit ? C.errSoft : C.sheet); rr(x, 0, 0, 440, 64, 10, null, hit ? C.err : C.border2, 1.6); icon(x, 'term', 28, 32, 22, hit ? C.err : C.ink, 1.8);
    T(x, 'cat ~/.ssh/id_rsa', 52, 33, { size: 21, family: F.mono, weight: 700, col: hit ? C.err : C.ink });
    if (hit) stamp(x, 368, 31, 'DENIED', { size: 20, col: C.err, rot: -.12, k: easeOut(seg(t, TL.rogueHit, TL.rogueHit + .25)), seed: 4 }); } },
  // the permission card (.hitl-card): face · Team Lead · @lead · needs your permission · Approval; question; detail; actions
  approval: { w: 620, h: 252, S: 3, key: t => [q(seg(t, TL.click - .1, TL.click + .1), 10), q(seg(t, TL.click, TL.click + .3), 15), faceKey('lead', t)].join(':'), paint: (x, t) => {
    x.save(); x.shadowColor = 'rgba(28,26,22,.15)'; x.shadowBlur = 22; x.shadowOffsetY = 8; rr(x, 0, 0, 620, 252, 10, C.sheet); x.restore();
    rr(x, 0, 0, 620, 252, 10, null, C.border2); x.fillStyle = C.warn; x.beginPath(); x.roundRect(0, 0, 620, 5, [10, 10, 0, 0]); x.fill();
    avatar(x, 26, 22, 36, 'lead', t, { gap: C.sheet });
    let hx = 74 + T(x, 'Team Lead', 74, 41, { size: 16, family: F.sans, weight: 700, col: C.ink }) + 8;
    hx += T(x, '@lead', hx, 41.5, { size: 13, family: F.mono, weight: 400, col: C.muted }) + 10; T(x, 'needs your permission', hx, 41.5, { size: 13.5, family: F.sans, weight: 400, col: C.text2 });
    chip(x, 592, 40, 'Approval', { size: 11.5, align: 'right', h: 24, col: C.warn, bg: C.warnSoft, border: '#D9B36A', family: F.sans, weight: 600 });
    T(x, 'Push 3 commits to origin/main?', 26, 96, { size: 25, family: F.serif, weight: 600, col: C.ink });
    rr(x, 26, 118, 568, 42, 8, C.code); T(x, '$ git push origin main', 42, 139.5, { size: 16, family: F.mono, weight: 500, col: C.ink });
    const press = seg(t, TL.click - .1, TL.click) * (1 - seg(t, TL.click + .05, TL.click + .25));
    let bx = 26; [['Allow once', true], ['This session', false], ['Always', false]].forEach(([s, main], i) => {
      const w = M(x, s, { size: 15, family: F.sans, weight: 600 }) + 34; x.save(); if (i === 0) { x.translate(bx + w / 2, 202); x.scale(1 - press * .06, 1 - press * .06); x.translate(-(bx + w / 2), -202); }
      rr(x, bx, 182, w, 40, 8, main ? C.ink : C.sheet, main ? null : C.border2); T(x, s, bx + 17, 202.5, { size: 15, family: F.sans, weight: 600, col: main ? '#F7F4EC' : C.ink }); x.restore(); bx += w + 10; });
    T(x, 'Deny', 534, 202.5, { size: 15, family: F.sans, weight: 600, col: C.err });
    stamp(x, 470, 104, 'ALLOWED', { size: 34, col: C.acc, rot: -.16, k: easeOut(seg(t, TL.click, TL.click + .22)), seed: 8, sub: 'ONCE · BY YOU' }); } },
  // S6b: a page from another site tries to drive the local server; the guard answers 403
  foreign: { w: 480, h: 190, S: 3, key: t => t > TL.fHit ? 'hit' + q(seg(t, TL.fHit, TL.fHit + .9), 18) : 'go', paint: (x, t) => { const hit = t > TL.fHit, hk = easeOut(seg(t, TL.fHit, TL.fHit + .22));
    rr(x, 0, 0, 480, 190, 10, '#F2F2EE'); rr(x, .5, .5, 479, 189, 10, null, hit ? rgba(C.err, .5 + .5 * hk) : '#B9B6AE', 1.4);
    x.fillStyle = '#DEDDD7'; x.beginPath(); x.roundRect(0, 0, 480, 38, [10, 10, 0, 0]); x.fill(); hline(x, 0, 480, 38, '#C6C4BC');
    ['#C9C6BE', '#C9C6BE', '#C9C6BE'].forEach((c, i) => { x.fillStyle = c; x.beginPath(); x.arc(20 + i * 18, 19, 5.5, 0, TAU); x.fill(); });
    rr(x, 86, 9, 300, 20, 10, '#F4F3EF'); T(x, 'https://evil.example', 100, 19.5, { size: 12, family: F.mono, weight: 500, col: '#5E5B53' });
    T(x, 'POST', 22, 74, { size: 15, family: F.mono, weight: 700, col: '#3A3832' }); T(x, '127.0.0.1:8765/api/…/uploads', 72, 74, { size: 15, family: F.mono, weight: 500, col: '#3A3832' });
    T(x, 'Origin: https://evil.example', 22, 104, { size: 14, family: F.mono, weight: 400, col: '#77746B' });
    if (hit) { x.save(); x.globalAlpha = clamp(seg(t, TL.fHit + .15, TL.fHit + .5) * 1.2); rr(x, 14, 128, 452, 44, 8, C.errSoft);
      T(x, 'refused: the request came from another web page', 26, 150.5, { size: 13.5, family: F.mono, weight: 600, col: C.err }); x.restore();
      stamp(x, 392, 84, '403', { size: 40, col: C.err, rot: -.14, k: hk, seed: 12 }); } } },
  lesson: { w: 496, h: 128, S: 3, paint: x => expCardDraw(x, 0, 0, 496, 128, 'Push only after the tests pass', 'git · testing', 1, true) },
};
