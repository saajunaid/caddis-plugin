import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import path from 'node:path';
import { afterAll, afterEach, describe, expect, it, vi } from 'vitest';

import { STALE_AFTER_MS, caddisHome, liveSessions, olderSessions, pidAlive, sessionsDir } from '../src/util/sessions.js';

const scratch = mkdtempSync(path.join(tmpdir(), 'caddis-sessions-'));
afterAll(() => rmSync(scratch, { recursive: true, force: true }));

const NOW = 1_800_000_000_000;

function home(label: string, entries: Array<Record<string, unknown> | string>): string {
  const root = path.join(scratch, label);
  const dir = sessionsDir(root);
  mkdirSync(dir, { recursive: true });
  entries.forEach((entry, i) => {
    const name = typeof entry === 'string' ? `raw-${i}.json` : `${String(entry.session_id)}.json`;
    writeFileSync(path.join(dir, name), typeof entry === 'string' ? entry : JSON.stringify(entry));
  });
  return root;
}

const beat = (sid: string, pid: number, version: string | null, lastSeenS: number, harness = 'claude') => ({
  session_id: sid,
  harness,
  caddis_version: version,
  pid,
  started: lastSeenS - 100,
  last_seen: lastSeenS,
});

describe('sessionsDir', () => {
  afterEach(() => vi.unstubAllEnvs());

  it('is ~/.caddis/sessions — the folder the SessionStart hook writes', () => {
    expect(sessionsDir('/h')).toBe(path.join('/h', '.caddis', 'sessions'));
  });

  it('reads CADDIS_HOME as the home folder, as caddis_heartbeat.py and the rest of caddis do', () => {
    vi.stubEnv('CADDIS_HOME', path.join(scratch, 'pinned-home'));
    expect(caddisHome()).toBe(path.join(scratch, 'pinned-home'));
    expect(sessionsDir()).toBe(path.join(scratch, 'pinned-home', '.caddis', 'sessions'));
  });

  it('falls back to the user home when CADDIS_HOME is empty', () => {
    vi.stubEnv('CADDIS_HOME', '');
    expect(caddisHome()).toBe(homedir());
  });
});

describe('liveSessions', () => {
  it('keeps live pids with a fresh last_seen and drops dead, stale and broken entries', () => {
    const nowS = NOW / 1000;
    const root = home('live', [
      beat('alive', 10, '1.3.140', nowS - 60),
      beat('dead', 20, '1.3.140', nowS - 60),
      beat('stale', 10, '1.3.140', nowS - STALE_AFTER_MS / 1000 - 1),
      '{ broken',
    ]);
    const found = liveSessions(root, NOW, (pid) => pid === 10);
    expect(found.map((s) => s.sessionId)).toEqual(['alive']);
    expect(found[0]).toMatchObject({ harness: 'claude', caddisVersion: '1.3.140', pid: 10 });
  });

  it('returns nothing when the folder does not exist', () => {
    expect(liveSessions(path.join(scratch, 'none'), NOW, () => true)).toEqual([]);
  });
});

describe('olderSessions', () => {
  it('lists only sessions older than the installed version of their own harness', () => {
    const nowS = NOW / 1000;
    const sessions = liveSessions(
      home('older', [
        beat('old-claude', 1, '1.3.140', nowS),
        beat('new-claude', 2, '1.3.143', nowS),
        beat('newer-claude', 5, '1.3.150', nowS),
        beat('proto', 6, '0.0.1', nowS, 'constructor'),
        beat('old-codex', 3, '1.3.100', nowS, 'codex'),
        beat('no-version', 4, null, nowS),
      ]),
      NOW,
      () => true,
    );
    const older = olderSessions(sessions, { claude: '1.3.143' });
    expect(older.map((s) => [s.sessionId, s.installed])).toEqual([['old-claude', '1.3.143']]);
  });
});

describe('pidAlive', () => {
  it('knows this process and rejects nonsense', () => {
    expect(pidAlive(process.pid)).toBe(true);
    expect(pidAlive(0)).toBe(false);
    expect(pidAlive(-1)).toBe(false);
  });
});
