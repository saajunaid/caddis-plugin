/** `claude-deepseek [claude args...]` — the DeepSeek lane. Every argument belongs to claude. */
import { laneMain } from './launch.js';

process.exitCode = await laneMain('deepseek', process.argv.slice(2));
