// world.js — the one continuous 3D world the whole film is shot in.
// Five 1600×1000 logbook pages are bound at one brass eyelet (bottom-left corner) like a fan deck. A single focus index f(t)
// spreads the deck: pages above the focus swing ~96° out of the way, the focused page faces the camera, the pages below it
// fan out underneath. Every page is a stack of canvas-textured sheets plus a lit paper edge. Each frame is painted
// back-to-front as separate passes, one per page or card, so every page gets its own depth-of-field blur. A cheap
// low-res shadow canvas on each page receives the soft shadows cast by everything above it.
// Desk frame: x right, y away from the viewer, z up. 1 world unit = 100 UI px.
import { THREE, W, H, TAU, clamp, lerp, seg, ease, easeOut, easeIn, easeInOut, expoInOut, backOut, spring, hash, noise3, fbm, mk, gl, layer, shake } from '../engine.js';
import { PAGES, CARDS, PW, PH, PIV, BOX, teamCard, expCard, TAB, paintTab, PROMPT, MENU_AT, TASKS, BOARD, restXY, lastMove, FLY, TEAM } from './pages.js';
import { TL, B, at } from './tl.js';

export const PX = .01;
const TH = .055, RAD = .14, SEP = 2.25, FAN = 13, SWING = 96, DESK_Z = -15.5;
const LIGHT = new THREE.Vector3(-.42, .5, 1).normalize();                      // towards the lamp
const SH = [LIGHT.x / LIGHT.z, LIGHT.y / LIGHT.z];                              // shadow shear per unit of height
const PIVL = [(PIV[0] - PW / 2) * PX, (PH / 2 - PIV[1]) * PX];                  // eyelet in page-local units
const scene = new THREE.Scene();
export const camera = new THREE.PerspectiveCamera(30, W / H, .05, 800);
const R = gl(); const ANISO = R.capabilities.getMaxAnisotropy();
scene.add(new THREE.AmbientLight('#fff4e6', 1.15));
const sun = new THREE.DirectionalLight('#ffe9cc', 1.9); sun.position.copy(LIGHT).multiplyScalar(30); scene.add(sun);
const fill = new THREE.DirectionalLight('#cbd7ff', .35); fill.position.set(6, -8, 3); scene.add(fill);

// ───────────────────────── geometry ─────────────────────────
function rshape(w, h, r) {
  const s = new THREE.Shape(), x0 = -w / 2, y0 = -h / 2, x1 = w / 2, y1 = h / 2;
  s.moveTo(x0 + r, y0); s.lineTo(x1 - r, y0); s.quadraticCurveTo(x1, y0, x1, y0 + r); s.lineTo(x1, y1 - r); s.quadraticCurveTo(x1, y1, x1 - r, y1);
  s.lineTo(x0 + r, y1); s.quadraticCurveTo(x0, y1, x0, y1 - r); s.lineTo(x0, y0 + r); s.quadraticCurveTo(x0, y0, x0 + r, y0); return s;
}
function faceGeo(w, h, r) { const g = new THREE.ShapeGeometry(rshape(w, h, r), 10), p = g.attributes.position, uv = g.attributes.uv; for (let i = 0; i < p.count; i++) uv.setXY(i, p.getX(i) / w + .5, p.getY(i) / h + .5); return g; }
function edgeGeo(w, h, r, th) { const g = new THREE.ExtrudeGeometry(rshape(w, h, r), { depth: th, bevelEnabled: false, curveSegments: 10 }); g.translate(0, 0, -th); return g; }
const sideMat = new THREE.MeshLambertMaterial({ color: '#d8cfbd' }), backMat = new THREE.MeshLambertMaterial({ color: '#e4ddcf' });
const basicMat = (map, o = {}) => new THREE.MeshBasicMaterial({ map, transparent: true, depthTest: false, depthWrite: false, fog: false, toneMapped: false, ...o });
function canvasTex(cv) { const t = new THREE.CanvasTexture(cv); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = ANISO; t.minFilter = THREE.LinearMipmapLinearFilter; return t; }

// ───────────────────────── pages ─────────────────────────
function makeSheet(def, pw, ph) {
  const [rx, ry, rw, rh] = def.rect, S = def.S, cv = mk(rw * S, rh * S), tex = canvasTex(cv);
  const mesh = new THREE.Mesh(def.full ? faceGeo(rw * PX, rh * PX, RAD) : new THREE.PlaneGeometry(rw * PX, rh * PX), basicMat(tex));
  mesh.position.set((rx + rw / 2 - pw / 2) * PX, (ph / 2 - ry - rh / 2) * PX, 0);
  return { def, cv, x: cv.getContext('2d'), tex, mesh, last: null };
}
function paintSheet(sh, t) {
  const k = (window.ready ? 'R' : 'D') + (sh.def.key ? sh.def.key(t) : '');
  if (k === sh.last) return; sh.last = k;
  const { x, cv, def } = sh; x.setTransform(1, 0, 0, 1, 0, 0); x.clearRect(0, 0, cv.width, cv.height);
  x.setTransform(def.S, 0, 0, def.S, -def.rect[0] * def.S, -def.rect[1] * def.S); def.paint(x, t); sh.tex.needsUpdate = true;
}
function shadowLayer(w, h, div = 8) {   // a low-res canvas on a surface that receives the soft shadows cast from above
  const cv = mk(Math.ceil(w / div), Math.ceil(h / div)), tex = new THREE.CanvasTexture(cv); tex.colorSpace = THREE.SRGBColorSpace;
  const mesh = new THREE.Mesh(faceGeo(w * PX, h * PX, RAD), basicMat(tex)); mesh.renderOrder = 60; mesh.position.z = .004;
  return { cv, x: cv.getContext('2d'), tex, mesh, w, h };
}
export const pages = PAGES.map((def, i) => {
  const g = new THREE.Group(), w = PW * PX, h = PH * PX;
  const edge = new THREE.Mesh(edgeGeo(w, h, RAD, TH), [backMat, sideMat]); edge.renderOrder = 0; g.add(edge);
  const sheets = def.sheets.map((s, j) => { const sh = makeSheet(s, PW, PH); sh.mesh.renderOrder = 2 + j; g.add(sh.mesh); return sh; });
  const shadow = shadowLayer(PW, PH); g.add(shadow.mesh);
  { const tw = TAB.w * PX, thh = TAB.h * PX, cv = mk(TAB.w * 3, TAB.h * 3), x = cv.getContext('2d'); x.scale(3, 3); paintTab(x, i); const tex = canvasTex(cv);
    const tab = new THREE.Group(), te = new THREE.Mesh(edgeGeo(tw, thh, .06, TH), [backMat, sideMat]), tf = new THREE.Mesh(faceGeo(tw, thh, .02), basicMat(tex));
    tf.renderOrder = 1; te.renderOrder = 0; tab.add(te, tf); tab.position.set((PW / 2 + TAB.w / 2 - TAB.tuck) * PX, (PH / 2 - TAB.y(i) - TAB.h / 2) * PX, 0); g.add(tab); }
  scene.add(g); return { i, def, g, sheets, edge, shadow, z: 0, th: 0 };
});
// the sandbox wall: a raised paper rim around the workspace (3D, lit)
{
  const [X, Y, w, h] = BOX, t = 14, hh = .26, outer = rshape(w * PX, h * PX, .18), hole = rshape((w - 2 * t) * PX, (h - 2 * t) * PX, .1);
  outer.holes.push(new THREE.Path(hole.getPoints(40).reverse()));
  const geo = new THREE.ExtrudeGeometry(outer, { depth: hh, bevelEnabled: true, bevelThickness: .02, bevelSize: .015, bevelSegments: 2, curveSegments: 12 });
  const wall = new THREE.Mesh(geo, [new THREE.MeshLambertMaterial({ color: '#fdfbf6', transparent: true }), new THREE.MeshLambertMaterial({ color: '#e6dfd0', transparent: true })]);   // transparent: sorted after the (transparent) sheets
  wall.position.set((X + w / 2 - PW / 2) * PX, (PH / 2 - Y - h / 2) * PX, 0); wall.renderOrder = 40; pages[3].g.add(wall); pages[3].wall = wall;
}
// ───────────────────────── cards ─────────────────────────
export const cards = Object.fromEntries(Object.entries(CARDS).map(([name, def]) => {
  const g = new THREE.Group(), w = def.w * PX, h = def.h * PX, cv = mk(def.w * def.S, def.h * def.S), tex = canvasTex(cv);
  const edge = new THREE.Mesh(edgeGeo(w, h, .08, .03), [backMat.clone(), sideMat.clone()]); edge.material.forEach(m => m.transparent = true); g.add(edge);
  const face = new THREE.Mesh(faceGeo(w, h, .08), basicMat(tex)); face.renderOrder = 2; g.add(face); g.visible = false; scene.add(g);
  if (def.back) {   // a designed back, seen when the card is face down (front-face culling hides whichever side looks away)
    const bc = mk(def.w * 2, def.h * 2), bx = bc.getContext('2d'); bx.scale(2, 2); def.back(bx); const bt = canvasTex(bc);
    const back = new THREE.Mesh(faceGeo(w, h, .08), basicMat(bt)); back.rotation.y = Math.PI; back.position.z = -.031; back.renderOrder = 2; g.add(back); }
  return [name, { name, def, g, cv, x: cv.getContext('2d'), tex, face, edge, last: null, op: 1 }];
}));
function paintCard(cd, t) {
  const k = (window.ready ? 'R' : 'D') + (cd.def.key ? cd.def.key(t) : '');
  if (k === cd.last) return; cd.last = k; const { x, cv, def } = cd;
  x.setTransform(1, 0, 0, 1, 0, 0); x.clearRect(0, 0, cv.width, cv.height); x.setTransform(def.S, 0, 0, def.S, 0, 0); def.paint(x, t); cd.tex.needsUpdate = true;
}
// ───────────────────────── desk ─────────────────────────
const desk = (() => {
  const g = new THREE.Group(), cv = mk(64, 64), x = cv.getContext('2d');
  x.fillStyle = 'rgba(236,226,206,.42)'; x.beginPath(); x.arc(32, 32, 3.4, 0, TAU); x.fill();
  const tex = new THREE.CanvasTexture(cv); tex.wrapS = tex.wrapT = THREE.RepeatWrapping; tex.repeat.set(260, 180); tex.anisotropy = ANISO; tex.colorSpace = THREE.SRGBColorSpace;
  const dots = new THREE.Mesh(new THREE.PlaneGeometry(156, 108), new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthTest: false, depthWrite: false, toneMapped: false }));
  g.add(dots); const sh = shadowLayer(9600, 6400, 32); sh.mesh.geometry = new THREE.PlaneGeometry(96, 64); sh.mesh.material.fog = true; sh.mesh.material.blending = THREE.AdditiveBlending; g.add(sh.mesh);
  g.position.set(0, -2, DESK_Z); scene.add(g); return { g, dots, shadow: sh };
})();
scene.fog = new THREE.Fog('#0f0e0b', 40, 110);

// ───────────────────────── choreography: the deck ─────────────────────────
// focus index f(t): which page faces the camera. Moves on beats; S6 sweeps back up, S7 riffles down to the bottom and closes.
const KF = [[0, 0], [TL.s3 + .1, 0], [TL.s3 + at(2.2), 1], [TL.s4, 1], [TL.s4 + at(2), 2], [TL.s5, 2], [TL.s5 + at(2), 3], [TL.cardRise + .35, 3], [TL.cardDock - .25, 0],
  [TL.s7 + .25, 0], [TL.s7 + at(3.4), 4], [TL.closeA, 4], [TL.closeB, 0]];
export function focusAt(t) {
  for (let i = 0; i < KF.length - 1; i++) { const [a, fa] = KF[i], [b, fb] = KF[i + 1]; if (t <= b) return lerp(fa, fb, (fa === fb ? 0 : t <= a ? 0 : easeInOut((t - a) / (b - a)))); }
  return KF[KF.length - 1][1];
}
export const spreadAt = t => easeInOut(seg(t, TL.explodeA, TL.explodeB)) * (1 - easeInOut(seg(t, TL.closeA + .25, TL.closeB)));
function thetaOf(i, f, sp) {
  const d = i - f; if (d >= 0) return -FAN * d * sp * Math.PI / 180;
  return (SWING * clamp(-d) + 7 * Math.max(0, -d - 1)) * sp * Math.PI / 180;   // f is already eased: one ease, not two (no strobing swings)
}
// pose of page i at time t: rotation about the eyelet, height in the stack
export function pagePose(i, t) {
  const f = focusAt(t), sp = spreadAt(t), th = thetaOf(i, f, sp), z = -i * lerp(.035, SEP, sp);
  const c = Math.cos(th), s = Math.sin(th);
  return { th, z, x: PIVL[0] - (c * PIVL[0] - s * PIVL[1]), y: PIVL[1] - (s * PIVL[0] + c * PIVL[1]) };
}
// page-local UI px → world, at time t (h = height above the page surface in world units)
export function pageToWorld(i, ux, uy, t, h = 0) {
  const p = pagePose(i, t), lx = (ux - PW / 2) * PX, ly = (PH / 2 - uy) * PX, c = Math.cos(p.th), s = Math.sin(p.th);
  return new THREE.Vector3(p.x + c * lx - s * ly, p.y + s * lx + c * ly, p.z + h);
}
export function cardToWorld(name, ux, uy) { const cd = cards[name], d = cd.def; return cd.g.localToWorld(new THREE.Vector3((ux - d.w / 2) * PX, (d.h / 2 - uy) * PX, .01)); }
export const eyeletWorld = i => new THREE.Vector3(PIVL[0], PIVL[1], pagePose(i, 0).z);

// cards: where each flying card is at time t → {on, pos, rz, rx, ry, op}
const flatOn = (i, ux, uy, t, h = .035) => ({ pos: pageToWorld(i, ux, uy, t, h), rz: pagePose(i, t).th, rx: 0, ry: 0 });
function arc(A, B, k, hgt) { const e = easeInOut(k); return { pos: new THREE.Vector3().lerpVectors(A.pos, B.pos, e).add(new THREE.Vector3(0, 0, Math.sin(Math.PI * e) * hgt)), rz: lerp(A.rz, B.rz, e), e }; }
function bezier(P0, P1, P2, P3, k) { const u = 1 - k; return P0.clone().multiplyScalar(u * u * u).add(P1.clone().multiplyScalar(3 * u * u * k)).add(P2.clone().multiplyScalar(3 * u * k * k)).add(P3.clone().multiplyScalar(k * k * k)); }
const SLIP_TO = [4, 2, 3];
// S1b: the two thinking menus stand up out of the composer, hinged on their bottom edge, tilted to the lens
const MENU_RX = .62;
function hinged(hx, hy, h, lift, rx, t, pg = 2) {   // a card of height h (UI px) hinged at UI point (hx, hy) of page pg: its centre and tilt
  const H = pageToWorld(pg, hx, hy, t, lift), hh = h * PX / 2; return new THREE.Vector3(H.x, H.y + Math.cos(rx) * hh, H.z + Math.sin(rx) * hh);
}
// S6b: the needle a foreign page tries to stitch into the binding eyelet with. N = tip, D = unit direction (eye → tip).
// Staged against the camera's axes for this shot (azimuth −40°): LEFT is screen-left, FWD is into the frame, z is up.
const EYE0 = new THREE.Vector3(PIVL[0], PIVL[1], 0), NEEDLE_L = 1.35, GAZ = -40 * Math.PI / 180;
export const G_LEFT = new THREE.Vector3(-Math.cos(GAZ), -Math.sin(GAZ), 0), G_FWD = new THREE.Vector3(-Math.sin(GAZ), Math.cos(GAZ), 0), G_UP = new THREE.Vector3(0, 0, 1);
const gp = (l, u, f = 0) => EYE0.clone().addScaledVector(G_LEFT, l).addScaledVector(G_UP, u).addScaledVector(G_FWD, f);
export function foreignNeedle(t) {
  if (t < TL.fIn - .2 || t > TL.fGone) return null;
  const hover = gp(1.2, .5, -.1), from = gp(10.5, 2.2, 2.0), hov = TL.fReach - .8, strikeD = EYE0.clone().sub(hover).normalize();
  let N, D;
  if (t < hov) { const k = easeOut(seg(t, TL.fIn, hov)); N = from.clone().lerp(hover, k).addScaledVector(G_UP, Math.sin(Math.PI * k) * .7); D = strikeD.clone().lerp(G_LEFT.clone().negate(), (1 - k) * .6).normalize(); }
  else if (t < TL.fHit) { const k = easeIn(seg(t, hov, TL.fReach)), w = .03 * Math.sin((t - hov) * 9) * (1 - k); N = hover.clone().lerp(gp(0, .06), k).addScaledVector(G_UP, w); D = strikeD; }
  else { const tau = t - TL.fHit, rec = 1 - Math.exp(-5 * tau) * Math.cos(tau * 7.5);   // glances off the brass: knocked up and back, then hangs there
    N = gp(.7 * rec, .06 + .55 * rec, -.05 * rec);
    D = strikeD.clone().lerp(G_LEFT.clone().negate().addScaledVector(G_UP, .5), .55 * (1 - Math.exp(-5 * tau))).normalize(); }
  // the fall: everything drops to the desk under gravity, tumbling
  let fall = 0, tumble = 0; if (t > TL.fFall) { const tau = t - TL.fFall, g = 11.5; fall = Math.min(.5 * g * tau * tau, 14.9); tumble = Math.min(tau, 1.63) * 2.4; }
  const drop = G_UP.clone().multiplyScalar(-fall).addScaledVector(G_LEFT, fall * .06);
  const Nf = N.clone().add(drop);
  return { N: Nf, D, eye: Nf.clone().addScaledVector(D, -NEEDLE_L), fall, tumble };
}
export function cardPose(name, t) {
  if (name.startsWith('slip')) {
    const i = +name[4], t0 = TL.slip(i) - .35, t1 = TL.slip(i), t2 = TL.slipLand(i), t3 = t2 + .9; if (t < t0 || t > t3) return null;
    const [lx, ly] = teamCard(0), [tx, ty] = teamCard(SLIP_TO[i]), A = flatOn(2, lx + 138 + (i - .5) * 16, ly + 176 - i * 6, t), Bp = flatOn(2, tx + 138, ty + 170, t);
    if (t < t1) { const k = easeOut(seg(t, t0, t1)); return { ...A, pos: A.pos.add(new THREE.Vector3(0, 0, .02 + i * .03)), s: lerp(.6, 1, backOut(k)), op: clamp(k * 2) }; }
    if (t < t2) { const m = arc(A, Bp, seg(t, t1, t2), 1.5 + i * .25); return { pos: m.pos, rz: m.rz + Math.sin(Math.PI * m.e) * .4 * (i - .5), rx: Math.sin(Math.PI * m.e) * .5, ry: -Math.sin(Math.PI * m.e) * .3, s: 1, op: 1 }; }
    const tau = t - t2; return { ...Bp, pos: Bp.pos.add(new THREE.Vector3(0, 0, .05 * Math.exp(-7 * tau) * Math.abs(Math.sin(15 * tau)))), s: 1, op: 1 - seg(t, t3 - .35, t3) };
  }
  if (name[0] === 'k' && name.length === 2) {   // a board card in flight: lifts out of its column, arcs, lands in the next
    const task = TASKS[+name[1] - 1], m = lastMove(task, t); if (!m) return null; const T1 = m[0], L = T1 - FLY; if (t < L || t > T1 + .28) return null;
    const born = m === task.moves[0], cw = BOARD.cardW / 2, chh = BOARD.cardH / 2, [dx, dy] = restXY(task, T1), [lx, ly] = teamCard(0);
    const [sx, sy] = born ? [lx + 138 - cw, ly + 160 - chh] : restXY(task, L - .001);
    const A = flatOn(2, sx + cw, sy + chh, t, born ? .12 : .036), Bp = flatOn(2, dx + cw, dy + chh, t, .036), dist = A.pos.distanceTo(Bp.pos);
    if (t < T1) { const k = seg(t, L, T1), e = expoInOut(k), up = Math.sin(Math.PI * Math.min(1, k * 1.08)), pos = new THREE.Vector3().lerpVectors(A.pos, Bp.pos, e).add(new THREE.Vector3(0, 0, up * (.55 + .12 * dist)));
      const dir = Math.sign(Bp.pos.x - A.pos.x) || 1; return { pos, rz: A.rz + up * .1 * dir, rx: up * .32, ry: -up * .22 * dir, s: born ? lerp(.45, 1, easeOut(Math.min(1, k * 1.6))) : 1 + up * .04, op: born ? clamp(k * 6) : 1 }; }
    const tau = t - T1; return { ...Bp, pos: Bp.pos.add(new THREE.Vector3(0, 0, .05 * Math.exp(-9 * tau) * Math.abs(Math.sin(18 * tau)))), s: 1, op: 1 };
  }
  if (name === 'file') {   // report.md comes back to the lead's inbox (inbox/from-writer/)
    const t0 = TL.handBack - .3, t1 = TL.handBack, t2 = TL.handLand, t3 = t2 + 1.0; if (t < t0 || t > t3) return null;
    const [wx, wy] = teamCard(4), [lx, ly] = teamCard(0), A = flatOn(2, wx + 138, wy + 160, t), Bp = flatOn(2, lx + 138, ly + 160, t);
    if (t < t1) { const k = easeOut(seg(t, t0, t1)); return { ...A, pos: A.pos.add(new THREE.Vector3(0, 0, .03)), s: lerp(.6, 1, backOut(k)), op: clamp(k * 2) }; }
    if (t < t2) { const m = arc(A, Bp, seg(t, t1, t2), 2.8); return { pos: m.pos, rz: m.rz - Math.sin(Math.PI * m.e) * .3, rx: Math.sin(Math.PI * m.e) * .45, ry: Math.sin(Math.PI * m.e) * .25, s: 1, op: 1 }; }
    const tau = t - t2; return { ...Bp, pos: Bp.pos.add(new THREE.Vector3(0, 0, .05 * Math.exp(-7 * tau) * Math.abs(Math.sin(15 * tau)))), s: 1, op: 1 - seg(t, t3 - .35, t3) };
  }
  if (name.startsWith('bot')) {   // building the team: each "+ New bot" click pops a bot card up out of that slot, face down; it flips and lands in place
    const i = +name[3], T1 = TL.roll(i), L = T1 - .44; if (t < L || t > T1 + .3) return null;
    const [X, Y] = teamCard(i), Bp = flatOn(2, X + 138, Y + 103, t, .03);
    if (t < T1) { const k = seg(t, L, T1), e = easeOut(k), pos = Bp.pos.clone().add(new THREE.Vector3(0, 0, Math.sin(Math.PI * Math.min(1, k * 1.08)) * .15));
      return { pos, rz: Bp.rz + (1 - e) * .1 * (i % 2 ? -1 : 1), rx: Math.sin(Math.PI * k) * .06, ry: -Math.PI * (1 - easeInOut(clamp(k * 1.15))), s: lerp(.45, 1, backOut(e, 1.05)), op: clamp(k * 6) }; }
    const tau = t - T1; return { ...Bp, pos: Bp.pos.add(new THREE.Vector3(0, 0, .06 * Math.exp(-9 * tau) * Math.abs(Math.sin(16 * tau)))), s: 1, op: 1 };
  }
  if (name === 'menuDS' || name === 'menuHK') {
    const hk = name === 'menuHK', h = CARDS[name].h, w = CARDS[name].w; if (t < (hk ? TL.hkOut - .1 : TL.chip) || t > TL.menuDown + .5) return null;
    const up = easeOut(seg(t, TL.chip, TL.menuUp + .35)), down = easeInOut(seg(t, hk ? TL.hkBack : TL.menuDown, (hk ? TL.hkBack : TL.menuDown) + .45));
    const hxDS = MENU_AT.x0 + CARDS.menuDS.w / 2, hy = MENU_AT.y;
    if (!hk) { const rx = MENU_RX * backOut(up, 1.2) * (1 - down), lift = lerp(.02, .32, up) * (1 - down) + .02 * down;
      return { pos: hinged(hxDS, hy, h, lift, rx, t), rz: 0, rx, ry: 0, s: lerp(.86, 1, up) * lerp(1, .9, down), op: clamp(up * 3) * (1 - seg(t, TL.menuDown + .25, TL.menuDown + .5)) }; }
    const out = easeOut(seg(t, TL.hkOut, TL.hkOut + .7)), back = easeInOut(seg(t, TL.hkBack, TL.hkBack + .55)), k = out * (1 - back);
    const hx = lerp(hxDS, hxDS + 392, k), rx = MENU_RX * (.7 + .3 * out) * (1 - .25 * back);
    const pos = hinged(hx, hy - 4 * (1 - k), h, .08 + .1 * Math.sin(Math.PI * clamp(out * (1 - back))), rx, t);
    return { pos, rz: 0, rx, ry: -.05 * Math.sin(Math.PI * out), s: 1, op: clamp(seg(t, TL.hkOut - .1, TL.hkOut + .15) * 2) * (1 - seg(t, TL.hkBack + .35, TL.hkBack + .55)) };
  }
  if (name === 'foreign') {
    const f = foreignNeedle(t); if (!f) return null; const w = CARDS.foreign.w * PX;
    const pos = f.eye.clone().addScaledVector(G_LEFT, w / 2 + .1).addScaledVector(G_UP, .2);   // the page that holds the needle, screen-left of its eye
    return { pos, look: true, spin: Math.atan2(-f.D.z, Math.hypot(f.D.x, f.D.y)) * .5 + f.tumble * .6, tumble: f.tumble, s: 1, op: clamp(seg(t, TL.fIn - .2, TL.fIn + .3) * 2) };
  }
  if (name === 'rogue') {
    if (t < TL.rogueA - .3 || t > TL.testsPass + 1.1) return null;
    const hitX = BOX[0] + BOX[2] - 14 - 220, x0 = 420, k = seg(t, TL.rogueA, TL.rogueHit), tau = t - TL.rogueHit;
    let ux = k < 1 ? lerp(x0, hitX, easeIn(k)) : hitX - 70 * (1 - Math.exp(-5 * tau)) - 26 * Math.exp(-5 * tau) * Math.sin(tau * 18) * .4;
    const sq = tau > 0 ? 1 - .16 * Math.exp(-14 * tau) * Math.cos(tau * 30) : 1;
    const P = flatOn(3, ux + (1 - sq) * 220, 866, t, .035); return { ...P, s: 1, sx: sq, sy: 2 - sq, op: clamp(seg(t, TL.rogueA - .3, TL.rogueA) * 2) * (1 - seg(t, TL.testsPass + .5, TL.testsPass + 1.1)) };
  }
  if (name === 'approval') {
    const t0 = TL.pushAsk + .1, t1 = TL.cardRise, t2 = TL.cardDock, t3 = TL.click + .62; if (t < t0 || t > t3) return null;
    const A = flatOn(3, 570, 832, t, .04), Bp = flatOn(0, 957, 530, t, .04);
    if (t < t1) { const k = easeOut(seg(t, t0, t0 + .5)); return { ...A, pos: A.pos.add(new THREE.Vector3(0, 0, .25 * (1 - k))), s: lerp(.85, 1, backOut(k)), op: clamp(k * 2) }; }
    if (t < t2) {
      const k = seg(t, t1, t2), e = easeInOut(k), out = new THREE.Vector3(1.3, -1, 0).normalize();
      const P1 = A.pos.clone().add(out.clone().multiplyScalar(7)).add(new THREE.Vector3(0, 0, 2.5)), P2 = Bp.pos.clone().add(out.clone().multiplyScalar(6)).add(new THREE.Vector3(0, 0, 3.5));
      return { pos: bezier(A.pos, P1, P2, Bp.pos, e), rz: lerp(A.rz, Bp.rz, e), rx: -Math.sin(Math.PI * e) * .55, ry: Math.sin(Math.PI * e) * .2, s: 1, op: 1 };
    }
    const tau = t - t2, fold = easeInOut(seg(t, TL.click + .28, t3)), R = flatOn(0, 957, 470, t, .02);   // answered: the card folds shut and is gone, as the app removes it
    const pos = Bp.pos.clone().add(new THREE.Vector3(0, 0, .06 * Math.exp(-7 * tau) * Math.abs(Math.sin(14 * tau)))).lerp(R.pos, fold);
    return { ...Bp, pos, s: 1, sx: lerp(1, .96, fold), sy: lerp(1, .1, fold), op: 1 - seg(t, t3 - .16, t3) };
  }
  if (name === 'lesson') {
    const t1 = TL.lessonA, t2 = TL.lessonLand; if (t < t1 - .5 || t > t2 + .12) return null;
    const A0 = flatOn(0, 957, 505, t1, .02), A = flatOn(0, 957, 600, t1, .5), [ex, ey, ew, eh] = expCard(0), Bp = flatOn(4, ex + ew / 2, ey + eh / 2, t, .04);
    if (t < t1) { const k = easeOut(seg(t, t1 - .5, t1)); return { pos: A0.pos.clone().lerp(A.pos, k), rz: A.rz, rx: -.25 * Math.sin(Math.PI * k), ry: 0, s: lerp(.62, 1, k), op: clamp(k * 6) }; }
    const k = seg(t, t1, t2), e = easeInOut(k), out = new THREE.Vector3(1.2, -1, 0).normalize();
    const P1 = A.pos.clone().add(out.clone().multiplyScalar(5)).add(new THREE.Vector3(0, 0, 2)), P2 = Bp.pos.clone().add(out.clone().multiplyScalar(4)).add(new THREE.Vector3(0, 0, 3));
    return { pos: bezier(A.pos, P1, P2, Bp.pos, e), rz: lerp(A.rz, Bp.rz, e) + Math.sin(Math.PI * e) * .5, rx: Math.sin(Math.PI * e) * .6, ry: -Math.sin(Math.PI * e) * .35, s: 1, op: 1 };
  }
  return null;
}

// ───────────────────────── camera ─────────────────────────
// keys: t, target [x,y,z], dist, azimuth°, elevation°, roll°, fov°, aperture (max blur px) ; eased between keys
const V = (x, y, z) => [x, y, z];
const GT = (l, u) => { const p = gp(l, u); return [p.x, p.y, p.z]; };   // a guard-shot target, in the shot's own axes
const CAM_H = [
  // S1 · one line
  { t: 0, tgt: V(1.2, -3.7, 0), d: 5.6, az: -15, el: 62, roll: -3, fov: 26, ap: 22 },
  { t: TL.send - .3, tgt: V(2.3, -3.7, 0), d: 5.0, az: -11, el: 65, roll: -2, fov: 26, ap: 22 },   // the pull-out is already moving when the line lifts off
  // S2 · reveal, S3 · plan
  { t: TL.s2 + .7, tgt: V(.3, -.1, 0), d: 24.5, az: 0, el: 90, roll: 0, fov: 30, ap: 6 },
  { t: TL.explodeA, tgt: V(.9, .2, 0), d: 19.8, az: -5, el: 83, roll: 1.5, fov: 30, ap: 6 },
  { t: TL.explodeB + .5, tgt: V(-.4, -4.4, -5.6), d: 54, az: 24, el: 42, roll: -4, fov: 30, ap: 7 },
  { t: TL.s3, tgt: V(-.9, -4.9, -5.6), d: 48, az: 32, el: 40, roll: -4, fov: 30, ap: 7 },
  { t: TL.s3 + at(2.6), tgt: V(-2.6, -.9, -2.25), d: 19.5, az: -14, el: 56, roll: -2, fov: 30, ap: 16 },
  { t: TL.s3 + at(6.5), tgt: V(-1.6, -1.4, -2.25), d: 17.2, az: -7, el: 58, roll: -1.5, fov: 30, ap: 16 },
  // S4 · Bot Mode: the page swings in, the bots are dealt, the lead's thinking level opens on its card
  { t: TL.s4, tgt: V(-2.2, -1.0, -2.25), d: 18.2, az: -10, el: 58, roll: -2, fov: 30, ap: 16 },
  { t: TL.roll(0) - .25, tgt: V(-4.4, 1.3, -4.5), d: 11.6, az: -10, el: 50, roll: -2, fov: 30, ap: 13 },
  { t: TL.roll(4) + .25, tgt: V(3.0, 1.3, -4.5), d: 12.0, az: 6, el: 52, roll: 1, fov: 30, ap: 13 },
  { t: TL.chip - .05, tgt: V(-3.4, 1.7, -4.4), d: 9.6, az: -6, el: 47, roll: -1, fov: 30, ap: 13 },
  { t: TL.menuUp + .4, tgt: V(-2.9, 2.75, -3.7), d: 10.4, az: -4, el: 40, roll: -1, fov: 30, ap: 11 },
  { t: TL.hkOut + .6, tgt: V(-1.75, 2.85, -3.6), d: 11.6, az: 0, el: 39, roll: 0, fov: 30, ap: 10 },
  { t: TL.hkBack, tgt: V(-1.85, 2.85, -3.6), d: 11.3, az: -1, el: 40, roll: 0, fov: 30, ap: 10 },
  // the lead splits the goal, the slips go out
  { t: TL.split + .1, tgt: V(-1.6, .6, -4.5), d: 15.0, az: -3, el: 57, roll: 0, fov: 30, ap: 11 },
  { t: TL.born(2) + .35, tgt: V(-3.4, -.1, -4.5), d: 13.6, az: -8, el: 60, roll: -1, fov: 30, ap: 12 },
  { t: TL.slipLand(1) + .3, tgt: V(.6, .9, -4.5), d: 16.2, az: 3, el: 64, roll: 1, fov: 30, ap: 11 },
  // faces: four holds, quick moves between them
  { t: TL.faces + .1, tgt: V(-3.0, 1.5, -4.5), d: 10.5, az: -9, el: 46, roll: -1, fov: 30, ap: 15 },
  { t: TL.faces + .65, tgt: V(-6.7, 1.95, -4.5), d: 4.7, az: -13, el: 24, roll: -3, fov: 30, ap: 18 },
  { t: TL.faces + 1.25, tgt: V(-6.7, 1.95, -4.5), d: 4.6, az: -13, el: 24, roll: -3, fov: 30, ap: 18 },
  { t: TL.faces + 1.8, tgt: V(-3.75, 2.0, -4.5), d: 4.5, az: -8, el: 23, roll: -2, fov: 30, ap: 18 },
  { t: TL.faces + 2.4, tgt: V(-3.75, 2.0, -4.5), d: 4.45, az: -8, el: 23, roll: -2, fov: 30, ap: 18 },
  { t: TL.faces + 2.95, tgt: V(-.8, 2.0, -4.5), d: 4.4, az: -3, el: 22, roll: -1, fov: 30, ap: 18 },
  { t: TL.faces + 3.6, tgt: V(-.8, 2.0, -4.5), d: 4.35, az: -3, el: 22, roll: -1, fov: 30, ap: 18 },
  { t: TL.faces + 4.15, tgt: V(5.1, 2.0, -4.5), d: 4.6, az: 8, el: 23, roll: 1, fov: 30, ap: 18 },
  { t: TL.faces + 4.75, tgt: V(5.1, 2.0, -4.5), d: 4.55, az: 8, el: 23, roll: 1, fov: 30, ap: 18 },
  // the board, wide enough for the lead and the page title; a push on the failure; the reviewer's PASS
  { t: TL.board + .55, tgt: V(-.15, -.3, -4.5), d: 18.6, az: 0, el: 62, roll: 0, fov: 30, ap: 10 },
  { t: TL.fail2 + .2, tgt: V(.9, -.05, -4.5), d: 15.2, az: 4, el: 58, roll: .5, fov: 30, ap: 11 },
  { t: TL.fail2 + 1.4, tgt: V(.95, -.05, -4.5), d: 15.0, az: 4, el: 58, roll: .5, fov: 30, ap: 11 },
  { t: TL.handLand + .2, tgt: V(-.4, .3, -4.5), d: 17.6, az: 0, el: 62, roll: 0, fov: 30, ap: 10 },
  { t: TL.redo2 + .6, tgt: V(.3, -.3, -4.5), d: 16.6, az: 2, el: 61, roll: 0, fov: 30, ap: 10 },
  { t: TL.slipLand(2) + .1, tgt: V(1.2, .4, -4.5), d: 15.6, az: 3, el: 60, roll: .5, fov: 30, ap: 11 },
  { t: TL.done3, tgt: V(.4, .1, -4.5), d: 17.4, az: 2, el: 60, roll: .5, fov: 30, ap: 11 },
  { t: TL.pass + .5, tgt: V(1.0, .45, -4.5), d: 15.4, az: 3, el: 58, roll: .5, fov: 30, ap: 12 },
  { t: TL.pass + 2.3, tgt: V(.9, .5, -4.5), d: 15.8, az: 3, el: 59, roll: .5, fov: 30, ap: 12 },
  // S5 · sandbox, S6 · you
  { t: TL.s5, tgt: V(.6, .8, -4.5), d: 18.4, az: 2, el: 78, roll: 3, fov: 30, ap: 14 },
  { t: TL.s5 + .95, tgt: V(-2.2, 1.0, -6.75), d: 17.0, az: -15, el: 50, roll: 0, fov: 30, ap: 9 },
  { t: TL.s5 + 1.75, tgt: V(-2.3, .8, -6.75), d: 16.4, az: -18, el: 47, roll: 0, fov: 30, ap: 9 },
  { t: TL.rogueA + .1, tgt: V(-1.0, -1.2, -6.75), d: 12.6, az: -30, el: 36, roll: 0, fov: 30, ap: 9 },
  { t: TL.rogueHit - .14, tgt: V(.7, -2.5, -6.75), d: 11.0, az: -35, el: 32, roll: .5, fov: 30, ap: 10 },
  { t: TL.rogueHit + .12, tgt: V(1.6, -3.3, -6.75), d: 8.6, az: -40, el: 27, roll: 1, fov: 30, ap: 12, e: 'expo' },
  { t: TL.testsPass + .3, tgt: V(-1.6, -1.2, -6.75), d: 12.6, az: -26, el: 38, roll: 0, fov: 30, ap: 8 },
  { t: TL.cardRise + .2, tgt: V(-1.0, -2.1, -6.75), d: 12.8, az: -20, el: 40, roll: 0, fov: 30, ap: 9 },
  { t: TL.cardDock, tgt: V(-.6, -2.6, 0), d: 21.5, az: 32, el: 48, roll: -3, fov: 30, ap: 9 },
  { t: TL.click + .5, tgt: V(-.3, -2.4, 0), d: 19.4, az: 28, el: 51, roll: -3, fov: 30, ap: 9 },
  // S6b · the guard: swing to the binding, push on the strike, follow the fall, come back to the thread that never moved
  { t: TL.fIn + .5, tgt: GT(2.7, -.1), d: 15.0, az: -36, el: 25, roll: -3, fov: 30, ap: 9 },
  { t: TL.fReach, tgt: GT(2.3, .05), d: 13.0, az: -40, el: 22, roll: -3.5, fov: 30, ap: 11 },
  { t: TL.fHit + .18, tgt: GT(2.3, .05), d: 12.2, az: -40.5, el: 22, roll: -4, fov: 30, ap: 12, e: 'expo' },
  { t: TL.fFall, tgt: GT(2.4, .1), d: 11.8, az: -41, el: 22.5, roll: -4, fov: 30, ap: 12 },
  { t: TL.fFall + .9, tgt: GT(2.8, -3.0), d: 15.5, az: -37, el: 22, roll: -3, fov: 30, ap: 9 },
  { t: TL.fGone - 1.3, tgt: GT(.15, -.05), d: 6.8, az: -43, el: 24, roll: -4, fov: 30, ap: 9 },
  { t: TL.fGone - .4, tgt: GT(.1, -.05), d: 6.4, az: -44, el: 24, roll: -4, fov: 30, ap: 9 },
  // S7 · memory, close, title
  { t: TL.s7 + .2, tgt: V(.6, -1, -1), d: 21, az: 6, el: 66, roll: 0, fov: 30, ap: 10 },
  { t: TL.lessonLand + .3, tgt: V(.9, -.9, -9), d: 20.5, az: 16, el: 54, roll: -2, fov: 30, ap: 11 },
  { t: TL.closeA, tgt: V(1.0, -.8, -9), d: 19.2, az: 19, el: 56, roll: -2, fov: 30, ap: 11 },
  { t: TL.closeB + .25, tgt: V(.2, .3, 0), d: 9.0, az: -14, el: 62, roll: -4, fov: 30, ap: 16 },
  { t: TL.finished + .5, tgt: V(-1.3, 1.9, 0), d: 7.4, az: -12, el: 60, roll: -4, fov: 30, ap: 16 },
  { t: TL.title - .1, tgt: V(-1.0, 1.7, 0), d: 7.8, az: -10, el: 62, roll: -4, fov: 30, ap: 16 },
  { t: TL.title + .95, tgt: V(-7.6, -1.6, -.8), d: 35, az: 30, el: 46, roll: -5, fov: 30, ap: 7, e: 'expo' },
  { t: TL.end + .6, tgt: V(-7.8, -1.7, -.8), d: 33.5, az: 34, el: 45, roll: -5, fov: 30, ap: 7 },
];
export const CAM = CAM_H;   // this film is 16:9 only
const caretX = t => { const n = clamp((t - TL.typeA) / (TL.typeB - TL.typeA)) * PROMPT.length; return (606 + 6.6 * n - PW / 2) * PX; };
function camAt(t) {
  if (t > TL.cardRise && t < TL.cardDock) {   // the camera cranes up with the approval card
    const c = camAt0(t), p = cardPose('approval', t), k = seg(t, TL.cardRise, TL.cardDock), w = Math.pow(Math.sin(Math.PI * k), .8) * .85;
    if (p) c.tgt = c.tgt.map((v, j) => lerp(v, [p.pos.x, p.pos.y, p.pos.z][j], w)); return c;
  }
  if (t > TL.lessonA - .4 && t < TL.lessonLand) {   // focus rides the lesson card on its way down
    const c = camAt0(t), p = cardPose('lesson', t), k = seg(t, TL.lessonA - .4, TL.lessonLand), w = Math.sin(Math.PI * k) * .5;
    if (p) c.tgt = c.tgt.map((v, j) => lerp(v, [p.pos.x, p.pos.y, p.pos.z][j], w)); return c; }
  if (t < TL.send + .7) { const c = camAt0(t), fx2 = lerp(caretX(t - .25), caretX(TL.typeB), seg(t, TL.typeB, TL.send)), w = .55 * (1 - easeInOut(seg(t, TL.send, TL.send + .7)));   // follow the caret while it types
    c.tgt = [lerp(c.tgt[0], fx2 - .6, w), c.tgt[1], c.tgt[2]]; return c; }
  return camAt0(t);
}
const CH = ['x', 'y', 'z', 'd', 'az', 'el', 'roll', 'fov', 'ap', 'sy'], cv = (k, c) => c < 3 ? k.tgt[c] : (k[c === 9 ? 'sy' : CH[c]] ?? 0);
const TAN = CH.map((_, c) => {   // Fritsch–Carlson tangents: smooth through every key, never overshooting, zero at real stops
  const n = CAM.length, dl = [], m = new Array(n).fill(0);
  for (let i = 0; i < n - 1; i++) dl.push((cv(CAM[i + 1], c) - cv(CAM[i], c)) / Math.max(1e-4, CAM[i + 1].t - CAM[i].t));
  for (let i = 1; i < n - 1; i++) m[i] = dl[i - 1] * dl[i] <= 0 ? 0 : (dl[i - 1] + dl[i]) / 2;
  for (let i = 0; i < n - 1; i++) { if (dl[i] === 0) { m[i] = m[i + 1] = 0; continue; } const a = m[i] / dl[i], b = m[i + 1] / dl[i], h2 = a * a + b * b; if (h2 > 9) { const tau = 3 / Math.sqrt(h2); m[i] = tau * a * dl[i]; m[i + 1] = tau * b * dl[i]; } }
  return m; });
function camAt0(t) {
  let i = 0; while (i < CAM.length - 2 && t >= CAM[i + 1].t) i++;
  const a = CAM[i], b = CAM[i + 1], h = b.t - a.t, k0 = clamp((t - a.t) / h), o = {};
  const val = c => { if (b.e === 'expo') return lerp(cv(a, c), cv(b, c), expoInOut(k0));
    const k = k0, k2 = k * k, k3 = k2 * k; return (2 * k3 - 3 * k2 + 1) * cv(a, c) + (k3 - 2 * k2 + k) * h * TAN[c][i] + (-2 * k3 + 3 * k2) * cv(b, c) + (k3 - k2) * h * TAN[c][i + 1]; };
  o.tgt = [val(0), val(1), val(2)]; ['d', 'az', 'el', 'roll', 'fov', 'ap'].forEach((p, j) => o[p] = val(j + 3)); o.sy = val(9);
  return o;
}
export function setCamera(t) {
  const c = camAt(t), az = c.az * Math.PI / 180, el = Math.min(89.95, c.el) * Math.PI / 180, [dx, dy] = shake(t, { amp: .6, freq: .35, seed: 4 });
  const tgt = new THREE.Vector3(...c.tgt).add(new THREE.Vector3(dx, dy, 0).multiplyScalar(c.d * .0016));
  const pos = tgt.clone().add(new THREE.Vector3(Math.cos(el) * Math.sin(az), -Math.cos(el) * Math.cos(az), Math.sin(el)).multiplyScalar(c.d));
  camera.position.copy(pos); camera.up.set(-Math.sin(el) * Math.sin(az), Math.sin(el) * Math.cos(az), Math.cos(el)); camera.fov = c.fov; if (c.sy) camera.setViewOffset(W, H, 0, c.sy * H, W, H); else camera.clearViewOffset(); camera.updateProjectionMatrix();   // sy: lens shift (subject sits higher, perspective unchanged)
  camera.lookAt(tgt); camera.rotateZ(c.roll * Math.PI / 180); camera.updateMatrixWorld(true);
  return { ...c, focus: pos.distanceTo(tgt), pos };
}
export function project(v) { const p = v.clone().project(camera); return [(p.x + 1) / 2 * W, (1 - p.y) / 2 * H, camera.position.distanceTo(v)]; }

// ───────────────────────── per-frame layout & shadows ─────────────────────────
function cornersOf(obj, w, h) {   // world corners of a w×h (world units) rect centred on obj's local origin
  return [[-w / 2, -h / 2], [w / 2, -h / 2], [w / 2, h / 2], [-w / 2, h / 2]].map(([a, b]) => obj.localToWorld(new THREE.Vector3(a, b, 0)));
}
const LAMP = new THREE.Vector3(-4.5, 3.2, 0);
function castShadows(recv, recvObj, recvZ, occluders, lamp = 0, pool = 0) {
  const { x, cv, w, h } = recv; x.setTransform(1, 0, 0, 1, 0, 0); x.clearRect(0, 0, cv.width, cv.height);
  const inv = recvObj.matrixWorld.clone().invert(), sc = cv.width / w;
  if (pool > 0) {   // the desk: a warm pool of lamp light that the deck's shadow is cut out of
    const q = new THREE.Vector3(LAMP.x + 3, LAMP.y - 4, recvZ).applyMatrix4(inv), u = (q.x / PX + w / 2) * sc, v = (h / 2 - q.y / PX) * sc, r = 2600 * sc;
    const g = x.createRadialGradient(u, v, 0, u, v, r); g.addColorStop(0, `rgba(255,196,130,${pool})`); g.addColorStop(.5, `rgba(255,180,110,${pool * .4})`); g.addColorStop(1, 'rgba(255,170,100,0)'); x.fillStyle = g; x.fillRect(0, 0, cv.width, cv.height);
  }
  if (lamp > 0) {   // the lamp's pool of light: the page darkens away from the point under the lamp
    const q = new THREE.Vector3(LAMP.x, LAMP.y, recvZ).applyMatrix4(inv), u = (q.x / PX + w / 2) * sc, v = (h / 2 - q.y / PX) * sc, r = 1500 * sc;
    const g = x.createRadialGradient(u, v, r * .15, u, v, r); g.addColorStop(0, 'rgba(20,14,8,0)'); g.addColorStop(1, `rgba(20,14,8,${lamp.toFixed(3)})`); x.fillStyle = g; x.fillRect(0, 0, cv.width, cv.height);
  }
  for (const o of occluders) {
    const dz = o.z - recvZ; if (dz <= .002) continue;
    const pts = o.corners.map(p => { const q = new THREE.Vector3(p.x - SH[0] * (p.z - recvZ), p.y - SH[1] * (p.z - recvZ), recvZ).applyMatrix4(inv); return [(q.x / PX + w / 2) * sc, (h / 2 - q.y / PX) * sc]; });
    const blur = (.12 + .2 * dz) / PX * sc, a = o.dark * .8 / (1 + .3 * dz);
    x.filter = `blur(${blur.toFixed(2)}px)`; x.fillStyle = `rgba(20,14,8,${a.toFixed(3)})`; if (pool) { x.globalCompositeOperation = 'destination-out'; x.fillStyle = `rgba(0,0,0,${Math.min(1, a * 3).toFixed(3)})`; } x.beginPath(); pts.forEach(([u, v], j) => j ? x.lineTo(u, v) : x.moveTo(u, v)); x.closePath(); x.fill();
  }
  x.filter = 'none'; x.globalCompositeOperation = 'source-over'; recv.tex.needsUpdate = true;
}
function layout(t) {
  pages.forEach(p => { const ps = pagePose(p.i, t); p.g.rotation.set(0, 0, ps.th); p.g.position.set(ps.x, ps.y, ps.z); p.z = ps.z; p.g.updateMatrixWorld(true);
    p.sheets.forEach(sh => paintSheet(sh, t)); });
  const occ = pages.map(p => ({ z: p.z, corners: cornersOf(p.g, PW * PX, PH * PX), dark: 1 }));
  for (const cd of Object.values(cards)) {
    const ps = cardPose(cd.name, t); cd.g.visible = !!ps; cd.pose = ps; if (!ps) continue;
    paintCard(cd, t); cd.g.position.copy(ps.pos);
    if (ps.look) { cd.g.rotation.set(0, 0, 0); cd.g.up.set(0, 0, 1); cd.g.lookAt(camera.position); cd.g.rotateZ(ps.spin || 0); cd.g.rotateX(ps.tumble || 0); } else cd.g.rotation.set(ps.rx || 0, ps.ry || 0, ps.rz || 0, 'ZXY');
    cd.g.scale.set((ps.s ?? 1) * (ps.sx ?? 1), (ps.s ?? 1) * (ps.sy ?? 1), 1); cd.g.updateMatrixWorld(true);
    if (/^k\d$/.test(cd.name)) cd.face.material.color.setScalar(.96 * (1 - clamp(-pagePose(2, t).z / 12) * .14)); else cd.face.material.color.setScalar(1);
    cd.face.material.opacity = ps.op ?? 1; cd.edge.material.forEach(m => { m.opacity = ps.op ?? 1; }); cd.z = ps.pos.z;
    occ.push({ z: ps.pos.z, corners: cornersOf(cd.g, cd.def.w * PX, cd.def.h * PX), dark: .8 * (ps.op ?? 1) });
  }
  pages.forEach(p => castShadows(p.shadow, p.shadow.mesh, p.z, occ, .26 + clamp(-p.z / 10) * .16));
  desk.g.updateMatrixWorld(true); castShadows(desk.shadow, desk.shadow.mesh, DESK_Z, occ.map(o => ({ ...o, dark: o.dark * 2.2 })), 0, .16);
  return occ;
}

// ───────────────────────── the thread ─────────────────────────
// vertical, through every eyelet; it is "stitched" downwards in S2 (the needle leads) and shortens as the deck closes
export function threadState(t) {
  const n = pages.length, zs = pages.map(p => p.z), tail = -.9;
  const lead = t < TL.stitchA ? 0 : t >= TL.stitch(n) ? n : (() => { for (let i = 0; i < n; i++) if (t < TL.stitch(i + 1)) return i + easeInOut(seg(t, TL.stitch(i), TL.stitch(i + 1))); })();
  return { zs, lead, zLead: lead >= n - 1 ? lerp(zs[n - 1], zs[n - 1] + tail, clamp(lead - (n - 1))) : lerp(zs[Math.floor(lead)], zs[Math.min(n - 1, Math.floor(lead) + 1)], lead - Math.floor(lead)) };
}
function drawThread(c, z0, z1, blur, glint = 0) {
  const a = project(new THREE.Vector3(PIVL[0], PIVL[1], z0)), b = project(new THREE.Vector3(PIVL[0], PIVL[1], z1));
  const wa = .04 * fpx() / a[2], wb = .04 * fpx() / b[2], near = clamp((70 - Math.max(wa, wb)) / 40) * clamp((Math.hypot(camera.position.x - PIVL[0], camera.position.y - PIVL[1]) - 2.6) / 2.2); if (near <= 0) return;
  c.save(); c.globalAlpha *= near; if (blur > .4) c.filter = `blur(${blur.toFixed(1)}px)`; c.lineCap = 'round';
  const dx = b[0] - a[0], dy = b[1] - a[1], L = Math.hypot(dx, dy) || 1, nx = -dy / L, ny = dx / L;
  c.fillStyle = '#C23C17'; c.beginPath(); c.moveTo(a[0] + nx * wa / 2, a[1] + ny * wa / 2); c.lineTo(b[0] + nx * wb / 2, b[1] + ny * wb / 2); c.lineTo(b[0] - nx * wb / 2, b[1] - ny * wb / 2); c.lineTo(a[0] - nx * wa / 2, a[1] - ny * wa / 2); c.fill();
  c.strokeStyle = 'rgba(255,160,120,.55)'; c.lineWidth = Math.max(.6, (wa + wb) * .14); c.setLineDash([Math.max(2, wa * 1.1), Math.max(2, wa * 1.4)]);
  c.beginPath(); c.moveTo(a[0] + nx * wa * .2, a[1] + ny * wa * .2); c.lineTo(b[0] + nx * wb * .2, b[1] + ny * wb * .2); c.stroke();
  if (glint > 0) { c.setLineDash([]); c.globalCompositeOperation = 'lighter'; c.strokeStyle = `rgba(255,120,60,${(.35 * glint).toFixed(3)})`; c.lineWidth = (wa + wb) * 2.2; c.beginPath(); c.moveTo(a[0], a[1]); c.lineTo(b[0], b[1]); c.stroke(); }
  c.restore();
}
const fpx = () => (H / 2) / Math.tan(camera.fov * Math.PI / 360);
function drawNeedle(c, z, zTip, blur) {   // a brass needle leading the thread, point down; below zTip it is inside the next page
  const a = project(new THREE.Vector3(PIVL[0], PIVL[1], z)), b = project(new THREE.Vector3(PIVL[0], PIVL[1], zTip)), e = project(new THREE.Vector3(PIVL[0], PIVL[1], z + .22));
  const w = .055 * fpx() / a[2], dx = b[0] - e[0], dy = b[1] - e[1], L = Math.hypot(dx, dy) || 1, nx = -dy / L, ny = dx / L;
  c.save(); if (blur > .4) c.filter = `blur(${blur.toFixed(1)}px)`;
  const g = c.createLinearGradient(e[0] + nx * w, e[1] + ny * w, e[0] - nx * w, e[1] - ny * w); g.addColorStop(0, '#FFF1C8'); g.addColorStop(.5, '#C9A15A'); g.addColorStop(1, '#6B4E22');
  c.fillStyle = g; c.beginPath(); c.moveTo(e[0] + nx * w * .5, e[1] + ny * w * .5); c.lineTo(b[0], b[1]); c.lineTo(e[0] - nx * w * .5, e[1] - ny * w * .5); c.closePath(); c.fill();
  c.fillStyle = '#2a1a0c'; c.beginPath(); c.ellipse(lerp(e[0], b[0], .12), lerp(e[1], b[1], .12), w * .14, w * .42, Math.atan2(dy, dx) + Math.PI / 2, 0, TAU); c.fill();
  const gl2 = c.createRadialGradient(b[0], b[1], 0, b[0], b[1], w * 3); gl2.addColorStop(0, 'rgba(255,230,170,.7)'); gl2.addColorStop(1, 'rgba(255,200,120,0)'); c.fillStyle = gl2; c.globalCompositeOperation = 'lighter'; c.fillRect(b[0] - w * 3, b[1] - w * 3, w * 6, w * 6);
  c.restore();
}

// ───────────────────────── air: dust in the lamp light ─────────────────────────
const MOTES = Array.from({ length: 220 }, (_, i) => ({ x: (hash(i, 1) - .5) * 40, y: (hash(i, 2) - .5) * 30 - 2, z: hash(i, 3) * 26 - 14, r: .012 + hash(i, 4) * .03, ph: hash(i, 5) * 100 }));
export function drawMotes(c, t, cs, k = 1) {
  if (k <= 0) return; const f = fpx(); c.save(); c.globalCompositeOperation = 'lighter';
  for (const m of MOTES) {
    const p = new THREE.Vector3(m.x + noise3(m.ph, t * .07, 1) * 1.6, m.y + noise3(m.ph, t * .07, 2) * 1.6, m.z + noise3(m.ph, t * .05, 3) * 1.2 + t * .03);
    const v = p.clone().project(camera); if (v.z > 1 || v.z < -1 || Math.abs(v.x) > 1.1 || Math.abs(v.y) > 1.1) continue;
    const d = camera.position.distanceTo(p); if (d < .6) continue;
    const coc = clamp(cs.ap * Math.abs(1 - cs.focus / d) * (H / 1080), 0, 34), r0 = m.r * f / d, r = Math.max(.7, r0) + coc * .9;
    const vis = clamp((r0 + coc * .5 - 1.2) / 2.5); if (vis <= 0) continue;   // far, pin-sharp specks read as dirt on the paper: only soft bokeh survives
    const lamp = clamp(1 - Math.hypot(p.x - LAMP.x, p.y - LAMP.y) / 26), a = vis * k * (.05 + .55 * lamp) * Math.min(1, 2.2 / (1 + coc * .35)) * (.6 + .4 * Math.sin(t * 1.3 + m.ph));
    if (a < .01) continue; const sx = (v.x + 1) / 2 * W, sy = (1 - v.y) / 2 * H;
    const g = c.createRadialGradient(sx, sy, 0, sx, sy, r); g.addColorStop(0, `rgba(255,214,160,${(a * .9).toFixed(3)})`); g.addColorStop(.55, `rgba(255,200,140,${(a * .35).toFixed(3)})`); g.addColorStop(1, 'rgba(255,190,130,0)');
    c.fillStyle = g; c.fillRect(sx - r, sy - r, r * 2, r * 2);
  }
  c.restore();
}
const beam = mk(W, H); {
  const x = beam.getContext('2d'); x.globalCompositeOperation = 'lighter';
  for (let i = 0; i < 3; i++) { x.save(); x.translate(-W * .08, -H * .25); x.rotate(.62 + i * .05);
    const g = x.createLinearGradient(0, -H * .2, 0, H * .2); g.addColorStop(0, 'rgba(255,200,140,0)'); g.addColorStop(.5, `rgba(255,205,150,${[.05, .035, .025][i]})`); g.addColorStop(1, 'rgba(255,200,140,0)');
    const g2 = x.createLinearGradient(0, 0, W * 1.5, 0); x.fillStyle = g; x.fillRect(0, -H * (.12 + i * .06), W * 1.6, H * (.24 + i * .12)); x.restore(); }
  x.globalCompositeOperation = 'destination-out'; const f = x.createLinearGradient(0, 0, W, H); f.addColorStop(0, 'rgba(0,0,0,0)'); f.addColorStop(.75, 'rgba(0,0,0,.85)'); f.addColorStop(1, 'rgba(0,0,0,1)'); x.fillStyle = f; x.fillRect(0, 0, W, H);
}
export function drawBeam(c, k = 1) { if (k <= 0) return; c.save(); c.globalAlpha = k; c.globalCompositeOperation = 'lighter'; c.drawImage(beam, 0, 0); c.restore(); }

// ───────────────────────── render ─────────────────────────
function only(objs) { scene.traverse(o => { if (o.isMesh || o.isGroup) o.visible = false; }); objs.forEach(o => { o.visible = true; o.traverseAncestors(a => a.visible = true); o.traverse(d => d.visible = true); }); }
function pass(c, objs, blur) {
  only(objs); R.toneMapping = THREE.NoToneMapping; R.setClearColor(0x000000, 0); R.clear(); R.render(scene, camera);
  if (blur > 7) { const L = layer('dof', W / 2, H / 2); L.filter = `blur(${(blur / 2).toFixed(1)}px)`; L.drawImage(R.domElement, 0, 0, W / 2, H / 2); c.drawImage(L.canvas, 0, 0, W, H); }
  else { c.save(); if (blur > .35) c.filter = `blur(${blur.toFixed(1)}px)`; c.drawImage(R.domElement, 0, 0, W, H); c.restore(); }
}
const bgCanvas = mk(W, H); {
  const x = bgCanvas.getContext('2d'), g = x.createRadialGradient(W * .38, H * .3, 0, W * .5, H * .5, W * .8);
  g.addColorStop(0, '#2b251e'); g.addColorStop(.45, '#191713'); g.addColorStop(1, '#0b0a08'); x.fillStyle = g; x.fillRect(0, 0, W, H);
}
// renderWorld(c, t, o): draws the whole 3D frame. o.lift: extra per-page brightness tweak; returns camera info for overlays
export function renderWorld(c, t, o = {}) {
  const cs = setCamera(t), occ = layout(t);
  c.drawImage(bgCanvas, 0, 0);
  const coc = d => clamp(cs.ap * Math.abs(1 - cs.focus / d) * (H / 1080), 0, 26);
  // depth of field: each page is focused at the point where the camera's line of sight meets its plane (clamped to the page)
  const dir = new THREE.Vector3(); camera.getWorldDirection(dir);
  const hitOn = (z, obj, hw, hh) => { if (Math.abs(dir.z) < 1e-4) return null; const k = (z - camera.position.z) / dir.z; if (k <= 0) return null;
    const P = camera.position.clone().addScaledVector(dir, k); if (!obj) return P; const L = obj.worldToLocal(P.clone()); L.x = clamp(L.x, -hw, hw); L.y = clamp(L.y, -hh, hh); L.z = 0; return obj.localToWorld(L); };
  const dist = (P, fb) => P ? camera.position.distanceTo(P) : fb;
  const items = [{ z: DESK_Z, objs: [desk.g], d: dist(hitOn(DESK_Z), 80), kind: 'desk' }];
  pages.forEach(p => { const ctr = p.g.localToWorld(new THREE.Vector3(0, 0, 0)); items.push({ z: p.z, objs: [p.g], d: dist(hitOn(p.z, p.g, PW * PX / 2, PH * PX / 2), camera.position.distanceTo(ctr)), kind: 'page', p }); });
  Object.values(cards).forEach(cd => { if (cd.pose) items.push({ z: cd.z, objs: [cd.g], d: camera.position.distanceTo(cd.g.position), kind: 'card' }); });
  const zc = camera.position.z; items.sort((a, b) => Math.abs(zc - b.z) - Math.abs(zc - a.z));
  // page tint: lower pages sit deeper in the stack's shade
  pages.forEach(p => { const k = 1 - clamp(-p.z / 12) * .14; p.sheets.forEach(sh => sh.mesh.material.color.setScalar(k)); });
  const th = threadState(t), focusZ = (() => { const f = focusAt(t); return lerp(pages[Math.floor(f)].z, pages[Math.min(4, Math.floor(f) + 1)].z, f - Math.floor(f)); })();
  const segBlur = z => coc(camera.position.distanceTo(new THREE.Vector3(PIVL[0], PIVL[1], z)));
  const glint = seg(t, TL.stitchA, TL.stitchA + .3) * (1 - seg(t, TL.stitch(5), TL.stitch(5) + .8));
  const needleOn = th.lead > 0 && t < TL.stitch(5) + .9, needleA = 1 - seg(t, TL.stitch(5) + .3, TL.stitch(5) + .9);
  const levels = [DESK_Z, ...pages.map(p => p.z)].sort((a, b) => a - b);
  const below = z => { let r = DESK_Z; for (const l of levels) if (l < z - 1e-4) r = l; return r; };
  const strand = (lo, hi) => {   // the thread between two heights (+ the needle if it leads inside this span)
    if (th.lead <= 0) return; const a = Math.max(lo, th.zLead), b = Math.min(hi, th.zs[0]);
    if (b > a + 1e-3) drawThread(c, b, a, segBlur((a + b) / 2), glint);
    if (needleOn && th.zLead >= lo - 1e-3 && th.zLead <= hi + 1e-3) { c.save(); c.globalAlpha *= needleA; drawNeedle(c, th.zLead, Math.max(th.zLead - .75, below(th.zLead) + .01), segBlur(th.zLead)); c.restore(); }
  };
  const lower = items.filter(it => it.z <= zc).sort((a, b) => a.z - b.z), upper = items.filter(it => it.z > zc).sort((a, b) => b.z - a.z);
  let prev = -Infinity;
  for (const it of lower) { if (it.kind !== 'card') { strand(prev, it.z); prev = it.z; } pass(c, it.objs, coc(it.d)); }
  strand(prev, zc);
  prev = Infinity; const ups = [];
  for (const it of upper) { if (it.kind !== 'card') { strand(it.z, prev); prev = it.z; } pass(c, it.objs, coc(it.d)); }
  strand(zc, prev);
  return { ...cs, focusZ };
}
