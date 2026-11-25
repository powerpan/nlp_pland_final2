// main.js — wires the chapters into one timeline (the whole film is one take inside scenes/world.js), then the end card.
import { shots, start } from './engine.js';
import { SHOTS } from './scenes/shots.js';

shots(SHOTS);   // the last chapter is the Claude Code end card, built from the PlanD seal (scenes/shots.js)
start();
