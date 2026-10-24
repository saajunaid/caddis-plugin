import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { createCoordinatorSource } from '../../src/hub/sources/coordinator.js';
import { hubDir } from '../../src/hub/paths.js';

let home: string;
beforeEach(() => {
  home = mkdtempSync(path.join(tmpdir(), 'caddis-hub-'));
});
afterEach(() => {
  rmSync(home, { recursive: true, force: true });
});

const NOW = Date.parse('2026-10-24T10:00:00Z');
function put(id: string, body: unknown): string {
  const dir = path.join(hubDir(home), 'repos', id);
  mkdirSync(dir, { recursive: true });
  const file = path.join(dir, 'coordinator.json');
  writeFileSync(file, typeof body === 'string' ? body : JSON.stringify(body));
  return file;
}
const state = (over: Record<string, unknown> = {}) => ({
  schema: 1,
  repo: 'acme/shop',
  coordinator_session: { name: 'demo-session', sessionId: 's1', pid: 42 },
  heartbeat_at: '2026-10-24T09:59:00Z',
  queue: [{ pr: 7, head_sha: 'abc', title: 't', state: 'ready' }],
  merging_now: null,
  deploy_checks: Array.from({ length: 8 }, (_, i) => ({ pr: i + 1 })),
  ledger: Array.from({ length: 25 }, (_, i) => ({ what: `w${i}` })),
  processed_requests: Array.from({ length: 25 }, (_, i) => ({ id: `r${i}` })),
  ...over,
});
const make = () => createCoordinatorSource({ home, now: () => NOW });

describe('coordinator source', () => {
  it('reads a fresh coordinator and trims lists', () => {
    put('acme-shop', state());
    const src = make();
    src.refresh();
    const e = src.get()[0]!;
    expect(e).toMatchObject({
      repo_id: 'acme-shop',
      schema: 1,
      heartbeat_age_s: 60,
      responding: true,
      merging_now: null,
      error: null,
      update_needed: false,
    });
    expect(e.coordinator_session).toMatchObject({ pid: 42 });
    expect(e.queue).toHaveLength(1);
    expect(e.deploy_checks).toHaveLength(5);
    expect((e.deploy_checks[0] as { pr: number }).pr).toBe(4);
    // H3: kept up to 100, so owner items and request views can join on them (R37, R38).
    expect(e.ledger).toHaveLength(25);
    expect(e.processed_requests).toHaveLength(25);
  });

  it('marks an old heartbeat as not responding (180 s is the limit)', () => {
    put('a', state({ heartbeat_at: '2026-10-24T09:57:00Z' }));
    put('b', state({ heartbeat_at: '2026-10-24T09:57:01Z' }));
    const src = make();
    src.refresh();
    const [a, b] = src.get();
    expect(a).toMatchObject({ heartbeat_age_s: 180, responding: false });
    expect(b).toMatchObject({ heartbeat_age_s: 179, responding: true });
  });

  it('accepts schema 0', () => {
    put('a', state({ schema: 0 }));
    const src = make();
    src.refresh();
    expect(src.get()[0]).toMatchObject({ schema: 0, error: null });
  });

  it('keeps the last good copy on a parse error and records it', () => {
    const file = put('a', state());
    const src = make();
    src.refresh();
    writeFileSync(file, '{ broken');
    src.refresh();
    const e = src.get()[0]!;
    expect(e.queue).toHaveLength(1);
    expect(e.error).toContain('corrupt');
    writeFileSync(file, JSON.stringify(state({ queue: [] })));
    src.refresh();
    expect(src.get()[0]).toMatchObject({ queue: [], error: null });
  });

  it('flags a newer schema as update_needed and keeps the last good copy', () => {
    const file = put('a', state());
    const src = make();
    src.refresh();
    writeFileSync(file, JSON.stringify(state({ schema: 2 })));
    src.refresh();
    const e = src.get()[0]!;
    expect(e).toMatchObject({ schema: 1, update_needed: true });
    expect(e.error).toContain('update the hub');
    expect(e.queue).toHaveLength(1);
  });

  it('shows a stub for a newer schema with no good copy', () => {
    put('a', state({ schema: 3 }));
    const src = make();
    src.refresh();
    expect(src.get()[0]).toMatchObject({ repo_id: 'a', update_needed: true, queue: [], ledger: [], responding: false });
  });

  it('shows an error stub for a first-time corrupt file', () => {
    put('a', '{ broken');
    const src = make();
    src.refresh();
    expect(src.get()[0]).toMatchObject({ repo_id: 'a', schema: null, responding: false, ledger: [], update_needed: false });
    expect(src.get()[0]!.error).toContain('corrupt');
  });

  it('returns nothing when there is no repos folder, and drops removed repos', () => {
    const src = make();
    src.refresh();
    expect(src.get()).toEqual([]);
    const file = put('a', state());
    src.refresh();
    expect(src.get()).toHaveLength(1);
    rmSync(file);
    src.refresh();
    expect(src.get()).toEqual([]);
  });

  it('does not write to the coordinator file', () => {
    const file = put('a', state());
    const before = JSON.stringify(state());
    make().refresh();
    expect(readFileSync(file, 'utf8')).toBe(before);
  });
  it('reads the hub folder named by CADDIS_HUB_HOME when it is set', () => {
    const hub = mkdtempSync(path.join(tmpdir(), 'caddis-hub-'));
    const old = process.env.CADDIS_HUB_HOME;
    try {
      mkdirSync(path.join(hub, 'repos', 'acme-shop'), { recursive: true });
      writeFileSync(path.join(hub, 'repos', 'acme-shop', 'coordinator.json'), JSON.stringify(state()));
      process.env.CADDIS_HUB_HOME = hub;
      const src = make();
      src.refresh();
      expect(JSON.stringify(src.get())).toContain('acme-shop');
    } finally {
      if (old === undefined) delete process.env.CADDIS_HUB_HOME;
      else process.env.CADDIS_HUB_HOME = old;
      rmSync(hub, { recursive: true, force: true });
    }
  });
});

describe('coordinator status and request views (H3: R36, R38)', () => {
  const SHA = 'A'.repeat(40);
  const reqLine = (id: string, created: string, over: Record<string, unknown> = {}): string =>
    JSON.stringify({
      v: 1,
      id,
      created_at: created,
      expires_at: '2026-10-24T10:30:00Z',
      repo: 'acme__shop',
      pr: 7,
      head_sha: SHA,
      action: 'hold',
      args: {},
      ...over,
    });
  const putRequests = (text: string): void =>
    writeFileSync(path.join(hubDir(home), 'repos', 'acme__shop', 'requests.jsonl'), text);

  it('a stop marker at or after the heartbeat is stopped, not down; a later heartbeat is live', () => {
    put('acme__shop', state({ heartbeat_at: '2026-10-24T09:50:00Z', stopped_at: '2026-10-24T09:50:00Z' }));
    const src = make();
    src.refresh();
    expect(src.get()[0]).toMatchObject({ status: 'stopped', responding: false, stopped_at: '2026-10-24T09:50:00Z' });
    put('acme__shop', state({ heartbeat_at: '2026-10-24T09:59:30Z', stopped_at: '2026-10-24T09:50:00Z' }));
    src.refresh();
    expect(src.get()[0]).toMatchObject({ status: 'live', responding: true });
    put('acme__shop', state({ heartbeat_at: '2026-10-24T09:50:00Z' }));
    src.refresh();
    expect(src.get()[0]).toMatchObject({ status: 'down', responding: false, stopped_at: null });
  });

  it('joins each request with its result, and marks one with no result after 2 min as not picked up', () => {
    put(
      'acme__shop',
      state({
        processed_requests: [
          { id: 'r-done', result: 'done', reason: '', at: '2026-10-24T09:59:10Z' },
          { id: 'r-moved', result: 'rejected', reason: 'head moved', at: '2026-10-24T09:59:10Z' },
          { id: 'r-old', result: 'expired', reason: 'expired', at: '2026-10-24T09:59:10Z' },
        ],
      }),
    );
    const lines = [
      reqLine('r-done', '2026-10-24T09:59:00Z', { action: 'approve', pr: null, head_sha: null, args: { what: 'x' } }),
      reqLine('r-moved', '2026-10-24T09:59:00Z'),
      reqLine('r-old', '2026-10-24T09:20:00Z'),
      'not json',
      reqLine('r-new', '2026-10-24T09:59:30Z'),
      reqLine('r-lost', '2026-10-24T09:57:30Z'),
    ];
    putRequests(lines.join('\n') + '\n' + reqLine('r-partial', '2026-10-24T09:59:59Z').slice(0, 30));
    const src = make();
    src.refresh();
    const views = src.get()[0]!.requests;
    expect(views.map((v) => [v.id, v.status, v.reason])).toEqual([
      ['r-done', 'done', null],
      ['r-moved', 'rejected', 'head moved'],
      ['r-old', 'expired', 'expired'],
      ['r-new', 'requested', null],
      ['r-lost', 'not_picked_up', 'no coordinator intake for 2 min'],
    ]);
    expect(views[0]).toMatchObject({ action: 'approve', pr: null, what: 'x', at: '2026-10-24T09:59:10Z' });
  });

  it('reads only the tail of a large requests file and drops the cut first line', () => {
    put('acme__shop', state());
    const lines = Array.from({ length: 2000 }, (_, i) => reqLine(`r${i}`, '2026-10-24T09:59:30Z'));
    putRequests(lines.join('\n') + '\n');
    const src = make();
    src.refresh();
    const views = src.get()[0]!.requests;
    expect(views).toHaveLength(30);
    expect(views.at(-1)!.id).toBe('r1999');
  });

  it('keeps the open owner asks', () => {
    put('acme__shop', state({ owner_asks: [{ id: 'ask-1', what: 'w', recommendation: 'hold' }, { what: 'no id' }] }));
    const src = make();
    src.refresh();
    expect(src.get()[0]!.owner_asks).toEqual([{ id: 'ask-1', what: 'w', recommendation: 'hold' }]);
  });
});
