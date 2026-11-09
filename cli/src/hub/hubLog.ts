/**
 * `~/.caddis/hub/hub.log`: one timestamped line per self-update or restart step.
 * A hub started by `caddis hub start` or autostart has no console (stdio ignored), so stderr alone is lost.
 * The file stays small: past 256 KB it moves to `hub.log.1` (one old copy) and a new file starts.
 */
import { appendFileSync, mkdirSync, renameSync, statSync } from 'node:fs';
import path from 'node:path';
import { logPath } from './paths.js';

export const LOG_MAX_BYTES = 256 * 1024;

/** Append `text` to the hub log and write it to stderr. Never throws. */
export function hubLog(text: string, home?: string, now: () => number = Date.now): void {
  try {
    process.stderr.write(`${text}\n`);
  } catch {
    /* no console */
  }
  const file = logPath(home);
  try {
    mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
    try {
      if (statSync(file).size > LOG_MAX_BYTES) renameSync(file, `${file}.1`);
    } catch {
      /* no log yet, or the rename lost a race: keep appending */
    }
    appendFileSync(file, `${new Date(now()).toISOString()} ${text.replace(/[\r\n]+/g, ' ')}\n`, { mode: 0o600 });
  } catch {
    /* a log that cannot be written must never stop the hub */
  }
}
