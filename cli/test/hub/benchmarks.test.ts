import { mkdirSync, mkdtempSync, rmSync, utimesSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { readBenchmarks } from '../../src/hub/benchmarks.js';

let tmp: string;

beforeEach(() => {
  tmp = mkdtempSync(path.join(tmpdir(), 'caddis-bench-'));
});

afterEach(() => {
  rmSync(tmp, { recursive: true, force: true });
});

function writeBoard(repoDir: string, content: string): string {
  const file = path.join(repoDir, 'evals', 'results', 'review-scoreboard.json');
  mkdirSync(path.dirname(file), { recursive: true });
  writeFileSync(file, content, 'utf8');
  return file;
}

describe('readBenchmarks', () => {
  it('reads the board of each repo that has one', () => {
    const repoA = path.join(tmp, 'repo-a');
    const repoB = path.join(tmp, 'repo-b');
    mkdirSync(repoA, { recursive: true });
    mkdirSync(repoB, { recursive: true });
    const board = { schema: 1, updated: '2026-11-12', rows: [] };
    writeBoard(repoA, JSON.stringify(board));

    const got = readBenchmarks([repoA, repoB]);
    expect(got).toEqual({
      boards: [
        {
          repo: 'repo-a',
          path: 'evals/results/review-scoreboard.json',
          board,
        },
      ],
      errors: [],
    });
  });

  it('skips repos without the file', () => {
    const emptyRepo = path.join(tmp, 'empty-repo');
    mkdirSync(emptyRepo, { recursive: true });
    const missingRepo = path.join(tmp, 'missing-repo');

    expect(readBenchmarks([emptyRepo, missingRepo])).toEqual({
      boards: [],
      errors: [],
    });
  });

  it('test_malformed_board_is_reported_not_thrown', () => {
    const badRepo = path.join(tmp, 'bad-repo');
    writeBoard(badRepo, '{not valid json');

    const got = readBenchmarks([badRepo]);
    expect(got.boards).toEqual([]);
    expect(got.errors).toHaveLength(1);
    expect(got.errors[0]!.repo).toBe('bad-repo');
    expect(got.errors[0]!.error.length).toBeGreaterThan(0);
  });

  it('caches by mtime', () => {
    const repo = path.join(tmp, 'cached-repo');
    const file = writeBoard(repo, JSON.stringify({ schema: 1, updated: '2026-11-12' }));
    const t1 = new Date('2026-11-12T00:00:00.000Z');
    utimesSync(file, t1, t1);

    const first = readBenchmarks([repo]);
    expect(first.boards).toHaveLength(1);

    // Same size and restored mtime: cached board is returned without re-reading disk.
    writeFileSync(file, JSON.stringify({ schema: 1, updated: '2099-01-01' }), 'utf8');
    utimesSync(file, t1, t1);
    const second = readBenchmarks([repo]);
    expect(second.boards[0]).toBe(first.boards[0]);
    expect(second.boards[0]!.board).toEqual({ schema: 1, updated: '2026-11-12' });

    // Updated mtime: file is re-read from disk.
    const t2 = new Date('2026-11-13T00:00:00.000Z');
    utimesSync(file, t2, t2);
    const third = readBenchmarks([repo]);
    expect(third.boards[0]!.board).toEqual({ schema: 1, updated: '2099-01-01' });
  });
});
