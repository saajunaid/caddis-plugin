import { appendFileSync, existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createActions } from '../../src/hub/actions.js';
import type { HubState } from '../../src/hub/state.js';
import { parseAudit, readAudit } from '../../src/hub/audit.js';
import { auditPath, hubDir } from '../../src/hub/paths.js';

let home: string;
beforeEach(() => {
  home = mkdtempSync(path.join(tmpdir(), 'caddis-hub-'));
  mkdirSync(path.dirname(auditPath(home)), { recursive: true });
});
afterEach(() => {
  rmSync(home, { recursive: true, force: true });
});

const line = (i: number, extra: Record<string, unknown> = {}): string =>
  JSON.stringify({ v: 1, at: `2026-10-24T09:${String(i % 60).padStart(2, '0')}:00Z`, request_id: `r${i}`, repo: 'acme__shop', pr: i, action: 'hold', what: null, result: 'requested', reason: null, ...extra });

describe('readAudit (R51)', () => {
  it('a missing file gives an empty list', () => {
    expect(readAudit(home)).toEqual([]);
  });

  it('250 lines give the last 200 in file order', () => {
    writeFileSync(auditPath(home), Array.from({ length: 250 }, (_, i) => line(i + 1)).join('\n') + '\n');
    const got = readAudit(home);
    expect(got).toHaveLength(200);
    expect(got[0]!.pr).toBe(51);
    expect(got[199]!.pr).toBe(250);
  });

  it('skips a partial tail line, a bad line and a line with no valid at', () => {
    writeFileSync(
      auditPath(home),
      [line(1), 'not json', '[1,2]', JSON.stringify({ v: 1, result: 'requested' }), JSON.stringify({ at: 'nope' }), line(2)].join('\n') +
        '\n{"v":1,"at":"2026-10-24T09:59:00Z","repo"',
    );
    expect(readAudit(home).map((e) => e.pr)).toEqual([1, 2]);
  });

  it('drops unknown keys: a line with a cookie keeps no cookie', () => {
    writeFileSync(auditPath(home), line(1, { cookie: 'secret-cookie', csrf: 'x' }) + '\n');
    const got = readAudit(home);
    expect(JSON.stringify(got)).not.toContain('secret');
    expect(Object.keys(got[0]!).sort()).toEqual(['action', 'at', 'pr', 'reason', 'repo', 'request_id', 'result', 'what']);
  });

  it('returns the same array until the file changes', () => {
    writeFileSync(auditPath(home), line(1) + '\n');
    const a = readAudit(home);
    expect(readAudit(home)).toBe(a);
    appendFileSync(auditPath(home), line(2) + '\n');
    const b = readAudit(home);
    expect(b).not.toBe(a);
    expect(b).toHaveLength(2);
  });
});

describe('parseAudit', () => {
  it('turns a refusal line into an entry with its reason', () => {
    const [e] = parseAudit([line(3, { result: 'refused', reason: 'head_moved', request_id: null })]);
    expect(e).toMatchObject({ result: 'refused', reason: 'head_moved', request_id: null, pr: 3 });
  });
});

describe('one audit file for the writer and the reader (CADDIS_HUB_HOME)', () => {
  it('the reader follows CADDIS_HUB_HOME, as the action route does', async () => {
    const hubFolder = mkdtempSync(path.join(tmpdir(), 'caddis-hub-'));
    vi.stubEnv('CADDIS_HUB_HOME', hubFolder);
    try {
      expect(auditPath(home)).toBe(path.join(hubFolder, 'audit.jsonl'));
      const actions = createActions({ home, getState: () => ({ repos: [] }) as unknown as HubState, now: () => Date.parse('2026-10-24T10:00:00Z') });
      const r = await actions.submit({ repo_id: 'acme__shop', action: 'hold', pr: 7, head_sha: 'A'.repeat(40) });
      expect(r.status).toBe(404);
      const got = readAudit(home);
      expect(got).toHaveLength(1);
      expect(got[0]).toMatchObject({ result: 'refused', reason: 'unknown_repo', repo: 'acme__shop' });
      expect(existsSync(path.join(hubDir(home), 'audit.jsonl'))).toBe(false);
    } finally {
      vi.unstubAllEnvs();
      rmSync(hubFolder, { recursive: true, force: true });
    }
  });
});
