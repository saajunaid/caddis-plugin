/**
 * `claude-oss <provider> [claude args...]` — a Claude Code session on any OSS provider.
 * Installed on PATH by `npm i -g @caddis/cli`; no shell profile edit, no script copying.
 */
import { laneMain } from './launch.js';

process.exitCode = await laneMain(undefined, process.argv.slice(2));
