// music/score.mjs — the film's own score, composed for the picture (not a looped preset), synthesized from scratch.
// "The logbook at night", extended for "A Team You Can Watch": felt piano, a plucked upright bass and brushes, in D major with
// jazz voicings. Every note is humanised (timing ±7 ms, velocity ±15 %, chords rolled), the bass walks, the drums swing, and
// the story beats are played by the band: the needle's stitches climb the chord, the bots are introduced one note each, the
// band stops when a task fails and comes back on the retry, "188 passed" and the push are arpeggios, the guard holds a pedal.
// Picture sounds (src/config.js music.hits) are paper, pen and stamps rather than synthetic blips.
//   node music/score.mjs            → music/score.wav and assets/score.m4a (loudness-normalised to -14 LUFS with ffmpeg)
// I can't listen: verify with the spectrogram and node music/levels.mjs, and say so.
import { createRequire } from 'node:module';
import { writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
const require = createRequire(import.meta.url);
const P = require('../src/config.js'), M = P.music || {};
const SR = 44100, LEN = P.duration, TAIL = 2.2, N = Math.ceil(SR * (LEN + TAIL)), TAU = Math.PI * 2;
const BPM = P.bpm || 110, BEAT = 60 / BPM, BAR = BEAT * 4, at = b => b * BEAT;
const L = new Float32Array(N), R = new Float32Array(N), sL = new Float32Array(N), sR = new Float32Array(N), mL = new Float32Array(N), mR = new Float32Array(N);
const duck = new Float32Array(N).fill(1);
let seed = (M.seed ?? 7) * 7919 + 1; const rnd = () => { seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
const mtof = m => 440 * Math.pow(2, (m - 69) / 12);
const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const hum = (t, ms = 7) => t + (rnd() - .5) * 2 * ms / 1000;          // a player is never exactly on the grid
const vel = (v, k = .15) => v * (1 - k + 2 * k * rnd());

function put(t0, len, gen, { gain = 1, pan = 0, rev = 0, bus = 'drum' } = {}) {
  if (t0 >= LEN + TAIL) return;
  const i0 = Math.max(0, Math.floor(t0 * SR)), i1 = Math.min(N, Math.floor((t0 + len) * SR));
  const gl = gain * Math.cos((pan + 1) * Math.PI / 4), gr = gain * Math.sin((pan + 1) * Math.PI / 4), BL = bus === 'mus' ? mL : L, BR = bus === 'mus' ? mR : R;
  for (let i = i0; i < i1; i++) { const v = gen(Math.max(0, i / SR - t0)); if (!Number.isFinite(v)) continue; BL[i] += v * gl; BR[i] += v * gr; sL[i] += v * gl * rev; sR[i] += v * gr * rev; }
}
function noise(t0, len, env, filt, o = {}) {   // state-variable filtered noise
  let lp = 0, bp = 0;
  put(t0, len, tt => { const n = rnd() * 2 - 1, [fc, q0] = filt(tt), q = Math.max(q0, .45), f = Math.min(.85, 2 * Math.sin(Math.PI * Math.min(fc, SR / 7) / SR));
    lp += f * bp; const hp = n - lp - q * bp; bp += f * hp; return env(tt) * (o.hp ? hp : o.lp ? lp : bp); }, o);
}

// ───────── the band ─────────
// felt piano: two slightly detuned strings, soft hammer, warm partials that die faster than the fundamental, damper release
function felt(t, m, len, v = 1, pan = 0) {
  const f = mtof(m), br = clamp(.6 + v * .5, .5, 1.1);
  put(t, len + 1.6, tt => { const a = Math.min(1, tt / .008), d = Math.exp(-tt * (.9 + f / 1100)), r = tt > len ? Math.exp(-(tt - len) * 7) : 1;
    const s = Math.sin(TAU * f * tt) + .7 * Math.sin(TAU * f * 1.0016 * tt + 1.3) + br * .3 * Math.sin(TAU * 2.002 * f * tt) * Math.exp(-tt * 2.6) + br * .1 * Math.sin(TAU * 3.006 * f * tt) * Math.exp(-tt * 5);
    return v * .075 * a * d * r * s; }, { gain: .85, pan, rev: .32, bus: 'mus' });
  noise(t, .04, tt => v * .06 * Math.exp(-tt * 110), () => [700 + f * .8, .7], { gain: .4, pan, lp: true });   // the felt hammer
}
// a chord, rolled bottom-up like a hand does
const roll = (t, notes, len, v, spread = .022) => notes.forEach((m, i) => felt(hum(t + i * spread * (.7 + .6 * rnd()), 4), m, len, vel(v * (i ? .8 : 1), .12), (i / Math.max(1, notes.length - 1) - .5) * .5));
// upright bass: plucked string, a little pitch drop, a body thump, second harmonic
const upright = (t, m, len, v = 1) => { const f = mtof(m);
  put(t, len + .25, tt => { const fr = f * (1 + .01 * Math.exp(-tt * 28)); return v * .42 * (Math.sin(TAU * fr * tt) + .35 * Math.sin(TAU * 2 * fr * tt) * Math.exp(-tt * 6)) * Math.min(1, tt / .005) * Math.exp(-tt * 2.4) * (tt > len ? Math.exp(-(tt - len) * 16) : 1); }, { gain: .75, bus: 'mus' });
  noise(t, .05, tt => v * .12 * Math.exp(-tt * 70), () => [500, .6], { gain: .5, lp: true }); };
// brushes: a swept snare (2 & 4), taps on the swung eighths, an occasional ghost; a soft felt kick
const brushSweep = (t, v = 1) => noise(t, .34, tt => v * .2 * Math.min(1, tt / .06) * Math.exp(-tt * 8.5), tt => [1900 + 1400 * Math.exp(-tt * 8), .55], { gain: .5, pan: .12, rev: .15 });
const brushTap = (t, v = 1) => noise(t, .1, tt => v * .16 * Math.min(1, tt / .006) * Math.exp(-tt * 34), () => [5200 + 1200 * rnd(), .6], { gain: .42, pan: .3, hp: true });
const kick = (t, v = 1) => { put(t, .45, tt => v * Math.sin(TAU * (52 * tt + 70 * (1 - Math.exp(-tt * 26)) / 26)) * Math.exp(-tt * 9) * Math.min(1, tt / .004), { gain: .55 });
  const i0 = Math.floor(t * SR); for (let i = 0; i < SR * .22 && i0 + i < N; i++) duck[i0 + i] = Math.min(duck[i0 + i], 1 - .16 * v * Math.exp(-i / SR * 14)); };
const swell = (t, len, v = 1) => noise(t - len, len + .15, tt => v * .1 * Math.pow(clamp(tt / len), 2.6) * (tt > len ? Math.exp(-(tt - len) * 30) : 1), tt => [3200 + 1800 * clamp(tt / len), .7], { gain: .45, rev: .35 });   // a brush crescendo on the cymbal, not a synth sweep

// ───────── the chart ─────────
// chords: bass root + right-hand voicing (close, around middle C), one per bar; bar = 4 beats at 110 bpm, the picture's grid
const CH = {
  Dmaj9: { root: 38, rh: [64, 66, 69, 73] }, 'D/F#': { root: 42, rh: [62, 64, 66, 69] }, Bm9: { root: 47, rh: [57, 61, 62, 66] }, Gmaj9: { root: 43, rh: [59, 62, 66, 69] },
  A7sus: { root: 45, rh: [62, 64, 67, 71] }, A13: { root: 45, rh: [61, 66, 67, 71] }, 'F#m7': { root: 42, rh: [57, 61, 64, 69] }, Em9: { root: 40, rh: [55, 59, 62, 66] },
};
const BARS = ['Dmaj9', 'Bm9',                                       // 0–1   one line
  'Gmaj9', 'A7sus', 'Dmaj9',                                             // 2–4   the reveal · the stitches
  'Gmaj9', 'A13', 'F#m7',                                                // 5–7   plan
  'Bm9', 'Gmaj9', 'Em9', 'A13',                                          // 8–11  Bot Mode: roll call · the lead's thinking level (HKGAI's new levels on bar 10)
  'Dmaj9', 'Bm9',                                                        // 12–13 the lead splits the goal · two slips at once
  'Gmaj9', 'Em9',                                                        // 14–15 faces
  'A13', 'F#m7', 'Em9', 'A13', 'Dmaj9', 'Bm9',                           // 16–21 board: the failure (16–17), the retry, the dones, PASS (20)
  'A13', 'Dmaj9', 'Bm9',                                                 // 22–24 sandbox (188 passed on bar 24's downbeat)
  'Gmaj9', 'A13', 'D/F#',                                                // 25–27 the card rises, docks, is allowed; pushed
  'Em9', 'F#m7', 'Em9', 'A7sus',                                         // 28–31 the guard: a held pedal, the 403, the fall, the thread that never moved
  'Gmaj9', 'Em9', 'A13', 'A7sus',                                        // 32–35 memory · the deck closes · the answer · the seal (beat 143)
  'Dmaj9', 'Gmaj9', 'Bm9', 'Dmaj9', 'Dmaj9'];                            // 36–40 the title holds · end card (beat 155) · ring out
const chordAt = t => CH[BARS[clamp(Math.floor(t / BAR), 0, BARS.length - 1)]];
// the bar's feel: drums 0 none / 1 sweeps / 2 full groove; bass 0 none / 1 half notes / 2 walking / 3 pedal
const FEEL = b => b <= 1 ? { dr: 0, bass: 0, comp: 'intro' } : b <= 3 ? { dr: 0, bass: 1, comp: 'long' } : b === 4 ? { dr: 1, bass: 1, comp: 'long' }
  : b === 9 || b === 10 || b === 14 || b === 15 ? { dr: 1, bass: 2, comp: 'faces' } : b === 28 || b === 29 ? { dr: 1, bass: 3, comp: 'guard' } : b === 30 || b === 31 ? { dr: 0, bass: 1, comp: 'long' }
  : b <= 27 ? { dr: 2, bass: 2, comp: 'groove' } : b <= 34 ? { dr: 2, bass: 2, comp: 'lift' } : b === 35 ? { dr: 0, bass: 1, comp: 'long' } : { dr: 0, bass: 1, comp: 'end' };
// the failure: the band stops on the stamp (beat 67.25) and comes back with the writer's done (beat 70)
const STOP = [67.25 * 60 / (P.bpm || 110), 69.75 * 60 / (P.bpm || 110)], stopped = t => t > STOP[0] - .02 && t < STOP[1];
const COMP = [[[0, 1.7], [2.5, 1.3]], [[0, .9], [1.5, .45], [2.5, 1.3]], [[.5, 1.4], [2, 1.8]], [[0, 1.4], [1.5, .4], [3, .8]]];
const SW = .1 * BEAT;   // swing on the off-beat eighths
const end = LEN - BEAT * .5;

for (let b = 0; b < BARS.length; b++) {
  const t = b * BAR; if (t >= end) break;
  const c = CH[BARS[b]], nx = CH[BARS[Math.min(BARS.length - 1, b + 1)]], F = FEEL(b);
  // piano, left hand: the root in the tenor register, only when the bass isn't walking (two instruments on one low note is mud)
  if (F.bass !== 2) felt(hum(t), c.root < 45 ? c.root + 12 : c.root, BAR * .95, vel(.5), -.25);
  // piano, right hand
  if (F.comp === 'faces') { roll(t, c.rh, BAR * .9, .34, .03); }   // the faces: sustained, quiet; the darting figure is played on top (below)
  else if (F.comp === 'guard') { felt(hum(t), c.rh[3] + 12, BAR * .9, .3, .35); felt(hum(t + at(2.5)), c.rh[1] + 12, BAR * .5, .24, -.3); }
  else if (F.comp === 'intro') { roll(t + (b ? 0 : .25), c.rh, BAR * 1.25, .85, .045); felt(hum(t + at(2.5)), c.rh[3] + 12, BAR * .6, .5, .3);
    if (b === 1) { upright(hum(t, 5), c.root, BAR * .9, .7); felt(hum(t + at(1.5)), c.rh[2] + 12, BEAT * 1.4, .45, .3); } }
  else if (F.comp === 'long') roll(t, c.rh, BAR * .92, .5, .03);
  else if (F.comp === 'groove' || F.comp === 'lift') for (const [o, d] of COMP[(b * 7 + 3) % COMP.length]) { const tt = t + at(o) + (o % 1 ? SW : 0); if (!stopped(tt)) roll(tt, c.rh, at(d), F.comp === 'lift' ? .6 : .5, .016); }
  // bass
  if (F.bass === 1) { upright(hum(t, 5), c.root, BAR * .48, vel(.8)); upright(hum(t + at(2), 5), c.root + 7, BAR * .45, vel(.6)); }
  if (F.bass === 2) { const walk = [c.root, c.root + (rnd() < .5 ? 7 : 4), c.root + (rnd() < .5 ? 9 : 12), nx.root + (rnd() < .5 ? -1 : 1)];
    walk.forEach((m, i) => { const tt = t + at(i) + .008; if (!stopped(tt)) upright(hum(tt, 6), m < 33 ? m + 12 : m > 52 ? m - 12 : m, BEAT * .85, vel(i ? .62 : .78)); }); }
  if (F.bass === 3) [0, 1, 2, 3].forEach(i => upright(hum(t + at(i), 5), 33, BEAT * .9, vel(i ? .5 : .66)));   // a held pedal on A: the guard waits
  // drums
  const sv = F.comp === 'guard' ? .5 : F.comp === 'faces' ? .65 : 1;
  if (F.dr >= 1) for (const bt of [1, 3]) { const tt = t + at(bt); if (!stopped(tt)) brushSweep(hum(tt, 6), vel(.82 * sv)); }
  if (F.comp === 'faces') for (let e = 0; e < 8; e += 2) brushTap(hum(t + at(e / 2), 5), vel(.42, .2));
  if (F.dr === 2) {
    for (let e = 0; e < 8; e++) { const tt = t + at(e / 2) + (e % 2 ? SW : 0); if (stopped(tt) || (e % 2 && rnd() < .25)) continue; brushTap(hum(tt, 5), vel(e % 2 ? .45 : .75, .2)); }
    if (!stopped(t)) kick(hum(t, 4), vel(.5)); const k2 = rnd() < .55 ? t + at(2.5) + SW : t + at(2); if (!stopped(k2)) kick(hum(k2, 4), vel(k2 % 1 ? .3 : .38));
    if (rnd() < .3 && !stopped(t + at(3.5))) brushTap(hum(t + at(3.5) + SW, 4), .55);   // a ghost on the "and" of 4
  }
}
// melody: a gentle line on the chord's upper tones, in two-bar phrases with room between them (call, rest, answer)
const PH = { beats: [0, 1, 1.5, 2.5, 4, 5, 5.5, 6.5], dur: [.9, .45, .9, 1.4, .9, .45, .9, 1.6], idx: [3, 2, 1, 2, 2, 1, 0, 1] };
function phrase(b0, v = .55, oct = 12, idx = PH.idx) {
  PH.beats.forEach((bt, i) => { const tt = at(b0 * 4 + bt) + (bt % 1 ? SW : 0), c = chordAt(tt + .01), tones = c.rh.map(m => m + oct).sort((a, b) => a - b);
    felt(hum(tt, 6), tones[clamp(idx[i], 0, 3)], at(PH.dur[i]), vel(v * (i === 0 || i === 4 ? 1.1 : .9), .1), .18); });
}
phrase(5); phrase(12, .5, 12, [2, 3, 2, 1, 3, 2, 1, 0]); phrase(18, .5, 12, [1, 2, 3, 2, 2, 3, 2, 1]); phrase(23, .5, 12, [2, 3, 2, 1, 3, 2, 1, 0]);
phrase(32, .62); phrase(32, .32, 24);                                   // the lift: the line doubled an octave up
// the story, played by the band
const stitch = [14.75, 15.5, 16.25, 17, 17.75], climb = [69, 74, 76, 78, 81];   // the needle climbs Dmaj9 as it goes down
stitch.forEach((bt, i) => felt(hum(at(bt), 3), climb[i], BEAT * 1.2, .55 + i * .04, (i - 2) * .15));
[6.5, 7, 7.5].forEach((bt, i) => felt(hum(at(bt) + (bt % 1 ? SW : 0), 4), [66, 69, 71][i], BEAT * .6, .42, .2));   // the line leaves: a pick-up into the reveal
[62, 66, 69, 71, 74].forEach((m, i) => felt(hum(at(32.5 + .9 * i), 3), m + 12, BEAT * 1.4, .46, -.6 + .3 * i));    // roll call: one note per bot, left to right
[[37.5, 62], [37.62, 66], [37.74, 69]].forEach(([bt, m], i) => felt(hum(at(bt), 2), m + 12, BEAT * 1.6, .32 - i * .03, -.3));   // the lead's thinking card stands up
felt(hum(at(40.75), 2), 81, BEAT * 1.2, .34, .45); felt(hum(at(40.97), 2), 85, BEAT * 1.2, .3, .5);                 // HKGAI's two new levels light up
[[48.5, 78], [49.25, 76], [50, 74]].forEach(([bt, m]) => felt(hum(at(bt), 3), m, BEAT * .9, .4, -.35));              // the lead's tasks drop into To do
felt(hum(at(53.5), 3), 69, BEAT * .9, .42, .4); felt(hum(at(54), 3), 73, BEAT * 1.2, .42, -.1);                     // two slips land at once
[[56.5, -.6], [57.25, .6], [58.5, -.4], [59, .7], [60.5, -.7], [61.25, .5], [62.5, 0], [63.25, .4]].forEach(([bt, pan], i) =>   // the faces: eyes darting
  felt(hum(at(bt), 4), [81, 78, 81, 76, 78, 74, 81, 78][i], BEAT * .3, .3, pan));
felt(hum(at(67.25), 2), 30, BAR * .8, .55, 0); felt(hum(at(67.25) + .01, 2), 54, BEAT * 2, .4, -.2); felt(hum(at(67.25) + .03, 2), 57, BEAT * 2, .36, .2);   // FAILED: the band stops
upright(at(67.25), 30, BEAT * 1.6, .8); swell(at(70), 1.1, .4); kick(at(70), .6);                                     // ... and comes back with the writer's done
[[70, 69], [76.5, 73], [81.25, 76]].forEach(([bt, m]) => felt(hum(at(bt), 2), m + 12, BEAT * 1.6, .44, .3));         // three dones, rising
const arp = (t, v = .5, up = 24, n = 6) => { const c = chordAt(t + .02), tones = [...c.rh.map(m => m + up - 12), ...c.rh.map(m => m + up)].sort((a, b) => a - b).slice(0, n);
  tones.forEach((m, i) => felt(hum(t + i * .07, 3), m, .9, v * (1 - i * .06), (i / n - .5) * .7)); };
arp(at(81.5), .46, 12);     // PASS
arp(at(96), .5);            // 188 passed
arp(at(108.5), .42, 12);    // pushed
// the guard: the strike is a stopped chord; the card's fall is a falling line that speeds up like gravity
felt(hum(at(114.75), 1), 33, BEAT * 1.5, .5, 0); felt(at(114.75) + .01, 45, BEAT * .9, .4, -.2); felt(at(114.75) + .02, 52, BEAT * .9, .36, .2); kick(at(114.75), .65);
[74, 71, 69, 66, 62, 57].forEach((m, i) => { const tt = at(118.5) + 1.6 * Math.sqrt((i + 1) / 6.2); felt(hum(tt, 2), m, BEAT * .8, .34 - i * .02, -.3 + .1 * i); });
felt(hum(at(139)), 85, BEAT * 3, .5, .2); felt(hum(at(139) + .12), 81, BEAT * 3, .35, -.1);   // the finished answer
// the seal (beat 143): the band anticipates the resolution, a low D under the stamp
roll(at(143), CH.Dmaj9.rh, BAR * 2.2, .55, .03); felt(at(143), 26, BAR * 2, .45, 0); felt(at(143) + .01, 38, BAR * 2, .5, 0); kick(at(143), .7); upright(at(143), 38, BAR * 1.8, .85);
swell(at(14), 1.6, .45); swell(at(104), 1.5, .4);                        // into the fan opening; into the card docking
// end card: the character lands (0.55 s in) on a rolled chord, the terminal types softly; then the last chord rings
if (P.endcard && P.endcard.on !== false) { const e0 = P.endcard.at ?? LEN - (P.endcard.len || 3.2);
  [62, 66, 69, 73, 78].forEach((m, i) => felt(hum(e0 + .55 + i * .06, 2), m, 1.6, .5, (i - 2) * .2));
  for (let i = 0; i < 12; i++) SFXkey(e0 + 1.6 + i * .075 + (rnd() - .5) * .02, .22); }
roll(end, [50, 57, 64, 66, 69, 76], 2.4, .5, .05); upright(end, 38, 2.2, .7);

// ───────── picture sounds ─────────
function SFXkey(t, v = 1) {   // a laptop key: a short muted thock with a little click on top
  const p = .85 + .3 * rnd(); put(t, .05, tt => v * .3 * Math.sin(TAU * 190 * p * tt) * Math.exp(-tt * 90), { gain: .55, pan: (rnd() - .5) * .3 });
  noise(t, .035, tt => v * .35 * Math.exp(-tt * 160), () => [1700 * p, .7], { gain: .5, pan: (rnd() - .5) * .3, lp: true }); }
const SFX = {
  key: SFXkey,
  click: (t, v = 1) => noise(t, .02, tt => v * .5 * Math.exp(-tt * 260), () => [3200, .6], { gain: .5 }),
  paper: (t, v = 1) => { for (let k = 0; k < 5; k++) noise(t + k * .045 + rnd() * .02, .06, tt => v * .35 * Math.exp(-tt * 45), () => [2200 + 1800 * rnd(), .6], { gain: .5, pan: rnd() - .5 }); },
  flick: (t, v = 1) => noise(t, .04, tt => v * .6 * Math.exp(-tt * 140), () => [3800, .6], { gain: .5 }),
  plane: (t, v = 1, len = .55) => noise(t, len, tt => v * .24 * Math.sin(Math.PI * clamp(tt / len)), tt => [1200 + 2200 * tt / len, .55], { gain: .5, rev: .3 }),
  scratch: (t, v = 1) => { for (let k = 0; k < 7; k++) noise(t + k * .04 + rnd() * .01, .025, tt => v * .22 * Math.exp(-tt * 120), () => [4800 + 1500 * rnd(), .7], { gain: .45, pan: .2 }); },
  stamp: (t, v = 1) => { put(t, .22, tt => v * .5 * Math.sin(TAU * 95 * tt) * Math.exp(-tt * 24), { gain: .8 }); noise(t, .1, tt => v * .5 * Math.exp(-tt * 42), () => [650, .6], { gain: .6, lp: true }); noise(t + .004, .05, tt => v * .25 * Math.exp(-tt * 90), () => [2600, .6], { gain: .4 }); },
  tink: (t, v = 1) => { [[2380, 1], [3710, .55], [5940, .3]].forEach(([f, a]) => put(t, .9, tt => v * .16 * a * Math.sin(TAU * f * tt) * Math.exp(-tt * (5 + f / 900)) * Math.min(1, tt / .001), { gain: .6, pan: -.25, rev: .4 }));
    noise(t, .015, tt => v * .4 * Math.exp(-tt * 300), () => [6000, .6], { gain: .4, pan: -.25 }); },
  thud: (t, v = 1) => { put(t, .3, tt => v * .45 * Math.sin(TAU * (70 + 40 * Math.exp(-tt * 30)) * tt) * Math.exp(-tt * 16), { gain: .7 }); noise(t, .06, tt => v * .4 * Math.exp(-tt * 70), () => [900, .6], { gain: .5, lp: true }); },
};
for (const h of (M.hits || [])) { const f = SFX[h.sfx]; if (f) f(h.t, h.v ?? 1, h.len); else console.warn('unknown sfx', h.sfx); }

// ───────── mix: gentle duck, reverb, glue, fade, normalise ─────────
for (let i = 0; i < N; i++) { L[i] += mL[i] * duck[i]; R[i] += mR[i] * duck[i]; }
const sections = (M.sections || [{ at: 0, energy: .8 }]).slice().sort((a, b) => a.at - b.at), energyAt = t => { let e = sections[0].energy; for (const s of sections) if (t >= s.at) e = s.energy; return e; };
{ let g = .55 + .45 * energyAt(0); const a = 1 / (SR * .6); for (let i = 0; i < N; i++) { g += ((.55 + .45 * energyAt(i / SR)) - g) * a; L[i] *= g; R[i] *= g; sL[i] *= g; sR[i] *= g; } }
const comb = (d, fb) => { const b = new Float32Array(d); let i = 0, f = 0; return x => { const y = b[i]; f = y * .7 + f * .3; b[i] = x + f * fb; i = (i + 1) % d; return y; }; };
const ap = d => { const b = new Float32Array(d); let i = 0; return x => { const y = b[i], o = -x + y; b[i] = x + y * .5; i = (i + 1) % d; return o; }; };
const mkRev = sp => { const cs = [1116, 1188, 1277, 1356, 1422, 1491, 1557, 1617].map(d => comb(d + sp, .84)), as = [556, 441, 341, 225].map(d => ap(d + sp)); return x => { let s = 0; for (const c of cs) s += c(x); s *= .1; for (const a of as) s = a(s); return s; }; };
const rvL = mkRev(0), rvR = mkRev(23);
for (let i = 0; i < N; i++) { L[i] += rvL(sL[i]) * .85; R[i] += rvR(sR[i]) * .85; }
let pre = 0; for (let i = 0; i < N; i++) pre = Math.max(pre, Math.abs(L[i]), Math.abs(R[i])); const drive = pre > 0 ? .85 / pre : 1;
let peak = 0; for (let i = 0; i < N; i++) { const t = i / SR; let g = Math.min(1, t / .02); if (t > LEN + TAIL - .8) g *= clamp((LEN + TAIL - t) / .8);
  L[i] = Math.tanh(L[i] * drive) * g; R[i] = Math.tanh(R[i] * drive) * g; peak = Math.max(peak, Math.abs(L[i]), Math.abs(R[i])); }
const norm = peak > 0 ? .89 / peak : 1, NS = Math.ceil(SR * (LEN + .8)), buf = Buffer.alloc(44 + NS * 4);
buf.write('RIFF', 0); buf.writeUInt32LE(36 + NS * 4, 4); buf.write('WAVE', 8); buf.write('fmt ', 12); buf.writeUInt32LE(16, 16); buf.writeUInt16LE(1, 20); buf.writeUInt16LE(2, 22);
buf.writeUInt32LE(SR, 24); buf.writeUInt32LE(SR * 4, 28); buf.writeUInt16LE(4, 32); buf.writeUInt16LE(16, 34); buf.write('data', 36); buf.writeUInt32LE(NS * 4, 40);
for (let i = 0; i < NS; i++) { const g = i / SR > LEN + .3 ? clamp((LEN + .8 - i / SR) / .5) : 1; buf.writeInt16LE(Math.round(clamp(L[i] * norm * g, -1, 1) * 32767), 44 + i * 4); buf.writeInt16LE(Math.round(clamp(R[i] * norm * g, -1, 1) * 32767), 46 + i * 4); }
mkdirSync('music', { recursive: true }); writeFileSync('music/score.wav', buf);
console.log(`music/score.wav  ${(NS / SR).toFixed(2)} s  felt piano · upright · brushes  bpm=${BPM}  bars=${BARS.length}  hits=${(M.hits || []).length}`);
if (!existsSync('assets')) mkdirSync('assets');
const LN = 'loudnorm=I=-14:TP=-1.2:LRA=20';   // two-pass linear: keeps the dynamics between quiet and full sections
const m1 = spawnSync('ffmpeg', ['-hide_banner', '-i', 'music/score.wav', '-af', `highpass=f=30,${LN}:print_format=json`, '-f', 'null', '-'], { encoding: 'utf8' });
const js = (() => { try { const t = m1.stderr; return JSON.parse(t.slice(t.lastIndexOf('{'), t.lastIndexOf('}') + 1)); } catch { return null; } })();
const af = js ? `highpass=f=30,${LN}:linear=true:measured_I=${js.input_i}:measured_TP=${js.input_tp}:measured_LRA=${js.input_lra}:measured_thresh=${js.input_thresh}:offset=${js.target_offset}` : `highpass=f=30,${LN}`;
const ff = spawnSync('ffmpeg', ['-y', '-loglevel', 'error', '-i', 'music/score.wav', '-af', af, '-ar', '44100', '-c:a', 'aac', '-b:a', '192k', 'assets/score.m4a'], { stdio: 'inherit' });
console.log(ff.status === 0 ? `assets/score.m4a  (${js ? 'linear two-pass' : 'single-pass'} loudnorm -14 LUFS)` : 'ffmpeg failed: encode assets/score.m4a yourself');
