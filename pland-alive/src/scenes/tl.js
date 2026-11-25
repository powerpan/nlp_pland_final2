// tl.js — the film's clock. Every event is placed on the 110 bpm grid (B = one beat) so cuts, landings and stamps hit the score.
// The first film's chapters keep their beats where they can: S1–S3 are unchanged, S5/S6 move by 12 bars, S7 by 16 bars, so
// their phrasing against the music is unchanged. The flagship Bot Mode section (S4) is new and long; the guard (S6b) is new.
export const B = 60 / 110;
export const at = n => n * B;
export const TL = {
  // S1 · one line (0–8B), in the "Build team" room
  typeA: .55, typeB: 3.0, send: at(6),
  // S2 · the reveal (8–20B)
  s2: at(8), bubbleLand: at(8), lead: at(9), explodeA: at(11), explodeB: at(14),
  stitchA: at(14), stitch: i => at(14 + i * .75), labelsA: at(15.5), labelsB: at(19.5),
  // S3 · plan (20–30B)
  s3: at(20), planItems: at(21.25), planCheck: i => at(23.5 + i), s4: at(30),
  // S4 · Bot Mode (30–90B): roll call, each bot's thinking level, the lead splits the goal, parallel delegation, faces, the board, review
  roll: i => at(32.5 + i * .9),
  chip: at(37.25), menuUp: at(37.5), dsRead: at(38.25), hkOut: at(39.75), hkNew: at(40.75), hkBack: at(46), menuDown: at(46.75),
  split: at(47.75), born: i => at(48.5 + i * .75),
  slip: i => [at(52), at(52.5), at(77.25)][i], slipLand: i => [at(53.5), at(54), at(78.75)][i],
  faces: at(56), board: at(65),
  fail2: at(67.25), done1: at(70), handBack: at(70.25), handLand: at(71.75), redo2: at(73.5), done2: at(76.5), take3: at(78.75), done3: at(81.25), pass: at(81.5),
  // S5 · sandbox (90–100B)
  s5: at(90), logRow: i => at(92 + i * .9), testsA: at(93.5), testsPass: at(96), rogueA: at(93.5), rogueHit: at(95), pushAsk: at(98),
  // S6 · you (100–110B)
  s6: at(100), cardRise: at(100.5), cardDock: at(104), cursorA: at(105), click: at(107), pushed: at(108.5),
  // S6b · the guard (110–126B)
  guard: at(110), fIn: at(111.5), fReach: at(114.5), fHit: at(114.75), fFall: at(118.5), fGone: at(123.5),
  // S7 · memory, close, title (126–149B); the end card follows (149–155B)
  s7: at(126), lessonA: at(126.4), lessonLand: at(130), barsA: at(130.5), closeA: at(137), closeB: at(139), finished: at(139.2), title: at(142), seal: at(143), tagline: at(143.5),
  end: at(155),
};
