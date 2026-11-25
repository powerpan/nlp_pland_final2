// shots.js — the film is one continuous take inside world.js; the shots below are only the chapters (for audits and the
// score). Every chapter draws the same world, then its overlays; captions are one shared pass, so a caption that is still
// on screen when a chapter changes plays its exit instead of vanishing.
import { W, H, TAU, clamp, lerp, seg, ease, easeOut, easeIn, easeInOut, backOut, spring, layer, text, measure, typeset, rgba, mix, hash, rng, noise3, fx } from '../engine.js';
import { drawClawd } from '../endcard.js';
import { renderWorld, pageToWorld, project, drawMotes, drawBeam, cardToWorld, foreignNeedle, camera } from './world.js';
import { MENU_AT, CARDS, teamCard } from './pages.js';
import { THREE } from '../engine.js';
import { TL, B, at } from './tl.js';
import { F, C, seal } from './ui.js';

const VERT = H > W, U = Math.min(W, H) / 1080;   // 9:16 keeps text inside phone safe zones: top 220, bottom 420, right 140 px
const INK = '#F1ECE0', DIM = '#A39C8E', ACC = '#FF7A4D';

// ───────────────────────── overlays ─────────────────────────
// tilt-shift: a screen-space band of focus along a line (the macro shot), everything else defocused
function tiltShift(c, { k = 1, a, b, band = 70, soft = 160, amount = 14 }) {
  if (k <= 0) return;
  const L = layer('tsb', W / 2, H / 2); L.filter = `blur(${(amount / 2).toFixed(1)}px)`; L.drawImage(c.canvas, 0, 0, W / 2, H / 2);
  const M = layer('tsm'), cx = (a[0] + b[0]) / 2, cy = (a[1] + b[1]) / 2, ang = Math.atan2(b[1] - a[1], b[0] - a[0]);
  M.save(); M.translate(cx, cy); M.rotate(ang);
  const g = M.createLinearGradient(0, -band - soft, 0, band + soft); g.addColorStop(0, '#000'); g.addColorStop(soft / (2 * (band + soft)), 'rgba(0,0,0,0)');
  g.addColorStop(1 - soft / (2 * (band + soft)), 'rgba(0,0,0,0)'); g.addColorStop(1, '#000');
  M.fillStyle = g; M.fillRect(-W * 2, -band - soft, W * 4, 2 * (band + soft)); M.fillStyle = '#000'; M.fillRect(-W * 2, -H * 3, W * 4, H * 3 - band - soft + 1); M.fillRect(-W * 2, band + soft - 1, W * 4, H * 3);
  M.restore(); M.globalCompositeOperation = 'source-in'; M.drawImage(L.canvas, 0, 0, W, H);
  c.save(); c.globalAlpha = k; c.drawImage(M.canvas, 0, 0); c.restore();
}
// caption: mono kicker (typed), serif italic line(s) (words rise out of a mask; '\n' breaks a row), Chinese line, soft exit upward
function caption(c, t, { t0, t1, kicker, line, zh, x, y, size = 66, zs = 27, ks = 15, align = 'left', ink = false }) {
  if (t < t0 - .05 || t > t1 + .6) return;
  const out = easeIn(seg(t, t1, t1 + .5)), A = 1 - out, dy = -out * 18 * U, X = x * U, Y = y * U + dy, lh = size * 1.1 * U;
  const INKC = ink ? '#1C1A16' : INK, DIMC = ink ? '#6E685C' : DIM, ACCC = ink ? '#C23C17' : ACC, rows = line.split('\n');
  const fnt = { size: size * U, family: F.serif, weight: 500, italic: true };
  if (ink) {   // a paper label, like the cards in the world: it arrives with the kicker and leaves with the words
    const wmax = Math.max(...rows.map(r => measure(c, r, fnt)), zh ? measure(c, zh, { size: zs * U, family: F.tcs, weight: 500, track: 4 * U * zs / 27 }) : 0);
    const x0 = (align === 'right' ? X - wmax : X) - 34 * U, y0 = Y - size * 1.42 * U, w0 = wmax + 68 * U, h0 = (Y + (rows.length - 1) * lh + size * .94 * U + (zh ? zs * .95 * U : 0) + 26 * U) - y0;
    const ka = easeOut(seg(t, t0 - .02, t0 + .26)) * A; if (ka > 0) { c.save(); c.globalAlpha = ka; c.translate(x0 + w0 / 2, y0 + h0 / 2); const sc = .97 + .03 * ka; c.scale(sc, sc);
      c.shadowColor = 'rgba(20,14,8,.32)'; c.shadowBlur = 30 * U; c.shadowOffsetY = 10 * U; c.fillStyle = '#F7F3EA'; c.beginPath(); c.roundRect(-w0 / 2, -h0 / 2, w0, h0, 10 * U); c.fill(); c.shadowColor = 'transparent';
      c.strokeStyle = 'rgba(120,100,70,.32)'; c.lineWidth = 1 * U; c.stroke(); c.restore(); }
  }
  c.save(); c.globalAlpha = A; if (!ink) { c.shadowColor = 'rgba(0,0,0,.5)'; c.shadowBlur = 14 * U; }
  if (kicker) { const n = Math.floor(clamp((t - t0) / .45) * kicker.length), s = kicker.slice(0, n), kw = 34 * U * ks / 15, ky = Y - size * .97 * U;
    const rk = easeOut(seg(t, t0, t0 + .4)); c.fillStyle = ACCC; c.fillRect(align === 'right' ? X - kw * rk : X, ky - 1 * U, kw * rk, 2.5 * U * ks / 15);
    text(c, s, align === 'right' ? X - kw - 14 * U : X + kw + 14 * U, ky, { size: ks * U, family: F.mono, weight: 700, col: ACCC, track: 3 * U * ks / 15, align }); }
  let wi = 0;
  rows.forEach((row, r) => { const words = row.split(' '), ws = words.map(wd => measure(c, wd + ' ', fnt));
    const total = ws.reduce((a, b) => a + b, 0), x0 = align === 'right' ? X - total : align === 'center' ? X - total / 2 : X, ry = Y + r * lh; let ox = 0;
    words.forEach((wd, i) => { const k = easeOut(seg(t, t0 + .12 + wi * .07, t0 + .62 + wi * .07)); wi++; if (k <= 0) { ox += ws[i]; return; }
      c.save(); if (k < 1) { c.beginPath(); c.rect(x0 + ox - 10 * U - .35 * size * U, ry - size * 1.15 * U, ws[i] + 20 * U + .35 * size * U, size * 1.77 * U); c.clip(); }   // rise out of a slot at its own baseline; no clip once settled
      text(c, wd, x0 + ox, ry + (1 - k) * size * .55 * U, { ...fnt, col: INKC, align: 'left', track: -.5 * U }); c.restore(); ox += ws[i]; }); });
  const nw = rows.join(' ').split(' ').length, zt = t0 + .62 + (nw - 1) * .07 + .05;   // the Chinese line comes in once the last word has landed
  if (zh) text(c, zh, align === 'right' ? X : X + 2 * U, Y + (rows.length - 1) * lh + size * .94 * U, { size: zs * U, family: F.tcs, weight: 500, col: DIMC, align, track: 4 * U * zs / 27, alpha: easeOut(seg(t, zt, zt + .4)) });
  c.restore();
}
// where each chapter's words go, per format (16:9 positions are the original cut's; the feature pages print their own title there)
const CAPS = {
  s1: { t0: .9, t1: TL.send + .5, kicker: 'PLAND', zh: '你只打一行字。', ink: true, h: { line: 'You type one line.', x: 128, y: 230, size: 72 } },
  s2: { t0: TL.explodeB - .3, t1: TL.s3 + .75, kicker: 'UNDERNEATH', zh: '在它底下，事情真的被做完。', h: { line: 'Underneath, the work gets done.', x: 120, y: 880, size: 62 } },
  roll: { t0: TL.roll(0) - .4, t1: TL.split - .35, kicker: 'BOT MODE', zh: '人數、角色都由你定，每個 Bot 的思考深度也由你設定。', ink: true,
    h: { line: 'Any size, any roles,\neach bot thinking as hard as you set.', x: 118, y: 838, size: 52, zs: 25 } },
  split: { t0: TL.split + .2, t1: TL.faces + 1.0, kicker: 'DELEGATION', zh: 'Lead 拆解目標，平行分給隊友。', ink: true, h: { line: 'The lead splits the goal, hands it out.', x: 1802, y: 912, size: 54, align: 'right' } },
  faces: { t0: TL.faces + 1.6, t1: TL.board + .9, kicker: 'LIVING FACES', zh: '在忙什麼，寫在臉上。', ink: true, h: { line: 'Their faces show their work.', x: 118, y: 912, size: 54 } },
  board: { t0: TL.board + 1.55, t1: TL.slipLand(2), kicker: 'BOARD · LIVE', zh: '每個任務都看得見，失敗的也一樣。', ink: true, h: { line: 'Every task, live. Even the ones that fail.', x: 118, y: 912, size: 54 } },
  review: { t0: TL.pass - .3, t1: TL.s5 + .2, kicker: 'REVIEW', zh: '交付之前，由 reviewer 把關。', ink: true, h: { line: 'Checked by a reviewer before it ships.', x: 118, y: 912, size: 54 } },
  s6: { t0: TL.cardDock + .1, t1: TL.pushed + 1.6, kicker: '00 / YOU', zh: '有風險的操作，一定先問你。', ink: true, h: { line: 'Anything risky comes to you.', x: 118, y: 896, size: 58 } },
  guard: { t0: TL.pushed + 2.25, t1: TL.fFall + .85, kicker: 'LOCAL ONLY · 127.0.0.1', zh: '只回應自己的頁面。', h: { line: 'It answers only its own page.', x: 118, y: 900, size: 60 } },
};
function cap(c, t, id) { const k = CAPS[id], L = k && k.h; if (L) caption(c, t, { ...k, ...L }); }
const caps = (c, t) => { for (const id in CAPS) cap(c, t, id); };   // one shared pass, whatever chapter is drawing
function fadeIn(c, t, t0, t1) { const k = 1 - easeOut(seg(t, t0, t1)); if (k > 0) { c.fillStyle = `rgba(8,7,6,${k.toFixed(3)})`; c.fillRect(0, 0, W, H); } }

// ───────────────────────── chapters ─────────────────────────
function grade(extra = {}) { fx({ grade: { shadows: '#151722', highlights: '#fff0dc', split: .3 }, vignette: .26, bloom: { amount: .2, radius: 26, threshold: .84, tint: '#ffcf9e' }, ...extra }); }

function world(c, t, o = {}) { const cs = renderWorld(c, t); drawBeam(c, o.beam ?? .8); drawMotes(c, t, cs, o.motes ?? 1); return cs; }
function s1(c, t, s) {
  world(c, t, { beam: .35 });
  const a = project(pageToWorld(0, 610, 894, t)), b = project(pageToWorld(0, 1100, 894, t));
  tiltShift(c, { a, b, band: 48 * U, soft: 190 * U, amount: lerp(30, 16, easeOut(seg(t, 0, 1.0))), k: 1 - easeInOut(seg(t, TL.send + .05, TL.send + .9)) });
  caps(c, t);
  fadeIn(c, t, 0, .7); grade();
}
// S4: what each thinking card is (screen-space notes with a leader line; not part of the app's UI)
function note(c, t, t0, t1, P, lines, { dx = -18, dy = -54, bg = '#1C1A16' } = {}) {
  const k = easeOut(seg(t, t0, t0 + .45)) * (1 - easeIn(seg(t, t1, t1 + .3))); if (k <= 0) return;
  const [x, y] = P, ex = x + dx * U, ey = y + dy * U, fs = 15 * U, f2 = 13 * U;
  const w1 = measure(c, lines[0], { size: fs, family: F.mono, weight: 700, track: 1.6 * U }), w2 = lines[1] ? measure(c, lines[1], { size: f2, family: F.mono, weight: 500 }) : 0;
  const pw = w1 + (w2 ? w2 + 22 * U : 0) + 28 * U, ph = 32 * U;
  c.save(); c.globalAlpha = k; c.strokeStyle = 'rgba(28,26,22,.6)'; c.lineWidth = 1.4 * U; c.beginPath(); c.moveTo(x, y); c.lineTo(ex, ey + (dy < 0 ? ph / 2 : -ph / 2)); c.stroke();
  c.fillStyle = '#1C1A16'; c.beginPath(); c.arc(x, y, 3.2 * U, 0, TAU); c.fill();
  c.translate(ex, ey); c.scale(.92 + .08 * k, .92 + .08 * k);
  c.shadowColor = 'rgba(20,14,8,.35)'; c.shadowBlur = 12 * U; c.shadowOffsetY = 4 * U; c.fillStyle = bg; c.beginPath(); c.roundRect(0, -ph / 2, pw, ph, 7 * U); c.fill(); c.shadowColor = 'transparent';
  text(c, lines[0], 14 * U, 1 * U, { size: fs, family: F.mono, weight: 700, col: '#F4EFE4', align: 'left', track: 1.6 * U });
  if (lines[1]) text(c, lines[1], 14 * U + w1 + 22 * U, 1 * U, { size: f2, family: F.mono, weight: 500, col: '#C8C0AF', align: 'left' });
  c.restore();
}
// the team is not fixed: an ink tag on the real "+ New bot" button while the slots fill
export const NEWBOT_BTN = [1495, 128];
function teamLabels(c, t) {
  if (t < TL.roll(2) - .1 || t > TL.roll(4) + .7) return;
  note(c, t, TL.roll(2), TL.roll(4) + .35, project(pageToWorld(2, NEWBOT_BTN[0], NEWBOT_BTN[1] + 15, t)), ['+ NEW BOT', 'add as many as you need'], { dx: -360, dy: 70 });
}
function menuLabels(c, t) {
  if (t < TL.menuUp || t > TL.menuDown + .4) return;
  note(c, t, TL.dsRead - .1, TL.menuDown - .2, project(cardToWorld('menuDS', 300, 0)), ['DEEPSEEK', '6 levels'], { dx: -60, dy: -44 });
  note(c, t, TL.hkOut + .45, TL.hkBack - .05, project(cardToWorld('menuHK', 40, 0)), ['HKGAI', '8 levels · 2 new'], { dx: -10, dy: -44, bg: '#7A3E1C' });
  note(c, t, TL.hkNew + .4, TL.hkBack - .05, project(cardToWorld('menuHK', 300, 0)), ['WEB SEARCH & FETCH', 'still on DeepSeek'], { dx: 30, dy: -92 });
}
// the mouse pointer: you build the team, one "+ New bot" click per slot (each bot is dealt in after its click), then the
// same hand goes on to the lead's thinking chip
export const NEWBOT = i => TL.roll(i) - .48;   // the card pops up out of the clicked slot right away (world.js)
function pointer(c, t) {
  if (t < NEWBOT(0) - .9 || t > TL.chip + 1.3) return;
  const slot = i => { const [X, Y] = teamCard(i); return project(pageToWorld(2, X + 138, Y + 80, t)); };
  const way = [...[0, 1, 2, 3, 4].map(i => [NEWBOT(i), slot(i)]), [TL.chip, project(pageToWorld(2, MENU_AT.chip[0] + 6, MENU_AT.chip[1] + 16, t))]];
  const startP = [W * .44, H * 1.08], away = [W * .3, H * 1.1], hop = (a, b, k, up) => [lerp(a[0], b[0], k), lerp(a[1], b[1], k) - Math.sin(Math.PI * k) * up * U];
  let P;
  if (t < way[0][0]) P = hop(startP, way[0][1], easeInOut(seg(t, way[0][0] - .9, way[0][0] - .08)), 40);
  else { let j = 0; while (j < way.length - 2 && t >= way[j + 1][0]) j++; const [ta, A] = way[j], [tb, Bq] = way[Math.min(j + 1, way.length - 1)];
    P = j === way.length - 2 && t >= tb ? Bq : hop(A, Bq, easeInOut(seg(t, ta + .1, tb - .08)), j === way.length - 2 ? 60 : 26); }
  const ka = easeIn(seg(t, TL.chip + .35, TL.chip + 1.2)); P = [lerp(P[0], away[0], ka), lerp(P[1], away[1], ka)];
  let press = 0;
  way.forEach(([ct, Q]) => { press = Math.max(press, seg(t, ct - .07, ct) * (1 - seg(t, ct + .06, ct + .22)));
    const rp = seg(t, ct, ct + .45); if (rp > 0 && rp < 1) { c.save(); c.strokeStyle = rgba('#D4441C', .7 * (1 - rp)); c.lineWidth = 2.6 * U * (1 - rp) + 1; c.beginPath(); c.arc(Q[0], Q[1], (10 + 54 * easeOut(rp)) * U, 0, TAU); c.stroke(); c.restore(); } });
  cursor(c, P[0], P[1], 1.0 * U, press, clamp(seg(t, way[0][0] - .9, way[0][0] - .7)) * (1 - ka));   // rises from below the frame once the page has swung in
}
function s2(c, t, s) { world(c, t); caps(c, t); grade(); }
const feature = id => (c, t) => { world(c, t, { beam: .3 }); caps(c, t); grade(); };
function s4(c, t, s) { world(c, t, { beam: .3, motes: t > TL.faces && t < TL.board ? .55 : 1 }); teamLabels(c, t); menuLabels(c, t); pointer(c, t); caps(c, t); grade(); }
// S6b: the foreign needle and its grey thread (2D, drawn over the world), then the caption
function guard(c, t, s) {
  const cs = world(c, t, { beam: .4 });
  const f = foreignNeedle(t);
  if (f) {
    const fpx = (H / 2) / Math.tan(camera.fov * Math.PI / 360), P = v => project(v), blurAt = d => clamp(cs.ap * Math.abs(1 - cs.focus / d) * (H / 1080), 0, 18);
    const tip = P(f.N), eye = P(f.eye), edgeW = cardToWorld('foreign', 480, 120), far = P(edgeW), slack = t > TL.fHit ? easeOut(seg(t, TL.fHit, TL.fHit + .8)) : 0;
    const mid = P(edgeW.clone().lerp(f.eye, .5).add(new THREE.Vector3(0, 0, -.18 - .35 * slack)));
    const op = clamp(seg(t, TL.fIn - .2, TL.fIn + .3) * 2);
    c.save(); c.globalAlpha = op; const bl = blurAt(eye[2]); if (bl > .5) c.filter = `blur(${bl.toFixed(1)}px)`;
    // the grey thread: from the foreign page's edge to the needle's eye, sagging
    c.strokeStyle = '#8F8B82'; c.lineCap = 'round'; c.lineWidth = Math.max(1.2, .028 * fpx / eye[2]); c.beginPath(); c.moveTo(far[0], far[1]); c.quadraticCurveTo(mid[0], mid[1], eye[0], eye[1]); c.stroke();
    c.strokeStyle = 'rgba(230,226,216,.35)'; c.lineWidth *= .35; c.setLineDash([3 * U, 4 * U]); c.stroke(); c.setLineDash([]);
    // the needle: dull steel, point first
    const w = .07 * fpx / eye[2], dx = tip[0] - eye[0], dy = tip[1] - eye[1], L = Math.hypot(dx, dy) || 1, nx = -dy / L, ny = dx / L;
    const g = c.createLinearGradient(eye[0] + nx * w, eye[1] + ny * w, eye[0] - nx * w, eye[1] - ny * w); g.addColorStop(0, '#E4E3DE'); g.addColorStop(.42, '#75736B'); g.addColorStop(1, '#1F1E1A');
    c.save(); c.shadowColor = 'rgba(10,8,6,.45)'; c.shadowBlur = 8 * U; c.shadowOffsetY = 4 * U;
    c.fillStyle = g; c.beginPath(); c.moveTo(eye[0] + nx * w * .5, eye[1] + ny * w * .5); c.lineTo(tip[0], tip[1]); c.lineTo(eye[0] - nx * w * .5, eye[1] - ny * w * .5); c.closePath(); c.fill(); c.restore();
    c.strokeStyle = 'rgba(20,18,15,.55)'; c.lineWidth = 1 * U; c.stroke();
    c.strokeStyle = 'rgba(255,255,255,.7)'; c.lineWidth = 1.1 * U; c.beginPath(); c.moveTo(lerp(eye[0], tip[0], .15) + nx * w * .2, lerp(eye[1], tip[1], .15) + ny * w * .2); c.lineTo(lerp(eye[0], tip[0], .8) + nx * w * .05, lerp(eye[1], tip[1], .8) + ny * w * .05); c.stroke();
    c.fillStyle = '#1E1C18'; c.beginPath(); c.ellipse(lerp(eye[0], tip[0], .1), lerp(eye[1], tip[1], .1), w * .13, w * .4, Math.atan2(dy, dx) + Math.PI / 2, 0, TAU); c.fill();
    c.restore();
    // the strike: a brass spark at the eyelet
    const sk = seg(t, TL.fHit, TL.fHit + .4); if (sk > 0 && sk < 1) { const E = project(new THREE.Vector3(-7.7, -4.72, .02)), r = rng(31); c.save(); c.globalCompositeOperation = 'lighter';
      const gg = c.createRadialGradient(E[0], E[1], 0, E[0], E[1], 90 * U * (1 - sk * .5)); gg.addColorStop(0, `rgba(255,220,150,${(.85 * (1 - sk)).toFixed(3)})`); gg.addColorStop(1, 'rgba(255,170,90,0)'); c.fillStyle = gg; c.fillRect(E[0] - 100 * U, E[1] - 100 * U, 200 * U, 200 * U);
      c.strokeStyle = `rgba(255,214,150,${(1 - sk).toFixed(3)})`; c.lineWidth = 2 * U; for (let i = 0; i < 12; i++) { const an = -Math.PI * (.15 + .7 * r()), d0 = (10 + 30 * easeOut(sk)) * U, d1 = d0 + (14 + 30 * r()) * U * (1 - sk);
        c.beginPath(); c.moveTo(E[0] + Math.cos(an) * d0, E[1] + Math.sin(an) * d0); c.lineTo(E[0] + Math.cos(an) * d1, E[1] + Math.sin(an) * d1); c.stroke(); } c.restore(); }
  }
  caps(c, t); grade();
}

// S6: the cursor that answers the approval card
function cursor(c, x, y, sc, press, a) {
  if (a <= 0) return; c.save(); c.globalAlpha = a; c.translate(x, y); const k = sc * (1 - press * .14); c.scale(k, k);
  c.shadowColor = 'rgba(20,14,8,.35)'; c.shadowBlur = 10; c.shadowOffsetY = 4;
  c.beginPath(); c.moveTo(0, 0); c.lineTo(0, 35); c.lineTo(9, 27); c.lineTo(16, 43); c.lineTo(22.5, 40); c.lineTo(15.5, 24); c.lineTo(27, 24); c.closePath();
  c.fillStyle = '#16140f'; c.fill(); c.shadowColor = 'transparent'; c.strokeStyle = '#ffffff'; c.lineWidth = 2.4; c.lineJoin = 'round'; c.stroke(); c.restore();
}
function s6(c, t, s) {
  world(c, t, { beam: .3 });
  caps(c, t);
  if (t > TL.cursorA - .1 && t < TL.click + 1.2) {
    const btn = project(cardToWorld('approval', 70, 190)), k = easeInOut(seg(t, TL.cursorA, TL.click - .16)), sx = W * .93, sy = H * 1.06;
    let x = lerp(sx, btn[0], k) + Math.sin(Math.PI * k) * 90 * U, y = lerp(sy, btn[1], k) - Math.sin(Math.PI * k) * 40 * U;
    const away = easeInOut(seg(t, TL.click + .3, TL.click + .75)); x += away * 120 * U; y += away * 80 * U;
    const press = seg(t, TL.click - .07, TL.click) * (1 - seg(t, TL.click + .06, TL.click + .22));
    const rp = seg(t, TL.click, TL.click + .45); if (rp > 0 && rp < 1) { c.save(); c.strokeStyle = rgba('#D4441C', .8 * (1 - rp)); c.lineWidth = 3 * U * (1 - rp) + 1; c.beginPath(); c.arc(btn[0], btn[1], (12 + 70 * easeOut(rp)) * U, 0, TAU); c.stroke(); c.restore(); }
    cursor(c, x, y, 1.05 * U, press, clamp(seg(t, TL.cursorA - .1, TL.cursorA + .2) * 2) * (1 - away));
  }
  grade();
}

// S7: the close and the title. Wordmark "Plan" + the seal "D" that stamps in, as in the app's empty state.
const TS = 150, TX = 132, TY = VERT ? 1060 : 470;
function sealPos(c) {
  const ww = measure(c, 'Plan', { size: TS * U, family: F.serif, weight: 600, track: -4 * U }), sz = TS * U * .9;
  const X = VERT ? W / 2 - (ww + 92 * U + sz / 2) / 2 : TX * U; return { X, ww, sx: X + ww + 92 * U, sy: TY * U + 6 * U, sz };
}
// words that rise out of a mask, left-aligned at x or centred on it
function riseWords(c, t, t0, str, x, y, size, col, align = 'left') {
  const words = str.split(' '), ws = words.map(wd => measure(c, wd + ' ', { size, family: F.serif, weight: 500, italic: true })), total = ws.reduce((a, b) => a + b, 0);
  let ox = align === 'center' ? x - total / 2 : x;
  words.forEach((wd, i) => { const k = easeOut(seg(t, t0 + i * .06, t0 + .5 + i * .06));
    if (k > 0) { c.save(); if (k < 1) { c.beginPath(); c.rect(ox - 8 * U - .35 * size, y - size * 1.15, ws[i] + 16 * U + .35 * size, size * 2.0); c.clip(); } text(c, wd, ox + 4 * U, y + (1 - k) * size, { size, family: F.serif, weight: 500, italic: true, col, align: 'left' }); c.restore(); }
    ox += ws[i]; });
}
function titleBlock(c, t) {
  const T0 = TL.seal - .42; if (t < T0 - .05) return null;
  const { X, ww, sx, sy, sz } = sealPos(c), Y = TY * U, size = TS * U;
  typeset(c, 'Plan', X, Y, { size, family: F.serif, weight: 600, col: '#F1ECE0', track: -4 * U, align: 'left' },
    i => { const a = spring(t - T0 - i * .05, 1.7, 7); return { dy: (1 - clamp(a)) * 60 * U, a: clamp(a * 2.2), s: .9 + .1 * clamp(a) }; });
  const sk = t - (T0 + .42);
  if (sk > -.18 && t < TL.end + .02) {   // the seal: drops in big, squashes on the paper, settles
    const fall = clamp((sk + .18) / .18), sc = sk < 0 ? lerp(1.9, 1, easeIn(fall)) : 1 + .1 * Math.exp(-9 * sk) * Math.cos(sk * 30), a = sk < 0 ? easeIn(fall) : 1;
    c.save(); c.globalAlpha = a; c.translate(sx, sy); c.scale(sc, 2 - sc); seal(c, 0, 0, sz, { ink: .5, seed: 13, rot: -3 * Math.PI / 180 }); c.restore();
    if (sk > 0 && sk < .7) { const r = rng(21); c.save(); c.fillStyle = '#D4441C';   // ink flecks thrown off by the stamp
      for (let i = 0; i < 26; i++) { const an = r() * TAU, d0 = sz * (.62 + r() * .5), d = d0 + easeOut(clamp(sk / .25)) * sz * (.15 + r() * .35), rr2 = (1.5 + r() * 4) * U;
        c.globalAlpha = (1 - clamp(sk / .7)) * (.5 + .5 * r()); c.beginPath(); c.arc(sx + Math.cos(an) * d, sy + Math.sin(an) * d * .8, rr2, 0, TAU); c.fill(); } c.restore(); }
  }
  const tg = TL.tagline; if (t < tg - .05) return;
  const zh = '一句話進去，整支團隊在你眼前工作。', cmd = 'pland desktop', za = easeOut(seg(t, tg + .45, tg + .95)), ck = easeOut(seg(t, tg + .7, tg + 1.1));
  const chip = (cx0, cy0) => { if (ck <= 0) return; c.save(); c.globalAlpha = ck; const fs = (VERT ? 26 : 20) * U, cw = measure(c, '$ ' + cmd, { size: fs, family: F.mono, weight: 500 }) + 36 * U, ch = fs * 2.2, x0 = VERT ? cx0 - cw / 2 : cx0;
    c.strokeStyle = 'rgba(241,236,224,.28)'; c.lineWidth = 1.2; c.beginPath(); c.roundRect(x0, cy0 - ch / 2, cw, ch, 8 * U); c.stroke();
    text(c, '$', x0 + 18 * U, cy0, { size: fs, family: F.mono, weight: 500, col: '#FF7A4D', align: 'left' }); text(c, cmd, x0 + 18 * U + fs * 1.1, cy0, { size: fs, family: F.mono, weight: 500, col: '#E9E2D4', align: 'left' }); c.restore(); };
  if (VERT) {
    riseWords(c, t, tg, 'One line in.', W / 2, Y + 128 * U, 56 * U, '#E9E2D4', 'center'); riseWords(c, t, tg + .18, 'A whole team underneath.', W / 2, Y + 196 * U, 56 * U, '#E9E2D4', 'center');
    text(c, zh, W / 2, Y + 272 * U, { size: 31 * U, family: F.tcs, weight: 500, col: '#A39C8E', align: 'center', track: 4 * U, alpha: za }); chip(W / 2, Y + 350 * U);
  } else {
    riseWords(c, t, tg, 'One line in.', X, Y + 112 * U, 46 * U, '#E9E2D4'); riseWords(c, t, tg + .2, 'A whole team you can watch.', X, Y + 170 * U, 46 * U, '#E9E2D4');
    text(c, zh, X + 6 * U, Y + 232 * U, { size: 25 * U, family: F.tcs, weight: 500, col: '#A39C8E', align: 'left', track: 4 * U, alpha: za }); chip(X + 6 * U, Y + 296 * U);
  }
}
const BURST = .45;   // seconds of the seal's break-up before the end card
function clawdLayout(c) { const px = 19 * U, ts = 132 * U, gap = 56 * U, tw = measure(c, 'Claude Code', { size: ts, family: 'Space Grotesk', weight: 700, track: -2 * U }), cw = 14 * px;
  return { px, ts, gap, cw, cx: W / 2 - (cw + gap + tw) / 2 + cw / 2, cy: H / 2 - 20 * U }; }
const sealFrom = (c) => { const S0 = sealPos(c); return i => { const a = hash(i * 3.7) - .5, b = hash(i * 5.3) - .5; return [S0.sx + a * S0.sz * .8, S0.sy + b * S0.sz * .8]; }; };
function s7(c, t, s) {
  world(c, t, { beam: .55 }); caps(c, t);
  const dim = easeInOut(seg(t, TL.title, TL.title + 1)) * .35; if (dim > 0) { c.fillStyle = `rgba(10,9,7,${dim})`; c.fillRect(0, 0, W, H); }
  const bk = seg(t, TL.end - BURST, TL.end);
  if (bk <= 0) titleBlock(c, t);
  else { c.save(); c.globalAlpha = 1 - easeIn(bk); titleBlock(c, t); c.restore(); c.fillStyle = `rgba(18,17,14,${easeInOut(bk).toFixed(3)})`; c.fillRect(0, 0, W, H);
    const L = clawdLayout(c), lt = t - (TL.end - BURST); drawClawd(c, L.cx, L.cy, L.px, { k: seg(lt, 0, 1.0), col: mix('#D4441C', '#D97757', easeOut(seg(lt, .1, .9))), eye: '#12110e', from: sealFrom(c) }); }
  grade({ grade: { shadows: '#151722', highlights: '#fff0dc', split: .3 * (1 - bk) }, bloom: { amount: .26 * (1 - bk), radius: 28, threshold: .8, tint: '#ffcf9e' }, vignette: .26 });
}

// End card: the seal breaks into the pixels that build the Claude Code character (a creator credit, not official material)
function endCard(c, t, s) {
  const lt = s.lt, T = { bg: '#12110e', fg: '#ECE8DD', dim: '#8E887B', acc: '#D97757' };
  c.fillStyle = T.bg; c.fillRect(0, 0, W, H);
  c.fillStyle = T.fg; c.globalAlpha = .05 * easeOut(seg(lt, .2, 1)); for (let x = 24 * U; x < W; x += 48 * U) for (let y = 24 * U; y < H; y += 48 * U) c.fillRect(x, y, 2 * U, 2 * U); c.globalAlpha = 1;
  const px = (VERT ? 22 : 19) * U, ts = (VERT ? 124 : 132) * U, gap = 56 * U, tw = measure(c, 'Claude Code', { size: ts, family: 'Space Grotesk', weight: 700, track: -2 * U }), cw = 14 * px;
  const cx = VERT ? W / 2 : W / 2 - (cw + gap + tw) / 2 + cw / 2, cy = VERT ? H / 2 - 170 * U : H / 2 - 20 * U;
  const glow = c.createRadialGradient(cx, cy, 0, cx, cy, 420 * U); glow.addColorStop(0, T.acc + '33'); glow.addColorStop(1, T.acc + '00');
  c.globalAlpha = easeOut(seg(lt, .4, 1.4)); c.fillStyle = glow; c.fillRect(0, 0, W, H); c.globalAlpha = 1;
  const T2 = lt + BURST, land = T2 - 1.0, sq = land > 0 ? 1 - .14 * Math.exp(-land * 7) * Math.cos(land * 22) : 1, hop = lt > 2.5 ? Math.max(0, Math.sin(clamp((lt - 2.5) / .35) * Math.PI)) * 26 * U : 0;
  c.save(); c.globalAlpha = .25 * easeOut(seg(T2, .8, 1.1)); c.fillStyle = '#000'; c.beginPath(); c.ellipse(cx, cy + 4.6 * px, 6 * px * (1 - hop / (120 * U)), 1.1 * px, 0, 0, TAU); c.fill(); c.restore();
  drawClawd(c, cx, cy - hop, px, { k: seg(T2, 0, 1.0), squash: sq, blink: lt > 2.0 && lt < 2.08, col: mix('#D4441C', T.acc, easeOut(seg(T2, .1, .9))), eye: T.bg, from: sealFrom(c) });
  const tx = VERT ? W / 2 : cx + cw / 2 + gap, ty = VERT ? cy + 5.2 * px + 96 * U : cy - 10 * U;
  typeset(c, 'Claude Code', tx, ty, { size: ts, family: 'Space Grotesk', weight: 700, col: T.fg, track: -2 * U, align: VERT ? 'center' : 'left' },
    i => { const a = spring(lt - 1.0 - i * .035, 1.8, 7); return { s: Math.max(0, a), dy: (1 - clamp(a)) * 40 * U, a: clamp(a * 2) }; });
  const line = '> made with Claude Code', n = Math.floor(clamp((lt - 1.55) / .9) * line.length), ly = ty + (VERT ? 118 : 108) * U, lx = VERT ? W / 2 - measure(c, line, { size: 34 * U, family: 'JetBrains Mono', weight: 500 }) / 2 : tx + 6 * U;
  if (lt > 1.45) { const w = text(c, line.slice(0, n), lx, ly, { size: 34 * U, family: 'JetBrains Mono', weight: 500, col: T.dim, align: 'left' });
    if (Math.floor(lt * 2.4) % 2 === 0 || n < line.length) { c.fillStyle = T.acc; c.fillRect(lx + w + 6 * U, ly - 18 * U, 18 * U, 36 * U); } }
  fx({ vignette: .26, grain: .03 });
}
const named = (name, f) => { Object.defineProperty(f, 'name', { value: name }); return f; };
export const SHOTS = [
  { at: 0, draw: named('s1_one_line', s1), mb: { samples: 16, shutter: .3 } },
  { at: TL.s2, draw: named('s2_reveal', s2) },
  { at: TL.s3, draw: named('s3_plan', feature('s3')) },
  { at: TL.s4, draw: named('s4_team', (c, t, s) => s4(c, t, s)) },
  { at: TL.split, draw: named('s4a_delegation', (c, t, s) => s4(c, t, s)) },
  { at: TL.faces, draw: named('s4b_faces', (c, t, s) => s4(c, t, s)), mb: { samples: 20, shutter: .35 } },
  { at: TL.board, draw: named('s4c_board', (c, t, s) => s4(c, t, s)) },
  { at: TL.s5, draw: named('s5_sandbox', feature('s5')) },
  { at: TL.s6, draw: named('s6_you', s6) },
  { at: TL.guard, draw: named('s6b_guard', guard) },
  { at: TL.s7, draw: named('s7_memory_close', s7) },
  { at: TL.end, draw: named('endcard', endCard), tr: { type: 'cut' }, bg: '#12110e' },
];
