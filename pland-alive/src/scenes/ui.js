// ui.js — PlanD's "logbook" design language as canvas helpers (all sizes in UI px; the caller pre-scales the context).
// Colours, radii and type roles follow pland/server/static/style.css: warm paper, ink, a serif for names and titles,
// mono for the machine's own words, one vermilion stamp accent.
import { TAU, clamp, lerp, hash, rng, noise3, mk, text, measure, rgba, mix } from '../engine.js';
import { faceAt, drawFace, busyAt, ringPulse } from './faces.js';

export const C = {
  bg: '#F4F1E9', bg2: '#EFEBE1', bg3: '#E6E1D4', sheet: '#FBFAF6', side: '#ECE8DD', panel: '#EFEBE1',
  border: '#DDD7C9', border2: '#C9C2B2', ink: '#1C1A16', text2: '#4D493F', muted: '#878173',
  acc: '#D4441C', accInk: '#AC3612', accSoft: '#F6DED3', user: '#E5DFD0', ok: '#2D7A4C', okSoft: '#DCEBDC',
  err: '#B3261E', errSoft: '#F4DAD5', warn: '#9C5D00', warnSoft: '#F3E4C3', code: '#EBE6DA',
};
// the shipped team template's colours (pland/team_templates/requirements-team.yaml)
export const BOT = { lead: '#C8462A', researcher: '#2B7A78', coder: '#33508C', reviewer: '#7A3E6A', writer: '#4E7A4A' };
export const F = { serif: 'Newsreader', sans: 'Inter', mono: 'JetBrains Mono', tc: 'Noto Sans TC', tcs: 'Noto Serif TC' };

export function rr(x, X, Y, w, h, r, fill, stroke, lw = 1) {
  x.beginPath(); x.roundRect(X, Y, w, h, r);
  if (fill) { x.fillStyle = fill; x.fill(); }
  if (stroke) { x.strokeStyle = stroke; x.lineWidth = lw; x.stroke(); }
}
export const T = (x, s, X, Y, o) => text(x, s, X, Y, { align: 'left', ...o });
export const M = (x, s, o) => measure(x, s, o);
export function hline(x, X0, X1, Y, col = C.border, lw = 1, dash = null) {
  x.save(); x.strokeStyle = col; x.lineWidth = lw; if (dash) x.setLineDash(dash); x.beginPath(); x.moveTo(X0, Y); x.lineTo(X1, Y); x.stroke(); x.restore();
}
export function vline(x, X, Y0, Y1, col = C.border, lw = 1) { x.save(); x.strokeStyle = col; x.lineWidth = lw; x.beginPath(); x.moveTo(X, Y0); x.lineTo(X, Y1); x.stroke(); x.restore(); }

// paper: warm base, a soft lamp falloff from the upper left, fine grain and a few fibres. Cached per size/seed.
export function paperTex(w, h, seed = 1, tone = C.bg) {
  const key = `${w}x${h}:${seed}:${tone}`;
  if (paperTex.c[key]) return paperTex.c[key];
  const cv = mk(w, h), x = cv.getContext('2d'), r = rng(seed);
  x.fillStyle = tone; x.fillRect(0, 0, w, h);
  const g = x.createRadialGradient(w * .18, h * .1, 0, w * .4, h * .4, Math.hypot(w, h) * .85);
  g.addColorStop(0, 'rgba(255,253,246,.55)'); g.addColorStop(.55, 'rgba(255,253,246,0)'); g.addColorStop(1, 'rgba(120,100,70,.10)');
  x.fillStyle = g; x.fillRect(0, 0, w, h);
  const s = 2, gw = Math.ceil(w / s), gh = Math.ceil(h / s), im = x.createImageData(gw, gh);
  for (let j = 0; j < gh; j++) for (let i = 0; i < gw; i++) {
    const v = noise3(i * .09, j * .09, seed) * .35 + (r() - .5) * .8, k = (j * gw + i) * 4;
    im.data[k] = im.data[k + 1] = im.data[k + 2] = v > 0 ? 255 : 90; im.data[k + 3] = Math.abs(v) * (v > 0 ? 7 : 10);
  }
  const t = mk(gw, gh); t.getContext('2d').putImageData(im, 0, 0); x.drawImage(t, 0, 0, w, h);
  x.lineCap = 'round';
  for (let i = 0; i < w * h / 9000; i++) { const px = r() * w, py = r() * h, a = r() * TAU, L = 5 + r() * 18;
    x.strokeStyle = r() < .5 ? 'rgba(90,70,40,.06)' : 'rgba(255,255,255,.35)'; x.lineWidth = .5 + r() * .7;
    x.beginPath(); x.moveTo(px, py); x.quadraticCurveTo(px + Math.cos(a + .6) * L * .5, py + Math.sin(a + .6) * L * .5, px + Math.cos(a) * L, py + Math.sin(a) * L); x.stroke(); }
  return (paperTex.c[key] = cv);
}
paperTex.c = {};

// the PlanD seal: a vermilion square with a serif D, double inset rule, slightly rotated; `ink` adds stamp unevenness
export function seal(x, cx, cy, s, { rot = -3 * Math.PI / 180, col = C.acc, fg = '#FFFDF8', ink = 0, seed = 3, letter = 'D' } = {}) {
  x.save(); x.translate(cx, cy); x.rotate(rot);
  rr(x, -s / 2, -s / 2, s, s, s * .1, col);
  x.strokeStyle = rgba('#FFFDF8', .4); x.lineWidth = s * .05; x.beginPath(); x.roundRect(-s / 2 + s * .1, -s / 2 + s * .1, s * .8, s * .8, s * .05); x.stroke();
  text(x, letter, 0, s * .04, { size: s * .62, family: F.serif, weight: 600, col: fg });
  if (ink > 0) {   // stamp texture: pale specks where the ink did not take
    const r = rng(seed); x.globalCompositeOperation = 'destination-out';
    for (let i = 0; i < 90 * ink; i++) { const a = r() * s - s / 2, b = r() * s - s / 2, n = noise3(a * .06, b * .06, seed);
      if (n < .1) continue; x.globalAlpha = .25 + .5 * r(); x.beginPath(); x.arc(a, b, (.6 + r() * 1.8) * s / 60, 0, TAU); x.fill(); }
  }
  x.restore();
}
// a bot's avatar: the living face (faces.js). ring: show the busy ring while the bot runs; still: a frozen history face
export function avatar(x, X, Y, s, name, t, { ring = false, still = false, gap = C.bg, alpha = 1 } = {}) {
  const f = faceAt(name, t, { still });
  drawFace(x, X, Y, s, BOT[name] || '#9CA3AF', f, { ring: ring && !still && busyAt(name, t) ? ringPulse(t) : 0, ringGap: gap, alpha });
}
// the user's tile: dark ink with "You"
export function youTile(x, X, Y, s) { rr(x, X, Y, s, s, s * .28, C.ink); text(x, 'You', X + s / 2, Y + s * .53, { size: s * .3, family: F.sans, weight: 600, col: '#F7F4EC' }); }
// the composer's send button: a vermilion circle with ↑ (style.css .send)
export function sendBtn(x, cx, cy, r, { press = 0, dim = false } = {}) {
  x.save(); x.translate(cx, cy); x.scale(1 - press * .12, 1 - press * .12); x.globalAlpha *= dim ? .3 : 1;
  x.fillStyle = C.acc; x.beginPath(); x.arc(0, 0, r, 0, TAU); x.fill();
  x.strokeStyle = '#FFFDF8'; x.lineWidth = r * .14; x.lineCap = 'round'; x.lineJoin = 'round'; x.beginPath(); x.moveTo(0, r * .46); x.lineTo(0, -r * .44); x.moveTo(-r * .38, -r * .06); x.lineTo(0, -r * .46); x.lineTo(r * .38, -r * .06); x.stroke();
  x.restore();
}
export function kbd(x, X, Y, s, size = 10.5) {
  const w = measure(x, s, { size, family: F.mono, weight: 500 }) + size * .8;
  rr(x, X, Y - size * .85, w, size * 1.7, 4, C.sheet, C.border2, 1);
  hline(x, X + 2, X + w - 2, Y + size * .85 - .5, C.border2, 1.5);
  T(x, s, X + size * .4, Y, { size, family: F.mono, weight: 500, col: C.muted });
  return w;
}
// pill/chip; returns its width
export function chip(x, X, Y, s, { size = 12, family = F.mono, weight = 500, col = C.text2, bg = C.sheet, border = C.border2, h = null, pad = null, r = null, align = 'left' } = {}) {
  const tw = measure(x, s, { size, family, weight }), p = pad ?? size * .8, w = tw + p * 2, hh = h ?? size * 2;
  const X0 = align === 'right' ? X - w : X;
  rr(x, X0, Y - hh / 2, w, hh, r ?? hh / 2, bg, border, 1);
  T(x, s, X0 + p, Y + .5, { size, family, weight, col });
  return w;
}
export function check(x, X, Y, s, col = C.ok, lw = 2) {
  x.save(); x.strokeStyle = col; x.lineWidth = lw; x.lineCap = 'round'; x.lineJoin = 'round';
  x.beginPath(); x.moveTo(X - s * .45, Y); x.lineTo(X - s * .1, Y + s * .35); x.lineTo(X + s * .5, Y - s * .4); x.stroke(); x.restore();
}
// the brass binding eyelet the thread passes through
export function eyelet(x, X, Y, r) {
  x.save();
  x.fillStyle = 'rgba(60,40,20,.18)'; x.beginPath(); x.arc(X + r * .12, Y + r * .18, r * 1.18, 0, TAU); x.fill();
  const g = x.createLinearGradient(X - r, Y - r, X + r, Y + r); g.addColorStop(0, '#F3D99A'); g.addColorStop(.45, '#C9A15A'); g.addColorStop(1, '#7D5E2C');
  x.fillStyle = g; x.beginPath(); x.arc(X, Y, r, 0, TAU); x.fill();
  x.strokeStyle = 'rgba(255,240,200,.7)'; x.lineWidth = r * .1; x.beginPath(); x.arc(X, Y, r * .78, Math.PI * 1.05, Math.PI * 1.75); x.stroke();
  const h = x.createRadialGradient(X - r * .15, Y - r * .15, 0, X, Y, r * .5); h.addColorStop(0, '#2A1A10'); h.addColorStop(1, '#0E0805');
  x.fillStyle = h; x.beginPath(); x.arc(X, Y, r * .46, 0, TAU); x.fill();
  x.restore();
}
// small line icons (stroke, UI style)
export function icon(x, kind, X, Y, s, col = C.muted, lw = 1.5) {
  x.save(); x.translate(X, Y); x.strokeStyle = col; x.fillStyle = col; x.lineWidth = lw; x.lineCap = 'round'; x.lineJoin = 'round'; x.beginPath();
  const h = s / 2;
  if (kind === 'folder') { x.moveTo(-h, -h * .55); x.lineTo(-h * .2, -h * .55); x.lineTo(0, -h * .3); x.lineTo(h, -h * .3); x.lineTo(h, h * .7); x.lineTo(-h, h * .7); x.closePath(); x.stroke(); }
  else if (kind === 'gear') { for (let i = 0; i < 8; i++) { const a = i / 8 * TAU; x.moveTo(Math.cos(a) * h * .62, Math.sin(a) * h * .62); x.lineTo(Math.cos(a) * h * .95, Math.sin(a) * h * .95); } x.stroke(); x.beginPath(); x.arc(0, 0, h * .55, 0, TAU); x.stroke(); x.beginPath(); x.arc(0, 0, h * .2, 0, TAU); x.stroke(); }
  else if (kind === 'file') { x.moveTo(-h * .7, -h); x.lineTo(h * .3, -h); x.lineTo(h * .7, -h * .6); x.lineTo(h * .7, h); x.lineTo(-h * .7, h); x.closePath(); x.stroke(); x.beginPath(); x.moveTo(-h * .35, -h * .1); x.lineTo(h * .35, -h * .1); x.moveTo(-h * .35, h * .3); x.lineTo(h * .35, h * .3); x.stroke(); }
  else if (kind === 'term') { x.roundRect(-h, -h * .8, s, s * .8, 2); x.stroke(); x.beginPath(); x.moveTo(-h * .55, -h * .3); x.lineTo(-h * .15, 0); x.lineTo(-h * .55, h * .3); x.moveTo(0, h * .35); x.lineTo(h * .5, h * .35); x.stroke(); }
  else if (kind === 'search') { x.arc(-h * .15, -h * .15, h * .6, 0, TAU); x.stroke(); x.beginPath(); x.moveTo(h * .3, h * .3); x.lineTo(h * .9, h * .9); x.stroke(); }
  else if (kind === 'branch') { x.arc(-h * .5, -h * .6, h * .25, 0, TAU); x.moveTo(-h * .5 + h * .25, h * .6); x.arc(-h * .5, h * .6, h * .25, 0, TAU); x.moveTo(h * .5 + h * .25, -h * .3); x.arc(h * .5, -h * .3, h * .25, 0, TAU); x.stroke();
    x.beginPath(); x.moveTo(-h * .5, -h * .35); x.lineTo(-h * .5, h * .35); x.moveTo(h * .5, -h * .05); x.quadraticCurveTo(h * .5, h * .3, -h * .3, h * .45); x.stroke(); }
  else if (kind === 'warn') { x.moveTo(0, -h); x.lineTo(h, h * .8); x.lineTo(-h, h * .8); x.closePath(); x.stroke(); x.beginPath(); x.moveTo(0, -h * .3); x.lineTo(0, h * .25); x.stroke(); x.beginPath(); x.arc(0, h * .52, lw * .7, 0, TAU); x.fill(); }
  else if (kind === 'lock') { x.roundRect(-h * .7, -h * .1, h * 1.4, h * 1.1, 2); x.stroke(); x.beginPath(); x.moveTo(-h * .4, -h * .1); x.lineTo(-h * .4, -h * .45); x.arc(0, -h * .45, h * .4, Math.PI, 0); x.lineTo(h * .4, -h * .1); x.stroke(); }
  else if (kind === 'book') { x.moveTo(0, -h * .6); x.quadraticCurveTo(-h * .5, -h, -h, -h * .7); x.lineTo(-h, h * .8); x.quadraticCurveTo(-h * .5, h * .5, 0, h * .9); x.quadraticCurveTo(h * .5, h * .5, h, h * .8); x.lineTo(h, -h * .7); x.quadraticCurveTo(h * .5, -h, 0, -h * .6); x.lineTo(0, h * .9); x.stroke(); }
  else if (kind === 'bolt') { x.moveTo(h * .2, -h); x.lineTo(-h * .5, h * .1); x.lineTo(0, h * .1); x.lineTo(-h * .2, h); x.lineTo(h * .5, -h * .1); x.lineTo(0, -h * .1); x.closePath(); x.stroke(); }
  else if (kind === 'send') { x.arc(0, 0, h, 0, TAU); x.fill(); x.strokeStyle = '#F7F4EC'; x.lineWidth = s * .09; x.beginPath(); x.moveTo(0, h * .5); x.lineTo(0, -h * .45); x.moveTo(-h * .4, -h * .05); x.lineTo(0, -h * .48); x.lineTo(h * .4, -h * .05); x.stroke(); }
  x.restore();
}
// a progress bar (track + fill)
export function bar(x, X, Y, w, h, k, col = C.acc, track = C.bg3) {
  rr(x, X, Y, w, h, h / 2, track); if (k > .001) rr(x, X, Y, Math.max(h, w * clamp(k)), h, h / 2, col);
}
// word-wrap for latin text; returns lines
export function wrap(x, s, maxW, o) {
  const words = s.split(' '), lines = []; let cur = '';
  for (const w of words) { const t = cur ? cur + ' ' + w : w; if (measure(x, t, o) > maxW && cur) { lines.push(cur); cur = w; } else cur = t; }
  if (cur) lines.push(cur); return lines;
}
// a rubber stamp (word in a double-ruled box), rotated, with ink texture
export function stamp(x, X, Y, word, { size = 34, col = C.acc, rot = -.12, k = 1, seed = 5, sub = '' } = {}) {
  if (k <= 0) return;
  const w = measure(x, word, { size, family: F.mono, weight: 700, track: size * .12 }) + size * 1.1, h = size * (sub ? 2.05 : 1.6);
  const s = k < 1 ? 1 + (1 - k) * 1.4 : 1;
  x.save(); x.translate(X, Y); x.rotate(rot); x.scale(s, s); x.globalAlpha *= clamp(k * 1.6);
  x.strokeStyle = col; x.lineWidth = size * .09; x.beginPath(); x.roundRect(-w / 2, -h / 2, w, h, size * .16); x.stroke();
  x.lineWidth = size * .035; x.beginPath(); x.roundRect(-w / 2 + size * .16, -h / 2 + size * .16, w - size * .32, h - size * .32, size * .08); x.stroke();
  text(x, word, 0, sub ? -size * .22 : size * .03, { size, family: F.mono, weight: 700, col, track: size * .12 });
  if (sub) text(x, sub, 0, size * .55, { size: size * .32, family: F.mono, weight: 500, col, track: size * .05 });
  const r = rng(seed); x.globalCompositeOperation = 'destination-out';
  for (let i = 0; i < 140; i++) { const a = (r() - .5) * w, b = (r() - .5) * h; if (noise3(a * .05, b * .05, seed) < .15) continue; x.globalAlpha = .3 + .5 * r(); x.beginPath(); x.arc(a, b, .5 + r() * size * .05, 0, TAU); x.fill(); }
  x.restore();
}
