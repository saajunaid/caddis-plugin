import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import {
  AGENT_DROP_AFTER_MS,
  AGENT_IDLE_AFTER_MS,
  readAgentBeats,
} from '../../src/hub/sources/beats.js';
import { createAgentsSource, WAIT_DEBOUNCE_MS } from '../../src/hub/sources/agents.js';
import { normalizeRepoPath } from '../../src/hub/config.js';

const NOW = Date.parse('2026-10-26T10:00:00Z');
const sec = (ms: number): number => ms / 1000;

let home: string;
let dir: string;
beforeEach(() => {
  home = mkdtempSync(path.join(tmpdir(), 'caddis-hub-beats-'));
  dir = path.join(home, '.caddis', 'sessions');
  mkdirSync(dir, { recursive: true });
});
afterEach(() => {
  rmSync(home, { recursive: true, force: true });
});

function write(name: string, body: Record<string, unknown> | string): void {
  writeFileSync(path.join(dir, name), typeof body === 'string' ? body : JSON.stringify(body), 'utf8');
}

const beat = (over: Record<string, unknown> = {}): Record<string, unknown> => ({
  session_id: 'conv-1',
  harness: 'agy',
  caddis_version: '1.3.200',
  pid: null,
  started: sec(NOW - 600_000),
  last_seen: sec(NOW - 5_000),
  status: 'working',
  status_since: sec(NOW - 5_000),
  cwd: null,
  repo_path: null,
  waiting_for: null,
  ...over,
});

const read = (alive: (pid: number) => boolean = () => true, exclude: Set<string> = new Set()) =>
  readAgentBeats({ home, now: NOW, alive, exclude });

describe('readAgentBeats', () => {
  it('reads a working agy session as a session entry marked by agent', () => {
    const repo = path.join(home, 'repo');
    mkdirSync(path.join(repo, '.git'), { recursive: true });
    write('conv-1.json', beat({ cwd: path.join(repo) }));
    expect(read()).toEqual([
      {
        key: 'agy:conv-1',
        pid: null,
        session_id: 'conv-1',
        name: null,
        kind: 'interactive',
        agent: 'agy',
        cwd: repo,
        repo_path: normalizeRepoPath(repo),
        status: 'working',
        waiting_for: null,
        waiting_class: null,
        waiting_since: null,
        copies: 1,
      },
    ]);
  });

  it('confirms a wait for the owner only after the debounce', () => {
    write('a.json', beat({ session_id: 'a', status: 'waiting', waiting_for: 'input needed', status_since: sec(NOW - WAIT_DEBOUNCE_MS) }));
    write('b.json', beat({ session_id: 'b', status: 'waiting', waiting_for: 'input needed', status_since: sec(NOW - WAIT_DEBOUNCE_MS + 1_000) }));
    const [a, b] = read().sort((x, y) => x.session_id.localeCompare(y.session_id));
    expect(a).toMatchObject({ status: 'waiting', waiting_for: 'input needed', waiting_class: 'owner', waiting_since: new Date(NOW - WAIT_DEBOUNCE_MS).toISOString() });
    expect(b).toMatchObject({ status: 'waiting', waiting_class: null });
  });

  it('shows a session not seen for the idle time as idle', () => {
    write('w.json', beat({ session_id: 'w', last_seen: sec(NOW - AGENT_IDLE_AFTER_MS - 1) }));
    write('q.json', beat({ session_id: 'q', status: 'waiting', last_seen: sec(NOW - AGENT_IDLE_AFTER_MS - 1), status_since: sec(NOW - AGENT_IDLE_AFTER_MS - 1) }));
    for (const s of read()) expect(s).toMatchObject({ status: 'idle', waiting_for: null, waiting_class: null, waiting_since: null });
  });

  it('keeps a wait with a live pid past the idle time', () => {
    write('q.json', beat({ session_id: 'q', pid: 4242, status: 'waiting', waiting_for: 'input needed', last_seen: sec(NOW - AGENT_IDLE_AFTER_MS - 1), status_since: sec(NOW - AGENT_IDLE_AFTER_MS - 1) }));
    expect(read((pid) => pid === 4242)[0]).toMatchObject({ pid: 4242, status: 'waiting', waiting_class: 'owner' });
  });

  it('drops a dead pid, a very old entry and a broken file', () => {
    write('dead.json', beat({ session_id: 'dead', pid: 99 }));
    write('old.json', beat({ session_id: 'old', last_seen: sec(NOW - AGENT_DROP_AFTER_MS - 1) }));
    write('broken.json', '{ nope');
    write('.hb-123.tmp', beat());
    expect(read((pid) => pid !== 99)).toEqual([]);
  });

  it('skips Claude Code beats, beats with no status and excluded ids', () => {
    write('claude.json', beat({ session_id: 'c', harness: 'claude' }));
    write('codex.json', { session_id: 'x', harness: 'codex', caddis_version: '1', pid: 5, started: 1, last_seen: sec(NOW) });
    write('odd.json', beat({ session_id: 'odd', status: 'dancing' }));
    write('dup.json', beat({ session_id: 'dup' }));
    expect(read(() => true, new Set(['dup']))).toEqual([]);
  });

  it('returns nothing when the folder is missing', () => {
    rmSync(dir, { recursive: true, force: true });
    expect(read()).toEqual([]);
  });
});

describe('agents source with agent beats', () => {
  const claudeOut = JSON.stringify([
    { pid: 3664, cwd: '/work/shop', kind: 'interactive', sessionId: 's-claude', name: 'demo-session', status: 'busy' },
  ]);

  it('lists agy sessions next to Claude sessions, once each', async () => {
    write('agy.json', beat({ session_id: 'conv-agy' }));
    write('same.json', beat({ session_id: 's-claude' }));
    const src = createAgentsSource({
      now: () => NOW,
      home,
      alive: () => true,
      findClaude: async () => 'claude',
      spawn: async () => ({ ok: true, code: 0, stdout: claudeOut, stderr: '', timedOut: false }),
    });
    await src.refresh();
    const data = src.get().data!;
    expect(data.map((d) => [d.session_id, d.agent])).toEqual([
      ['s-claude', 'claude'],
      ['conv-agy', 'agy'],
    ]);
  });

  it('still lists agy sessions when claude is missing', async () => {
    write('agy.json', beat({ session_id: 'conv-agy' }));
    const src = createAgentsSource({ now: () => NOW, home, alive: () => true, findClaude: async () => null });
    await src.refresh();
    const s = src.get();
    expect(s.ok).toBe(false);
    expect(s.data!.map((d) => d.session_id)).toEqual(['conv-agy']);
  });

  it('reads no beats without a home', async () => {
    write('agy.json', beat({ session_id: 'conv-agy' }));
    const src = createAgentsSource({ now: () => NOW, findClaude: async () => null });
    await src.refresh();
    expect(src.get().data).toBeNull();
  });
});
