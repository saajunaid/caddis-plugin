import { mkdtempSync, rmSync, writeFileSync, readFileSync, existsSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { lockPath, hubDir } from '../../src/hub/paths.js';
import { acquireLock, readLock, releaseLock, writeLock } from '../../src/hub/lock.js';
import { pidAlive } from '../../src/util/sessions.js';

let home: string;

beforeEach(() => {
  home = mkdtempSync(path.join(tmpdir(), 'caddis-hub-'));
});
afterEach(() => {
  rmSync(home, { recursive: true, force: true });
});

const info = (pid: number, port = 0) => ({ pid, started_at: '2026-10-24T10:00:00.000Z', port });

describe('hub.lock', () => {
  it('creates the lock with pid, started_at and port', () => {
    const r = acquireLock(info(4242, 47821), home, () => true);
    expect(r.ok).toBe(true);
    const raw = JSON.parse(readFileSync(lockPath(home), 'utf8'));
    expect(raw).toEqual({ pid: 4242, started_at: '2026-10-24T10:00:00.000Z', port: 47821 });
    expect(readLock(home)).toEqual(raw);
  });

  it('refuses when a live process holds the lock and names the holder', () => {
    expect(acquireLock(info(1111, 5000), home, () => true).ok).toBe(true);
    const r = acquireLock(info(2222), home, () => true);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.holder).toMatchObject({ pid: 1111, port: 5000 });
    expect(readLock(home)?.pid).toBe(1111);
  });

  it('takes over a stale lock (dead pid)', () => {
    acquireLock(info(1111), home, () => true);
    const r = acquireLock(info(2222), home, (pid) => pid !== 1111);
    expect(r.ok).toBe(true);
    expect(readLock(home)?.pid).toBe(2222);
  });

  it('takes over a corrupt lock', () => {
    mkdirSync(hubDir(home), { recursive: true });
    writeFileSync(lockPath(home), 'not json');
    expect(readLock(home)).toBeNull();
    expect(acquireLock(info(2222), home, () => true).ok).toBe(true);
    expect(readLock(home)?.pid).toBe(2222);
  });

  it('writeLock updates the port; releaseLock removes only our own lock', () => {
    acquireLock(info(4242), home, () => true);
    writeLock(info(4242, 51000), home);
    expect(readLock(home)?.port).toBe(51000);
    releaseLock(9999, home);
    expect(existsSync(lockPath(home))).toBe(true);
    releaseLock(4242, home);
    expect(existsSync(lockPath(home))).toBe(false);
    releaseLock(4242, home); // a missing lock is fine
  });

  it('readLock returns null when there is no lock', () => {
    expect(readLock(home)).toBeNull();
  });
});

describe('pidAlive (the lock liveness rule)', () => {
  it('ESRCH means dead, EPERM means alive', () => {
    const kill = vi.spyOn(process, 'kill');
    kill.mockImplementationOnce(() => {
      throw Object.assign(new Error('x'), { code: 'ESRCH' });
    });
    expect(pidAlive(1234)).toBe(false);
    kill.mockImplementationOnce(() => {
      throw Object.assign(new Error('x'), { code: 'EPERM' });
    });
    expect(pidAlive(1234)).toBe(true);
  });
});
