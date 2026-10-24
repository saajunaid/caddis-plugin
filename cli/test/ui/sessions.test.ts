import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { repoSessions } from '../../ui/src/repo/sessions';
import type { HubState } from '../../ui/src/types';

const load = (name: string): HubState =>
  JSON.parse(readFileSync(new URL(`../fixtures/hub-state/${name}.json`, import.meta.url), 'utf8')) as HubState;

describe('repoSessions (P20, R50)', () => {
  it('lists the repo sessions, the waiting one first', () => {
    const s = load('full');
    const m = repoSessions(s, s.repos[0]!);
    expect(m.unknown).toBe(false);
    expect(m.rows.map((r) => [r.name, r.status])).toEqual([
      ['demo-session-api', 'waiting'],
      ['demo-session-peer', 'waiting'],
      ['demo-session-web', 'busy'],
    ]);
    expect(m.rows[0]).toMatchObject({ waitingFor: 'permission prompt', waitingClass: 'owner', copyWarning: null });
    expect(m.rows[1]).toMatchObject({ waitingClass: 'peer' });
  });
  it('warns when a session runs twice (L16)', () => {
    const s = load('full');
    s.sessions[1]!.copies = 2;
    expect(repoSessions(s, s.repos[0]!).rows.find((r) => r.name === 'demo-session-web')!.copyWarning).toBe('2 copies');
  });
  it('a repo with no sessions has no rows', () => {
    const s = load('full');
    const docs = s.repos.find((r) => r.name === 'docs')!;
    s.sessions = s.sessions.filter((x) => x.repo_path !== docs.path);
    const m = repoSessions(s, docs);
    expect(m.rows).toEqual([]);
    expect(m.unknown).toBe(false);
  });
  it('a failing sessions source that never loaded is unknown, with its error', () => {
    const s = load('full');
    s.sources.agents = { ok: false, last_ok_at: null, last_error: 'claude agents failed', stale: true };
    expect(repoSessions(s, s.repos[0]!)).toEqual({ unknown: true, error: 'claude agents failed', rows: [] });
  });
  it('a failing source with an earlier good read keeps the rows and the error', () => {
    const s = load('full');
    s.sources.agents = { ok: false, last_ok_at: '2026-10-24T10:40:00Z', last_error: 'claude agents failed', stale: false };
    const m = repoSessions(s, s.repos[0]!);
    expect(m.unknown).toBe(false);
    expect(m.error).toBe('claude agents failed');
    expect(m.rows).toHaveLength(3);
  });
});
