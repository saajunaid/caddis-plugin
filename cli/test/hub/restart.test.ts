import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { createRestarter, readInstalledVersion, type ChildHandle, type RestartDeps } from '../../src/hub/restart.js';

interface Rig {
  deps: RestartDeps;
  calls: string[];
  state: { version: string | null; newServerWorks: boolean; childExits: boolean; clock: number };
  exitCodes: number[];
}

function rig(): Rig {
  const calls: string[] = [];
  const exitCodes: number[] = [];
  const state = { version: '1.0.0' as string | null, newServerWorks: true, childExits: false, clock: 0 };
  const deps: RestartDeps = {
    currentVersion: '1.0.0',
    readVersion: () => state.version,
    closeServer: async () => void calls.push('close'),
    spawnNew: () => {
      calls.push('spawn');
      const child: ChildHandle = {
        pid: 42,
        exited: state.childExits ? Promise.resolve(1) : new Promise<number | null>(() => {}),
      };
      return child;
    },
    probe: async () => {
      calls.push('probe');
      return state.newServerWorks ? state.version : null;
    },
    restartOwn: async () => void calls.push('restartOwn'),
    killChild: async () => void calls.push('kill'),
    exit: (c) => {
      calls.push('exit');
      exitCodes.push(c);
    },
    log: (t) => calls.push(`log:${t}`),
    every: () => () => {},
    sleep: async (ms) => {
      state.clock += ms;
    },
    now: () => state.clock,
    waitMs: 1000,
  };
  return { deps, calls, state, exitCodes };
}

const steps = (calls: string[]): string[] => calls.filter((c) => !c.startsWith('log:'));

describe('createRestarter', () => {
  it('does nothing when the version is unchanged', async () => {
    const r = rig();
    await createRestarter(r.deps).tick();
    expect(steps(r.calls)).toEqual([]);
  });

  it('does nothing when package.json does not parse', async () => {
    const r = rig();
    r.state.version = null;
    await createRestarter(r.deps).tick();
    expect(steps(r.calls)).toEqual([]);
  });

  it('a changed version restarts once, in order, then exits 0', async () => {
    const r = rig();
    r.state.version = '1.1.0';
    const rs = createRestarter(r.deps);
    await rs.tick();
    expect(steps(r.calls)).toEqual(['close', 'spawn', 'probe', 'exit']);
    expect(r.exitCodes).toEqual([0]);
  });

  it('waits until the new server answers with the new version', async () => {
    const r = rig();
    r.state.version = '1.1.0';
    let n = 0;
    r.deps.probe = async () => (++n < 3 ? null : '1.1.0');
    await createRestarter(r.deps).tick();
    expect(n).toBe(3);
    expect(r.exitCodes).toEqual([0]);
  });

  it('a failed new server rolls back and the same version is not retried', async () => {
    const r = rig();
    r.state.version = '1.1.0';
    r.state.newServerWorks = false;
    const rs = createRestarter(r.deps);
    await rs.tick();
    expect(steps(r.calls)).toContain('restartOwn');
    expect(steps(r.calls)).toContain('kill');
    expect(r.exitCodes).toEqual([]);
    expect(r.calls.some((c) => c.startsWith('log:') && c.includes('failed'))).toBe(true);
    r.calls.length = 0;
    await rs.tick();
    await rs.tick();
    expect(r.calls).toEqual([]);
  });

  it('rolls back at once when the child exits', async () => {
    const r = rig();
    r.state.version = '1.1.0';
    r.state.childExits = true;
    await createRestarter(r.deps).tick();
    expect(steps(r.calls)).toEqual(['close', 'spawn', 'kill', 'restartOwn']);
  });

  it('a later new version is tried again after a failure', async () => {
    const r = rig();
    r.state.version = '1.1.0';
    r.state.newServerWorks = false;
    const rs = createRestarter(r.deps);
    await rs.tick();
    r.calls.length = 0;
    r.state.version = '1.2.0';
    r.state.newServerWorks = true;
    await rs.tick();
    expect(steps(r.calls)).toEqual(['close', 'spawn', 'probe', 'exit']);
  });

  it('a close that fails rolls back: tick never rejects, and the next tick can run', async () => {
    const r = rig();
    r.state.version = '1.1.0';
    r.deps.closeServer = async () => {
      r.calls.push('close');
      throw new Error('close failed');
    };
    const rs = createRestarter(r.deps);
    await expect(rs.tick()).resolves.toBeUndefined();
    expect(steps(r.calls)).toEqual(['close', 'restartOwn']);
    expect(r.calls.some((c) => c.includes('close failed'))).toBe(true);
    r.state.version = '1.2.0';
    await rs.tick(); // busy was reset
    expect(steps(r.calls).slice(2)).toEqual(['close', 'restartOwn']);
  });

  it('tick never rejects, even when the rollback log throws', async () => {
    const r = rig();
    r.state.version = '1.1.0';
    r.deps.closeServer = async () => {
      throw new Error('close failed');
    };
    r.deps.restartOwn = async () => {
      throw new Error('no port');
    };
    let first = true;
    r.deps.log = () => {
      if (first) {
        first = false;
        return;
      }
      throw new Error('log broke');
    };
    await expect(createRestarter(r.deps).tick()).resolves.toBeUndefined();
  });

  it('exits 1 when the old server cannot be restarted', async () => {
    const r = rig();
    r.state.version = '1.1.0';
    r.state.newServerWorks = false;
    r.deps.restartOwn = async () => {
      throw new Error('port taken');
    };
    await createRestarter(r.deps).tick();
    expect(r.exitCodes).toEqual([1]);
  });

  it('start schedules one timer and stop cancels it', () => {
    const r = rig();
    let cancelled = 0;
    let scheduled = 0;
    r.deps.every = (_fn, ms) => {
      scheduled++;
      expect(ms).toBe(60_000);
      return () => void cancelled++;
    };
    const rs = createRestarter(r.deps);
    rs.start();
    rs.start();
    rs.stop();
    expect([scheduled, cancelled]).toEqual([1, 1]);
  });
});

describe('readInstalledVersion', () => {
  let dir: string;
  beforeEach(() => {
    dir = mkdtempSync(path.join(tmpdir(), 'caddis-hub-'));
  });
  afterEach(() => rmSync(dir, { recursive: true, force: true }));

  it('reads the version fresh, and returns null for a missing or corrupt file', () => {
    expect(readInstalledVersion(dir)).toBeNull();
    writeFileSync(path.join(dir, 'package.json'), '{ "version": "2.0.0" }');
    expect(readInstalledVersion(dir)).toBe('2.0.0');
    writeFileSync(path.join(dir, 'package.json'), '{ "version": "2.0');
    expect(readInstalledVersion(dir)).toBeNull();
    writeFileSync(path.join(dir, 'package.json'), '{}');
    expect(readInstalledVersion(dir)).toBeNull();
  });
});
