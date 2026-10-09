/**
 * Which agy processes are running right now.
 *
 * `agy plugin install` deletes the caddis plugin folder and then copies the new files in. A running
 * agy holds that folder open, so the delete can succeed while the copy fails, and the plugin is left
 * EMPTY (v1.3.136, 2026-10-08: eight headless agy lanes lost about 25 minutes). The installer asks
 * here first and refuses while any agy runs.
 */
import { run } from './exec.js';

/** PIDs of every `agy.exe` row in `tasklist /FO CSV /NH` output. Other programs and the "no tasks" line are ignored. */
export function parseTasklistCsv(stdout: string): number[] {
  const pids: number[] = [];
  for (const line of stdout.split(/\r?\n/)) {
    const match = /^"agy\.exe","(\d+)"/i.exec(line.trim());
    if (match) pids.push(Number(match[1]));
  }
  return pids;
}

/** PIDs from `pgrep -x agy` output: one number per line, anything else skipped. */
export function parsePgrep(stdout: string): number[] {
  return stdout
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => /^\d+$/.test(line))
    .map(Number);
}

/**
 * Running agy PIDs, or an empty list. A failed lookup returns an empty list on purpose: the check is a
 * safety net, and a missing `tasklist` must not stop an install. (`run` never throws.)
 */
export async function listAgyPids(): Promise<number[]> {
  if (process.platform === 'win32') {
    const result = await run('tasklist', ['/FI', 'IMAGENAME eq agy.exe', '/FO', 'CSV', '/NH'], { timeout: 20_000 });
    return result.ok ? parseTasklistCsv(result.stdout) : [];
  }
  const result = await run('pgrep', ['-x', 'agy'], { timeout: 10_000 });
  return result.ok ? parsePgrep(result.stdout) : [];
}
