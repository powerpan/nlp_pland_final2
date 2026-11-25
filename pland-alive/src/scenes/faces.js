// faces.js — the bots' living faces, drawn from the app's own SVG (pland/server/static/app.js FACE_SVG, style.css .face).
// 32-unit box: eyes at x 11 / 21, y 14 (white ellipse 3.6×4.2, pupil r 2 at y 14.2, #161A22), a ^ ^ "joy" pair, six mouths
// in white 1.8 strokes. The moods are the app's FACE_MOODS (gaze lists, expressions, hold times) and its reactions (a 2.4 s grin
// after a finished run, a 3.2 s frown after an error). Gaze: the pupils snap (.18 s), the whole face drifts after them (.38 s).
// The app picks gaze and holds at random; here every choice is hashed, and each bot's whole track is precomputed at load, so a
// face is a pure function of t. All tiles of one bot share one track, exactly as in the app.
import { clamp, lerp, hash } from '../engine.js';
import { TL } from './tl.js';

// ───────── the story: each bot's run state over the film ─────────
// states: idle · thinking · tool · writing · waiting; 'done' / 'error' are run ends (the app's faceReact)
const S = (t, s, tool) => [t, s, tool];
export const STORY = {
  // the lead sits inside delegate_task while a batch runs: delegate() returns only when every task in the batch has finished
  lead: [S(0, 'idle'), S(TL.lead, 'thinking'), S(TL.planItems, 'tool', 'todo'), S(TL.planItems + 1.6, 'thinking'), S(TL.split - .2, 'tool', 'team_tasks'), S(TL.born(2) + .3, 'thinking'),
    S(TL.slip(0) - .4, 'tool', 'delegate_task'), S(TL.done1 + .05, 'thinking'), S(TL.handLand, 'tool', 'read_file'), S(TL.handLand + .6, 'thinking'),
    S(TL.redo2 - .4, 'tool', 'delegate_task'), S(TL.done2 + .05, 'thinking'), S(TL.slip(2) - .4, 'tool', 'delegate_task'), S(TL.done3 + .05, 'thinking'),
    S(TL.logRow(0) - .3, 'tool', 'run_shell'), S(TL.pushAsk, 'waiting'), S(TL.click + .05, 'tool', 'git_push'), S(TL.pushed, 'writing'), S(TL.pushed + 1.5, 'thinking'),
    S(TL.finished, 'done')],
  researcher: [S(0, 'idle')],
  coder: [S(0, 'idle'), S(TL.slipLand(1), 'thinking'), S(TL.slipLand(1) + 1.1, 'tool', 'run_python'), S(TL.fail2, 'error'), S(TL.redo2, 'thinking'), S(TL.redo2 + .55, 'tool', 'run_python'), S(TL.done2, 'done')],
  reviewer: [S(0, 'idle'), S(TL.slipLand(2), 'thinking'), S(TL.slipLand(2) + .7, 'tool', 'run_shell'), S(TL.done3, 'done')],
  writer: [S(0, 'idle'), S(TL.slipLand(0), 'thinking'), S(TL.slipLand(0) + 1.4, 'writing'), S(TL.done1, 'done')],
};
export function stateAt(name, t) { const tr = STORY[name] || STORY.researcher; let s = 'idle', t0 = 0, tool = null; for (const [a, st, tl] of tr) if (t >= a) { s = st; t0 = a; tool = tl; } return { s, since: t - t0, tool }; }
export const busyAt = (name, t) => { const { s } = stateAt(name, t); return s !== 'idle' && s !== 'done' && s !== 'error'; };
// the sidebar / board line for a state (the app's exact strings)
export function workLine(name, t, fallback = 'run_shell') {
  const { s, tool: tl } = stateAt(name, t), tool = tl || fallback;
  return s === 'thinking' ? 'Thinking…' : s === 'tool' ? `Running ${tool}…` : s === 'writing' ? 'Writing…' : s === 'waiting' ? 'Waiting for you…' : '';
}

// ───────── the app's moods ─────────
const MOODS = {
  thinking: { gaze: [[-1, -1], [1, -1], [-.6, -.9], [.9, -.4], [0, -1], [-1, .1]], expr: ['think', 'think', 'neutral', 'focus'], hold: [.65, 1.7] },
  tool: { gaze: [[-.8, .9], [.8, .9], [0, 1], [-1, .3], [1, .4], [0, 0]], expr: ['focus', 'focus', 'focus', 'neutral', 'surprise'], hold: [.45, 1.3] },
  waiting: { gaze: [[0, 0], [0, 0], [0, 0], [-.9, 0], [.9, 0]], expr: ['ask'], hold: [1.2, 2.6] },
  idle: { gaze: [[0, 0]], expr: ['neutral'], hold: [4, 8] },
};
// expression → eye transform and mouth (style.css [data-expr])
const EXPR = {
  neutral: { sx: 1, sy: 1, ty: 0, eye: 1, joy: 0, m: 'smile' }, think: { sx: 1, sy: .84, ty: 0, eye: 1, joy: 0, m: 'side' },
  focus: { sx: 1, sy: .55, ty: 0, eye: 1, joy: 0, m: 'flat' }, ask: { sx: 1.08, sy: 1.08, ty: 0, eye: 1, joy: 0, m: 'o' },
  surprise: { sx: 1.16, sy: 1.16, ty: 0, eye: 1, joy: 0, m: 'o' }, happy: { sx: 1, sy: 1, ty: 0, eye: 0, joy: 1, m: 'grin' },
  sad: { sx: 1, sy: .78, ty: 1, eye: 1, joy: 0, m: 'sad' },
};
const MOUTHS = ['smile', 'flat', 'side', 'sad', 'o', 'grin'];
const cb = (x1, y1, x2, y2) => k => { if (k <= 0) return 0; if (k >= 1) return 1; let lo = 0, hi = 1, u = k;   // CSS cubic-bezier timing
  for (let i = 0; i < 18; i++) { u = (lo + hi) / 2; const x = 3 * (1 - u) * (1 - u) * u * x1 + 3 * (1 - u) * u * u * x2 + u * u * u; if (x < k) lo = u; else hi = u; }
  return 3 * (1 - u) * (1 - u) * u * y1 + 3 * (1 - u) * u * u * y2 + u * u * u; };
const E_HEAD = cb(.3, .7, .3, 1), E_PUP = cb(.2, .8, .3, 1), E_EASE = cb(.25, .1, .25, 1);
// a channel = keyframes [t, target]; each change eases from the value it had at that moment (CSS transitions do exactly this)
function channel(keys, dur, ez) {
  const st = []; let v = keys[0][1];
  for (let i = 0; i < keys.length; i++) { const [t, tgt] = keys[i]; if (i) { const [tp, tgp] = keys[i - 1]; v = st[i - 1] + (tgp - st[i - 1]) * ez(clamp((t - tp) / dur)); } st.push(v); }
  return t => { let i = 0, lo = 0, hi = keys.length - 1; if (t < keys[0][0]) return keys[0][1];
    while (lo <= hi) { const m = (lo + hi) >> 1; if (keys[m][0] <= t) { i = m; lo = m + 1; } else hi = m - 1; }
    return st[i] + (keys[i][1] - st[i]) * ez(clamp((t - keys[i][0]) / dur)); };
}
const END = 92;
function buildTrack(name, seed) {
  const story = STORY[name] || STORY.researcher, keys = [];   // [t, gx, gy, expr]
  let n = 0;
  for (let si = 0; si < story.length; si++) {
    const [t0, st] = story[si], t1 = si + 1 < story.length ? story[si + 1][0] : END;
    if (st === 'done' || st === 'error') {   // the reaction, then idle
      const fl = st === 'done' ? 2.4 : 3.2; keys.push([t0, 0, 0, st === 'done' ? 'happy' : 'sad']);
      if (t0 + fl < t1) { for (let t = t0 + fl; t < t1;) { keys.push([t, 0, 0, 'neutral']); t += lerp(4, 8, hash(seed + n++, 7)); } }
      continue;
    }
    if (st === 'writing') {   // the reading sweep: −1 → −.5 → 0 → .5 → 1, then snap back like a carriage return
      let sw = -1; for (let t = t0; t < t1;) { keys.push([t, sw, .55, hash(seed + n, 3) < .12 ? 'happy' : 'neutral']); sw = sw < 1 ? sw + .5 : -1; t += lerp(.26, .46, hash(seed + n++, 5)); }
      continue;
    }
    const m = MOODS[st];
    for (let t = t0; t < t1;) {
      const g = m.gaze[Math.floor(hash(seed + n, 1) * m.gaze.length)], ex = m.expr[Math.floor(hash(seed + n, 2) * m.expr.length)];
      keys.push([t, g[0], g[1], ex]); t += lerp(m.hold[0], m.hold[1], hash(seed + n++, 4));
    }
  }
  // blinks: 130 ms, every 1.4–4.2 s while busy, 2.6–7 s idle; 15 % come back as a quick double
  const blinks = []; let bt = .5 + hash(seed, 9) * 3.5, k = 0;
  while (bt < END) { blinks.push(bt); const busy = busyAt(name, bt), iv = busy ? lerp(1.4, 4.2, hash(seed + k, 11)) : lerp(2.6, 7, hash(seed + k, 11));
    bt += hash(seed + k, 12) < .15 ? iv / 10 + .13 : iv; k++; }
  const ex = keys.map(([t, , , e]) => [t, EXPR[e]]);
  const ch = {
    hx: channel(keys.map(([t, gx]) => [t, gx]), .38, E_HEAD), hy: channel(keys.map(([t, , gy]) => [t, gy]), .38, E_HEAD),
    px: channel(keys.map(([t, gx]) => [t, gx]), .18, E_PUP), py: channel(keys.map(([t, , gy]) => [t, gy]), .18, E_PUP),
    sx: channel(ex.map(([t, e]) => [t, e.sx]), .16, E_EASE), sy: channel(ex.map(([t, e]) => [t, e.sy]), .16, E_EASE), ty: channel(ex.map(([t, e]) => [t, e.ty]), .16, E_EASE),
    eye: channel(ex.map(([t, e]) => [t, e.eye]), .16, E_EASE), joy: channel(ex.map(([t, e]) => [t, e.joy]), .16, E_EASE),
  };
  MOUTHS.forEach(mm => { ch['m_' + mm] = channel(ex.map(([t, e]) => [t, e.m === mm ? 1 : 0]), .2, E_EASE); });
  return { ch, blinks };
}
const TRACKS = Object.fromEntries(Object.keys(STORY).map((n, i) => [n, buildTrack(n, 101 + i * 37)]));
// the face's pose at time t (a frozen face, e.g. transcript history, passes still: true)
export function faceAt(name, t, { still = false } = {}) {
  const tr = TRACKS[name] || TRACKS.researcher;
  if (still) return { hx: 0, hy: 0, px: 0, py: 0, sx: 1, sy: 1, ty: 0, eye: 1, joy: 0, m_smile: 1, m_flat: 0, m_side: 0, m_sad: 0, m_o: 0, m_grin: 0, blink: 1 };
  const f = {}; for (const [k, fn] of Object.entries(tr.ch)) f[k] = fn(t);
  let b = 1; for (const t0 of tr.blinks) { if (t0 > t + .01) break; const d = t - t0; if (d >= 0 && d < .25) { const k = d < .06 ? d / .06 : d < .13 ? 1 : 1 - (d - .13) / .06; b = Math.min(b, 1 - .92 * clamp(k)); } }
  f.blink = b; return f;
}
// a key for sheet caching: the face's pose, quantised
export const faceKey = (name, t) => { const f = faceAt(name, t); return [f.hx, f.hy, f.px, f.py, f.sy * f.blink, f.sx, f.ty, f.eye, f.joy, f.m_smile, f.m_flat, f.m_side, f.m_sad, f.m_o, f.m_grin].map(v => Math.round(v * 40)).join(','); };

// ───────── drawing ─────────
const JOY = new Path2D('M7.6 15.2Q11 10.6 14.4 15.2M17.6 15.2Q21 10.6 24.4 15.2');
const MP = { smile: new Path2D('M12.6 21.4Q16 24 19.4 21.4'), flat: new Path2D('M13.2 22.6H18.8'), side: new Path2D('M13 23.2Q16.4 22.6 19.4 20.9'),
  sad: new Path2D('M12.8 23.8Q16 21.2 19.2 23.8'), o: (() => { const p = new Path2D(); p.ellipse(16, 22.6, 1.7, 2, 0, 0, Math.PI * 2); return p; })(), grin: new Path2D('M11.6 20.6Q16 26 20.4 20.6Z') };
// tile at (X, Y), size s (px), the bot's colour; f = faceAt(...); ring 0..1 = the busy ring's pulse
export function drawFace(x, X, Y, s, col, f, { ring = 0, ringGap = '#F4F1E9', ringCol = '#D4441C', alpha = 1 } = {}) {
  x.save(); x.globalAlpha *= alpha;
  if (ring > 0) {   // box-shadow: 0 0 0 2px var(--bg), 0 0 0 3.5px var(--accent) (sizes scaled from a 34 px tile)
    const u = s / 34, R = s * .28;
    x.fillStyle = `rgba(212,68,28,${(ring).toFixed(3)})`; x.beginPath(); x.roundRect(X - 3.5 * u, Y - 3.5 * u, s + 7 * u, s + 7 * u, R + 3.5 * u); x.fill();
    x.fillStyle = ringGap; x.beginPath(); x.roundRect(X - 2 * u, Y - 2 * u, s + 4 * u, s + 4 * u, R + 2 * u); x.fill();
  }
  x.beginPath(); x.roundRect(X, Y, s, s, s * .28); x.fillStyle = col; x.fill(); x.save(); x.clip();
  x.fillStyle = 'rgba(0,0,0,.14)'; x.fillRect(X, Y + s - s * .059, s, s * .06);   // inset 0 -2px 0 rgba(0,0,0,.14)
  const k = s / 32; x.translate(X, Y); x.scale(k, k); x.translate(f.hx * 1.1, f.hy * .9);
  // eyes
  if (f.eye > .01) for (const cx of [11, 21]) {
    x.save(); x.globalAlpha *= f.eye; x.translate(cx, 14); x.translate(0, f.ty); x.scale(f.sx, f.sy * f.blink); x.translate(-cx, -14);
    x.fillStyle = '#fff'; x.beginPath(); x.ellipse(cx, 14, 3.6, 4.2, 0, 0, Math.PI * 2); x.fill();
    x.fillStyle = '#161a22'; x.beginPath(); x.arc(cx + f.px * 1.5, 14.2 + f.py * 1.7, 2, 0, Math.PI * 2); x.fill();
    x.restore();
  }
  x.lineWidth = 1.8; x.lineCap = 'round'; x.lineJoin = 'round'; x.strokeStyle = '#fff';
  if (f.joy > .01) { x.save(); x.globalAlpha *= f.joy; x.stroke(JOY); x.restore(); }
  for (const m of MOUTHS) { const a = f['m_' + m]; if (a < .01) continue; x.save(); x.globalAlpha *= a; if (m === 'o' || m === 'grin') { x.fillStyle = 'rgba(0,0,0,.3)'; x.fill(MP[m]); } x.stroke(MP[m]); x.restore(); }
  x.restore(); x.restore();
}
// the busy ring's pulse (keyframes busy-ring 1.6 s ease-in-out infinite)
export const ringPulse = t => .5 - .5 * Math.cos(t / 1.6 * Math.PI * 2);
