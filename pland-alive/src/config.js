// config.js — the parameters agreed in step 0 (the parameter card, STORYBOARD.md). Single source of truth:
// the browser engine reads window.PROJECT, and music/score.mjs reads module.exports.
const B = 60 / 110;                    // one beat at 110 bpm
const PROJECT = {
  title: 'pland-alive',
  style: ['16-ui-layers-2.5d'],
  format: '16x9',
  width: 1920, height: 1080,
  fps: 30,
  drawFps: null,
  duration: 163 * B,                   // 88.91 s, end card included
  bpm: 110,
  beatOffset: 0,
  bg: '#12110e',
  fonts: [
    { family: 'Newsreader', weights: [500, 600], italic: true },
    { family: 'Inter', weights: [300, 400, 500, 600, 700] },
    { family: 'Noto Sans TC', weights: [500, 700] },
    { family: 'Noto Serif TC', weights: [500, 600] },
    { family: 'JetBrains Mono', weights: [400, 500, 600, 700] },
    { family: 'Space Grotesk', weights: [700] },      // end card wordmark
  ],
  chars: '↑↵⇧⌘▾⌄✓★●○◐◓◑◒⚠·—→←…“”‘’',
  post: { grain: .024, vignette: .32 },
  motionBlur: { samples: 16, shutter: .5 },
  endcard: { on: true, len: 8 * B, theme: { bg: '#12110e', fg: '#ECE8DD', dim: '#8E887B', accent: '#D97757', eye: '#12110e' },
    title: 'Claude Code', line: '> made with Claude Code' },
  audio: 'assets/score.m4a',
  music: {
    preset: 'composed',                // music/score.mjs is this film's own arrangement: felt piano, upright bass, brushes (D major)
    key: 'D',
    seed: 7,
    // picture sounds only: paper, pen, keys, stamps, the pointer, brass. Musical moments are played by the band (score.mjs).
    hits: [
      ...[.62, .78, .9, 1.07, 1.2, 1.36, 1.55, 1.68, 1.86, 2.0, 2.18, 2.33, 2.52, 2.66, 2.83].map(t => ({ t, sfx: 'key', v: .42 })),   // typing
      { t: 6 * B, sfx: 'key', v: .8 },                                                           // Enter
      { t: 11 * B, sfx: 'paper', v: .4 }, { t: 12.5 * B, sfx: 'paper', v: .3 },                 // the deck fans open
      ...[20, 30, 90].map(b => ({ t: (b + .55) * B, sfx: 'paper', v: .42 })),                  // pages swing to the next feature (on the swing itself)
      ...[0, 1, 2, 3, 4].map(i => ({ t: 21.25 * B + i * .32, sfx: 'scratch', v: .28 })),        // the plan writes itself
      { t: 23.5 * B, sfx: 'scratch', v: .45 }, { t: 24.5 * B, sfx: 'scratch', v: .45 },         // ticks
      ...[0, 1, 2, 3, 4].flatMap(i => [{ t: (32.5 + .9 * i) * B - .48, sfx: 'click', v: .32 }, { t: (32.5 + .9 * i) * B - .42, sfx: 'flick', v: .2 }, { t: (32.5 + .9 * i) * B, sfx: 'paper', v: .34 }]),   // you add each bot (+ New bot): it pops out of the slot, flips, lands
      { t: 37.25 * B, sfx: 'click', v: .55 }, { t: 37.5 * B, sfx: 'flick', v: .22 },           // the lead's thinking chip; the card stands up
      { t: 39.75 * B, sfx: 'paper', v: .26 }, { t: 46 * B, sfx: 'paper', v: .2 }, { t: 46.75 * B, sfx: 'paper', v: .22 },   // HKGAI card out, back, both down
      ...[48.5, 49.25, 50].flatMap(b => [{ t: b * B - .62, sfx: 'flick', v: .18 }, { t: b * B, sfx: 'paper', v: .26 }]),   // the lead's tasks drop into To do
      ...[[52, 53.5], [52.5, 54], [77.25, 78.75]].flatMap(([a, l]) => [{ t: a * B, sfx: 'flick', v: .4 }, { t: a * B + .03, sfx: 'plane', v: .32, len: (l - a) * B },
        { t: l * B, sfx: 'paper', v: .3 }]),                                                     // delegation slips: writer and coder at once, later the reviewer
      ...[67.25, 70, 73.8, 76.5, 81.25].flatMap(b => [{ t: b * B - .62, sfx: 'flick', v: .2 }, { t: b * B, sfx: 'paper', v: .32 }]),   // board cards lift and land
      { t: 67.25 * B + .02, sfx: 'stamp', v: .55 },                                              // FAILED
      ...[70, 76.5, 81.25].map(b => ({ t: b * B + .03, sfx: 'stamp', v: .28 })),                 // DONE
      { t: 70.25 * B, sfx: 'flick', v: .38 }, { t: 70.25 * B + .03, sfx: 'plane', v: .3, len: 1.5 * B }, { t: 71.75 * B, sfx: 'paper', v: .34 },   // report.md back to the lead's inbox
      { t: 81.5 * B, sfx: 'stamp', v: .65 },                                                     // PASS
      ...[0, 1, 4].map(i => ({ t: (92 + i * .9) * B, sfx: 'key', v: .25 })),                   // tool calls
      { t: 95 * B, sfx: 'thud', v: .7 }, { t: 95 * B + .02, sfx: 'stamp', v: .85 },            // the rogue command hits the wall: DENIED
      { t: 98 * B + .1, sfx: 'flick', v: .3 },                                                   // the permission card appears
      { t: 100.5 * B, sfx: 'plane', v: .34, len: 3.2 * B },                                      // ... and rises to the top
      { t: 107 * B, sfx: 'click', v: .7 }, { t: 107 * B + .03, sfx: 'stamp', v: .85 },        // Allow once: ALLOWED
      { t: 111.5 * B, sfx: 'plane', v: .22, len: 2.6 * B },                                      // a foreign page drifts in
      { t: 114.75 * B, sfx: 'tink', v: .8 }, { t: 114.75 * B + .05, sfx: 'stamp', v: .8 },     // the needle strikes the brass: 403
      { t: 118.5 * B + 1.6, sfx: 'thud', v: .28 },                                               // ... and lands on the desk far below
      ...[69.48, 69.71, 69.85, 70.08].map(t => ({ t, sfx: 'paper', v: .38 })),                  // riffle down to Memory
      { t: 126.4 * B, sfx: 'flick', v: .3 }, { t: 130 * B, sfx: 'paper', v: .4 },              // the lesson files in
      ...[75.0, 75.18, 75.35, 75.52].map(t => ({ t, sfx: 'paper', v: .34 })),                  // the deck closes
      { t: 143 * B, sfx: 'stamp', v: 1 },                                                        // the seal
    ],
    sections: [{ at: 0, energy: .3 }, { at: 8 * B, energy: .55 }, { at: 20 * B, energy: .85 }, { at: 30 * B, energy: .8 }, { at: 56 * B, energy: .7 },
      { at: 65 * B, energy: .9 }, { at: 90 * B, energy: .85 }, { at: 110 * B, energy: .75 }, { at: 126 * B, energy: 1 }, { at: 139 * B, energy: .5 }, { at: 155 * B, energy: .3 }],
  },
};
if (typeof module !== 'undefined') module.exports = PROJECT; else window.PROJECT = PROJECT;
