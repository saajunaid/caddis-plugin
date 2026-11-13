/**
 * Review benchmark scoreboards from `<repo>/evals/results/review-scoreboard.json`.
 * Read on demand for `GET /api/benchmarks`, with an mtime cache keyed by file path (as `readAudit`).
 */
import { readFileSync, realpathSync, statSync } from 'node:fs';
import path from 'node:path';

export const SCOREBOARD_REL_PATH = 'evals/results/review-scoreboard.json';

export interface BenchmarkBoard {
  repo: string;
  path: string;
  board: unknown;
}

type CachedItem =
  | { sig: string; kind: 'board'; entry: BenchmarkBoard }
  | { sig: string; kind: 'error'; error: string };

const cache = new Map<string, CachedItem>();

export function readBenchmarks(repoPaths: string[]): {
  boards: BenchmarkBoard[];
  errors: { repo: string; error: string }[];
} {
  const boards: BenchmarkBoard[] = [];
  const errors: { repo: string; error: string }[] = [];

  for (const repoPath of repoPaths) {
    const resolvedRepo = path.resolve(repoPath);
    const repo = path.basename(resolvedRepo);
    const file = path.join(resolvedRepo, 'evals', 'results', 'review-scoreboard.json');

    let sig: string;
    try {
      const st = statSync(file);
      if (!st.isFile()) {
        cache.delete(file);
        continue;
      }
      sig = `${st.size}:${st.mtimeMs}`;
    } catch (e) {
      cache.delete(file);
      const code = (e as NodeJS.ErrnoException).code;
      if (code === 'ENOENT' || code === 'ENOTDIR') continue;
      errors.push({ repo, error: e instanceof Error ? e.message : String(e) });
      continue;
    }

    const hit = cache.get(file);
    if (hit && hit.sig === sig) {
      if (hit.kind === 'board') boards.push(hit.entry);
      else errors.push({ repo, error: hit.error });
      continue;
    }

    let text: string;
    try {
      const realRepo = realpathSync(resolvedRepo);
      const realFile = realpathSync(file);
      const rel = path.relative(realRepo, realFile);
      if (!rel || rel === '..' || rel.startsWith(`..${path.sep}`) || path.isAbsolute(rel)) {
        const msg = 'scoreboard path escapes repo';
        cache.set(file, { sig, kind: 'error', error: msg });
        errors.push({ repo, error: msg });
        continue;
      }
      text = readFileSync(realFile, 'utf8');
    } catch (e) {
      cache.delete(file);
      const code = (e as NodeJS.ErrnoException).code;
      if (code === 'ENOENT' || code === 'ENOTDIR') continue;
      errors.push({ repo, error: e instanceof Error ? e.message : String(e) });
      continue;
    }

    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      cache.set(file, { sig, kind: 'error', error: msg });
      errors.push({ repo, error: msg });
      continue;
    }

    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      const msg = 'scoreboard is not a JSON object';
      cache.set(file, { sig, kind: 'error', error: msg });
      errors.push({ repo, error: msg });
      continue;
    }

    const entry: BenchmarkBoard = { repo, path: SCOREBOARD_REL_PATH, board: parsed };
    cache.set(file, { sig, kind: 'board', entry });
    boards.push(entry);
  }

  return { boards, errors };
}
