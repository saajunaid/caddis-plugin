import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { createGitFetcher, FETCH_TIMEOUT_MS, mapLimit } from '../../src/hub/gitFetch.js';
import type { SpawnFn, SpawnOptions, SpawnResult } from '../../src/hub/spawn.js';

let root: string;

beforeEach(() => {
  root = mkdtempSync(path.join(tmpdir(), 'caddis-fetch-'));
});

afterEach(() => {
  rmSync(root, { recursive: true, force: true });
});

function makeRepo(
  name: string,
  opts: { head?: boolean; remote?: string | null; config?: boolean } = {},
): string {
  const dir = path.join(root, name);
  mkdirSync(path.join(dir, '.git'), { recursive: true });
  if (opts.head !== false) {
    writeFileSync(path.join(dir, '.git', 'HEAD'), 'ref: refs/heads/main\n');
  }
  if (opts.config !== false) {
    const url = opts.remote === undefined ? 'https://github.com/acme/alpha.git' : opts.remote;
    const cfg =
      url !== null
        ? `[remote "origin"]\n\turl = ${url}\n\tfetch = +refs/heads/*:refs/remotes/origin/*\n`
        : '[core]\n\tbare = false\n';
    writeFileSync(path.join(dir, '.git', 'config'), cfg);
  }
  return dir;
}

describe('createGitFetcher', () => {
  it('spawns git -C <repo> fetch origin --prune --quiet with 30 s timeout and non-interactive env', async () => {
    const alpha = makeRepo('alpha');
    const calls: { cmd: string; args: string[]; opts: SpawnOptions }[] = [];
    const spawn: SpawnFn = async (cmd, args, opts) => {
      calls.push({ cmd, args, opts });
      return { ok: true, code: 0, stdout: '', stderr: '', timedOut: false };
    };

    const res = await createGitFetcher({ spawn }).fetchRepo(alpha);

    expect(res).toEqual({ path: alpha, status: 'fetched' });
    expect(FETCH_TIMEOUT_MS).toBe(30_000);
    expect(calls).toHaveLength(1);
    expect(calls[0]!.cmd).toBe('git');
    expect(calls[0]!.args).toEqual(['-C', alpha, 'fetch', 'origin', '--prune', '--quiet']);
    expect(calls[0]!.opts.timeoutMs).toBe(30_000);
    expect(calls[0]!.opts.env).toMatchObject({
      GIT_TERMINAL_PROMPT: '0',
      GCM_INTERACTIVE: 'never',
    });
  });

  it('returns failed with stderr text on non-zero exit', async () => {
    const alpha = makeRepo('alpha');
    const spawn: SpawnFn = async () => ({
      ok: false,
      code: 128,
      stdout: '',
      stderr: '  fatal: repository not found\n',
      timedOut: false,
    });

    const res = await createGitFetcher({ spawn }).fetchRepo(alpha);

    expect(res).toEqual({
      path: alpha,
      status: 'failed',
      error: 'fatal: repository not found',
    });
  });

  it('returns failed mentioning timed out when spawn times out', async () => {
    const alpha = makeRepo('alpha');
    const spawn: SpawnFn = async () => ({
      ok: false,
      code: null,
      stdout: '',
      stderr: 'unrelated output',
      timedOut: true,
    });

    const res = await createGitFetcher({ spawn }).fetchRepo(alpha);

    expect(res.path).toBe(alpha);
    expect(res.status).toBe('failed');
    expect(res.error).toMatch(/timed out/i);
  });

  it('never rejects when spawn throws synchronously or rejects', async () => {
    const alpha = makeRepo('alpha');
    const syncThrow: SpawnFn = () => {
      throw new Error('sync spawn failure');
    };
    const asyncReject: SpawnFn = async () => {
      throw new Error('async spawn failure');
    };

    await expect(createGitFetcher({ spawn: syncThrow }).fetchRepo(alpha)).resolves.toEqual({
      path: alpha,
      status: 'failed',
      error: 'sync spawn failure',
    });
    await expect(createGitFetcher({ spawn: asyncReject }).fetchRepo(alpha)).resolves.toEqual({
      path: alpha,
      status: 'failed',
      error: 'async spawn failure',
    });
  });

  it('returns skipped and does not call spawn without .git/HEAD or without an origin remote', async () => {
    const plain = path.join(root, 'plain');
    mkdirSync(plain, { recursive: true });
    const noHead = makeRepo('no-head', { head: false });
    const noOrigin = makeRepo('no-origin', { remote: null });
    const noConfig = makeRepo('no-config', { config: false });

    let spawnCalls = 0;
    const spawn: SpawnFn = async () => {
      spawnCalls += 1;
      return { ok: true, code: 0, stdout: '', stderr: '', timedOut: false };
    };
    const fetcher = createGitFetcher({ spawn });

    for (const dir of [plain, noHead, noOrigin, noConfig]) {
      const res = await fetcher.fetchRepo(dir);
      expect(res.path).toBe(dir);
      expect(res.status).toBe('skipped');
    }
    expect(spawnCalls).toBe(0);
  });

  it('shares an in-flight fetch for the same repo, spawns again after settling, and runs distinct repos concurrently', async () => {
    const alpha = makeRepo('alpha');
    const beta = makeRepo('beta', { remote: 'https://github.com/acme/beta.git' });

    const pending: { args: string[]; resolve: (r: SpawnResult) => void }[] = [];
    const spawn: SpawnFn = (_cmd, args) =>
      new Promise<SpawnResult>((resolve) => {
        pending.push({ args, resolve });
      });

    const fetcher = createGitFetcher({ spawn });

    // Concurrent calls for the same repo (exact, trailing slash, relative dot segment) join one spawn.
    const p1 = fetcher.fetchRepo(alpha);
    const p2 = fetcher.fetchRepo(`${alpha}/`);
    const p3 = fetcher.fetchRepo(path.join(alpha, 'sub', '..'));
    expect(pending).toHaveLength(1);

    pending[0]!.resolve({ ok: true, code: 0, stdout: '', stderr: '', timedOut: false });
    const [r1, r2, r3] = await Promise.all([p1, p2, p3]);
    expect(r1).toEqual({ path: alpha, status: 'fetched' });
    expect(r2).toEqual(r1);
    expect(r3).toEqual(r1);

    // Once settled, a new call spawns again.
    const p4 = fetcher.fetchRepo(alpha);
    expect(pending).toHaveLength(2);
    pending[1]!.resolve({ ok: true, code: 0, stdout: '', stderr: '', timedOut: false });
    expect(await p4).toEqual({ path: alpha, status: 'fetched' });

    // Two different repos spawn twice in parallel.
    const pa = fetcher.fetchRepo(alpha);
    const pb = fetcher.fetchRepo(beta);
    expect(pending).toHaveLength(4);
    pending[2]!.resolve({ ok: true, code: 0, stdout: '', stderr: '', timedOut: false });
    pending[3]!.resolve({ ok: true, code: 0, stdout: '', stderr: '', timedOut: false });
    expect(await Promise.all([pa, pb])).toEqual([
      { path: alpha, status: 'fetched' },
      { path: beta, status: 'fetched' },
    ]);
  });
});

describe('mapLimit', () => {
  it('handles an empty list without invoking the worker', async () => {
    let calls = 0;
    const out = await mapLimit<number, number>([], 4, async (n) => {
      calls += 1;
      return n;
    });
    expect(out).toEqual([]);
    expect(calls).toBe(0);
  });

  it('never runs more than limit workers at once and preserves result order', async () => {
    let active = 0;
    let peak = 0;
    const items = [0, 1, 2, 3, 4, 5, 6];

    const out = await mapLimit(items, 3, async (item) => {
      active += 1;
      peak = Math.max(peak, active);
      await new Promise((r) => setTimeout(r, (items.length - item) * 4));
      active -= 1;
      return `res-${item}`;
    });

    expect(peak).toBe(3);
    expect(out).toEqual(['res-0', 'res-1', 'res-2', 'res-3', 'res-4', 'res-5', 'res-6']);
  });
});
