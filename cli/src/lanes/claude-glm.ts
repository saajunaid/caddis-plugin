/** `claude-glm [claude args...]` — the GLM lane. Every argument belongs to claude. */
import { laneMain } from './launch.js';

process.exitCode = await laneMain('glm', process.argv.slice(2));
