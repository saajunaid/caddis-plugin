import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { classifyWaiting, createAgentsSource, repoPathFor } from '../../src/hub/sources/agents.js';
import { normalizeRepoPath } from '../../src/hub/config.js';

const fixture = readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), 'fixtures', 'agents.json'), 'utf8');

let dir: string;
beforeEach(() => {
  dir = mkdtempSync(path.join(tmpdir(), 'caddis-hub-'));
});
afterEach(() => {
  rmSync(dir, { recursive: true, force: true });
});

const ok = (stdout: string) => async () => ({ ok: true, code: 0, stdout, stderr: '', timedOut: false });

function make(stdoutRef: { v: string }, clock: { t: number }, extra: Record<string, unknown> = {}) {
  return createAgentsSource({
    now: () => clock.t,
    findClaude: async () => 'claude',
    spawn: async () => ({ ok: true, code: 0, stdout: stdoutRef.v, stderr: '', timedOut: false }),
    ...extra,
  });
}

describe('classifyWaiting', () => {
  it('owner for permission prompt, input needed and questions', () => {
    expect(classifyWaiting('permission prompt')).toBe('owner');
    expect(classifyWaiting('input needed')).toBe('owner');
    expect(classifyWaiting('Asking a QUESTION')).toBe('owner');
    expect(classifyWaiting('peer reply')).toBe('peer');
    expect(classifyWaiting(null)).toBe('peer');
  });
});

describe('agents source', () => {
  it('parses interactive, background, duplicate and done entries', async () => {
    const clock = { t: Date.parse('2026-10-24T10:00:00Z') };
    const src = make({ v: fixture }, clock);
    await src.refresh();
    const s = src.get();
    expect(s.ok).toBe(true);
    const data = s.data!;
    expect(data.map((d) => d.session_id)).toEqual(['s-idle', 's-wait', 's-peer', 's-dup', 's-bg']);
    expect(data.find((d) => d.session_id === 's-dup')).toMatchObject({ copies: 2, key: '3900:s-dup' });
    expect(data.find((d) => d.session_id === 's-idle')).toMatchObject({ key: '3664:s-idle', pid: 3664, status: 'idle', copies: 1 });
    expect(data.find((d) => d.session_id === 's-bg')).toMatchObject({ kind: 'background', status: 'working', pid: null });
  });

  it('debounces waiting for 45 s', async () => {
    const clock = { t: Date.parse('2026-10-24T10:00:00Z') };
    const out = { v: fixture };
    const src = make(out, clock);
    await src.refresh();
    let w = src.get().data!.find((d) => d.session_id === 's-wait')!;
    expect(w).toMatchObject({ status: 'waiting', waiting_class: null, waiting_for: 'permission prompt', waiting_since: '2026-10-24T10:00:00.000Z' });
    clock.t += 44_000;
    await src.refresh();
    expect(src.get().data!.find((d) => d.session_id === 's-wait')!.waiting_class).toBeNull();
    clock.t += 1_000;
    await src.refresh();
    const data = src.get().data!;
    w = data.find((d) => d.session_id === 's-wait')!;
    expect(w.waiting_class).toBe('owner');
    expect(data.find((d) => d.session_id === 's-peer')!.waiting_class).toBe('peer');
    expect(data.find((d) => d.session_id === 's-idle')!.waiting_class).toBeNull();
  });

  it('resets the debounce when the session stops waiting', async () => {
    const clock = { t: Date.parse('2026-10-24T10:00:00Z') };
    const out = { v: fixture };
    const src = make(out, clock);
    await src.refresh();
    clock.t += 30_000;
    out.v = fixture.replace('"status":"waiting","waitingFor":"permission prompt"', '"status":"busy"');
    await src.refresh();
    clock.t += 30_000;
    out.v = fixture;
    await src.refresh();
    const w = src.get().data!.find((d) => d.session_id === 's-wait')!;
    expect(w.waiting_class).toBeNull();
    expect(w.waiting_since).toBe(new Date(clock.t).toISOString());
  });

  it('keeps the last good data on failure and goes stale after 3 minutes', async () => {
    const clock = { t: Date.parse('2026-10-24T10:00:00Z') };
    let mode: 'good' | 'bad' | 'json' | 'timeout' = 'good';
    const src = createAgentsSource({
      now: () => clock.t,
      findClaude: async () => 'claude',
      spawn: async () =>
        mode === 'good'
          ? { ok: true, code: 0, stdout: fixture, stderr: '', timedOut: false }
          : mode === 'bad'
            ? { ok: false, code: 1, stdout: '', stderr: 'boom', timedOut: false }
            : mode === 'timeout'
              ? { ok: false, code: null, stdout: '', stderr: '', timedOut: true }
              : { ok: true, code: 0, stdout: 'not json', stderr: '', timedOut: false },
    });
    await src.refresh();
    mode = 'bad';
    clock.t += 60_000;
    await src.refresh();
    let s = src.get();
    expect(s.ok).toBe(false);
    expect(s.last_error).toContain('boom');
    expect(s.data).toHaveLength(5);
    expect(s.stale).toBe(false);
    mode = 'json';
    await src.refresh();
    expect(src.get().last_error).toContain('not valid JSON');
    mode = 'timeout';
    clock.t += 130_000;
    await src.refresh();
    s = src.get();
    expect(s.last_error).toContain('timed out');
    expect(s.stale).toBe(true);
    expect(s.data).toHaveLength(5);
  });

  it('fails cleanly when claude is missing', async () => {
    const src = createAgentsSource({ findClaude: async () => null, spawn: ok('[]') });
    await src.refresh();
    expect(src.get()).toMatchObject({ ok: false, data: null, stale: true });
    expect(src.get().last_error).toContain('claude');
  });

  it('bounds a PATH lookup that never ends, so the latch opens again', async () => {
    vi.useFakeTimers();
    try {
      let finds = 0;
      const src = createAgentsSource({
        findClaude: () => {
          finds += 1;
          return new Promise<string | null>(() => {});
        },
        spawn: ok('[]'),
      });
      const first = src.refresh();
      await vi.advanceTimersByTimeAsync(10_000);
      await first;
      expect(src.get().last_error).toBe('finding claude did not finish in 10 s');
      void src.refresh();
      expect(finds).toBe(2); // a new run, not the hung promise
    } finally {
      vi.useRealTimers();
    }
  });

  it('runs one refresh at a time', async () => {
    let calls = 0;
    const src = createAgentsSource({
      findClaude: async () => 'claude',
      spawn: async () => {
        calls += 1;
        await new Promise((r) => setTimeout(r, 20));
        return { ok: true, code: 0, stdout: '[]', stderr: '', timedOut: false };
      },
    });
    await Promise.all([src.refresh(), src.refresh()]);
    expect(calls).toBe(1);
  });

  it('maps a session cwd to its repo', async () => {
    const repo = path.join(dir, 'shop');
    mkdirSync(path.join(repo, '.git'), { recursive: true });
    mkdirSync(path.join(repo, 'sub'), { recursive: true });
    const json = JSON.stringify([{ pid: 1, cwd: path.join(repo, 'sub'), kind: 'interactive', sessionId: 'a', name: 'demo-session', status: 'idle' }]);
    const src = createAgentsSource({ findClaude: async () => 'claude', spawn: ok(json) });
    await src.refresh();
    expect(src.get().data![0]!.repo_path).toBe(normalizeRepoPath(repo));
  });
});

describe('repoPathFor', () => {
  it('returns the folder that holds a .git folder', () => {
    const repo = path.join(dir, 'shop');
    mkdirSync(path.join(repo, '.git'), { recursive: true });
    expect(repoPathFor(repo)).toBe(normalizeRepoPath(repo));
  });

  it('maps a worktree to the main repo through commondir', () => {
    const main = path.join(dir, 'shop');
    const wtGit = path.join(main, '.git', 'worktrees', 'feat');
    mkdirSync(wtGit, { recursive: true });
    writeFileSync(path.join(wtGit, 'commondir'), '../..\n');
    const wt = path.join(dir, 'wt', 'feat');
    mkdirSync(path.join(wt, 'deep'), { recursive: true });
    writeFileSync(path.join(wt, '.git'), `gitdir: ${wtGit}\n`);
    expect(repoPathFor(path.join(wt, 'deep'))).toBe(normalizeRepoPath(main));
  });

  it('maps a submodule (no commondir) to its own work tree', () => {
    const sub = path.join(dir, 'super', 'libs', 'sub');
    const modGit = path.join(dir, 'super', '.git', 'modules', 'sub');
    mkdirSync(modGit, { recursive: true });
    mkdirSync(sub, { recursive: true });
    writeFileSync(path.join(sub, '.git'), `gitdir: ${modGit}
`);
    expect(repoPathFor(sub)).toBe(normalizeRepoPath(sub));
  });

  it('accepts a relative gitdir', () => {
    const main = path.join(dir, 'shop');
    const wtGit = path.join(main, '.git', 'worktrees', 'feat');
    mkdirSync(wtGit, { recursive: true });
    writeFileSync(path.join(wtGit, 'commondir'), '../..');
    const wt = path.join(main, '.claude-wt');
    mkdirSync(wt, { recursive: true });
    writeFileSync(path.join(wt, '.git'), `gitdir: ${path.relative(wt, wtGit)}\n`);
    expect(repoPathFor(wt)).toBe(normalizeRepoPath(main));
  });

  it('returns null with no .git, no cwd, or a bad .git file', () => {
    const bare = path.join(dir, 'plain');
    mkdirSync(bare, { recursive: true });
    expect(repoPathFor(null)).toBeNull();
    writeFileSync(path.join(bare, '.git'), 'garbage');
    expect(repoPathFor(bare)).toBeNull();
  });
});

describe.skipIf(process.platform !== 'win32')('sessions through a .cmd shim (win32)', () => {
  it('reads a claude agents array from a fake .cmd via spawnBounded', async () => {
    const jsonFile = path.join(dir, 'agents.json');
    writeFileSync(jsonFile, fixture);
    const shim = path.join(dir, 'claude.cmd');
    writeFileSync(shim, `@echo off\r\ntype "${jsonFile}"

`);
    const src = createAgentsSource({ now: () => Date.now(), findClaude: async () => shim });
    await src.refresh();
    const s = src.get();
    expect(s.last_error).toBeNull();
    expect(s.data!.length).toBeGreaterThan(0);
  });
});
