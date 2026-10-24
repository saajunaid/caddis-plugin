/**
 * Append one JSON line to a shared file, never interleaved (R34).
 *
 * The hub is the only writer of `requests.jsonl` and `audit.jsonl`: the single-instance lock (L25) holds one hub
 * process per machine. Inside that process, one promise chain per file runs the appends one at a time. Each line is
 * one `write` on a file opened in append mode, so it lands whole at the end. A tail with no newline can only come
 * from a writer that died mid-line: it is closed with a newline first, so it stays one bad line (intake rejects
 * it) and never joins the new line. This is the rule of `append_request` in `caddis_coordinate.py`.
 */
import { mkdir, open } from 'node:fs/promises';
import path from 'node:path';

const chains = new Map<string, Promise<void>>();
/** Windows can refuse an open for a moment while another process reads the file. */
const RETRY_CODES = new Set(['EBUSY', 'EPERM', 'EACCES']);
const RETRY_FOR_MS = 2_000;

const keyOf = (file: string): string => {
  const abs = path.resolve(file);
  return process.platform === 'win32' ? abs.toLowerCase() : abs;
};

async function writeLine(file: string, line: string): Promise<void> {
  await mkdir(path.dirname(file), { recursive: true });
  const deadline = Date.now() + RETRY_FOR_MS;
  for (;;) {
    try {
      // 'a+': read the last byte, write at the end. Mode 0600 applies when the file is created.
      const fh = await open(file, 'a+', 0o600);
      try {
        const { size } = await fh.stat();
        let prefix = '';
        if (size > 0) {
          const last = Buffer.alloc(1);
          await fh.read(last, 0, 1, size - 1);
          if (last[0] !== 0x0a) prefix = '\n';
        }
        await fh.write(`${prefix}${line}\n`);
        await fh.sync();
      } finally {
        await fh.close();
      }
      return;
    } catch (e) {
      const code = (e as NodeJS.ErrnoException).code ?? '';
      if (process.platform !== 'win32' || !RETRY_CODES.has(code) || Date.now() >= deadline) throw e;
      await new Promise((r) => setTimeout(r, 20));
    }
  }
}

/** Append `line` plus a newline to `file`. The line must hold no newline. Calls for one file run in order. */
export function appendLine(file: string, line: string): Promise<void> {
  if (line.includes('\n') || line.includes('\r')) return Promise.reject(new Error('a line must hold no newline'));
  const key = keyOf(file);
  const prev = chains.get(key) ?? Promise.resolve();
  const next = prev.catch(() => undefined).then(() => writeLine(file, line));
  chains.set(key, next);
  const clear = (): void => {
    if (chains.get(key) === next) chains.delete(key);
  };
  next.then(clear, clear);
  return next;
}
