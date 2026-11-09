import { describe, expect, it } from 'vitest';
import {
  createUpdater,
  fetchLatestVersion,
  isGlobalInstall,
  RETRY_AFTER_MS,
  UPDATE_EVERY_MS,
  UPDATE_FIRST_MS,
  type UpdateDeps,
} from '../../src/hub/selfUpdate.js';

// POSIX paths: the rig checks with platform 'linux', whatever the host.
const ROOT = '/npm/node_modules';
const PKG = '/npm/node_modules/@caddis/cli';

interface Rig {
  deps: UpdateDeps;
  calls: string[];
  logs: string[];
  state: { latest: string | null; disk: string | null; installOk: boolean; diskAfterInstall: string | null; clock: number };
  timers: { fn: () => void; ms: number }[];
}

function rig(over: Partial<UpdateDeps> = {}): Rig {
  const calls: string[] = [];
  const logs: string[] = [];
  const timers: { fn: () => void; ms: number }[] = [];
  const state = { latest: '1.0.1' as string | null, disk: '1.0.0' as string | null, installOk: true, diskAfterInstall: '1.0.1' as string | null, clock: 0 };
  const deps: UpdateDeps = {
    currentVersion: '1.0.0',
    packageRoot: PKG,
    autoUpdate: () => true,
    fetchLatest: async () => {
      calls.push('fetch');
      return state.latest;
    },
    globalRoot: async () => {
      calls.push('npm-root');
      return ROOT;
    },
    install: async (v) => {
      calls.push(`install:${v}`);
      if (state.installOk) state.disk = state.diskAfterInstall;
      return state.installOk ? { ok: true, detail: '' } : { ok: false, detail: 'EBUSY' };
    },
    readVersion: () => state.disk,
    onInstalled: async (v) => void calls.push(`restart:${v}`),
    log: (t) => logs.push(t),
    now: () => state.clock,
    after: (fn, ms) => {
      timers.push({ fn, ms });
      return () => {};
    },
    platform: 'linux',
    ...over,
  };
  return { deps, calls, logs, state, timers };
}

describe('isGlobalInstall', () => {
  it('is true for <npm root -g>/@caddis/cli', () => {
    expect(isGlobalInstall(PKG, ROOT, 'linux')).toBe(true);
  });

  it('is false for a dev checkout or an npx cache', () => {
    expect(isGlobalInstall('/src/caddis/cli', ROOT, 'linux')).toBe(false);
    expect(isGlobalInstall('/home/u/.npm/_npx/abc/node_modules/@caddis/cli', ROOT, 'linux')).toBe(false);
  });

  it('ignores case and a trailing separator on Windows only', () => {
    const win = 'C:\\Users\\me\\AppData\\Roaming\\npm\\node_modules';
    const pkg = 'c:\\users\\me\\appdata\\roaming\\npm\\node_modules\\@caddis\\cli\\';
    expect(isGlobalInstall(pkg, win, 'win32')).toBe(true);
    expect(isGlobalInstall('/NPM/NODE_MODULES/@caddis/cli', ROOT, 'linux')).toBe(false);
  });
});

describe('fetchLatestVersion', () => {
  it('reads `version` from the registry answer', async () => {
    const seen: string[] = [];
    const v = await fetchLatestVersion(async (url) => {
      seen.push(String(url));
      return new Response(JSON.stringify({ name: '@caddis/cli', version: '0.4.99' }), { status: 200 });
    });
    expect(v).toBe('0.4.99');
    expect(seen).toEqual(['https://registry.npmjs.org/@caddis/cli/latest']);
  });

  it('throws on an HTTP error, so the check logs it', async () => {
    await expect(fetchLatestVersion(async () => new Response('nope', { status: 503 }))).rejects.toThrow(/503/);
  });

  it('returns null for a version that is not plain x.y.z (it goes into an npm command line)', async () => {
    const v = await fetchLatestVersion(async () => new Response(JSON.stringify({ version: '1.0.0 & calc' }), { status: 200 }));
    expect(v).toBeNull();
  });
});

describe('createUpdater', () => {
  it('first check after 60 s, then every 30 min', async () => {
    const r = rig();
    r.state.latest = '1.0.0';
    const u = createUpdater(r.deps);
    u.start();
    expect(r.timers.map((t) => t.ms)).toEqual([UPDATE_FIRST_MS]);
    r.timers[0]!.fn();
    await u.idle();
    expect(r.timers.map((t) => t.ms)).toEqual([UPDATE_FIRST_MS, UPDATE_EVERY_MS]);
  });

  it('does nothing when the published version is not newer', async () => {
    for (const latest of ['1.0.0', '0.9.9', null]) {
      const r = rig();
      r.state.latest = latest;
      await createUpdater(r.deps).tick();
      expect(r.calls).toEqual(['fetch']);
    }
  });

  it('a newer version: install the exact version, check the disk, then restart', async () => {
    const r = rig();
    await createUpdater(r.deps).tick();
    expect(r.calls).toEqual(['fetch', 'npm-root', 'install:1.0.1', 'restart:1.0.1']);
  });

  it('compares by number, not by text (1.0.10 is newer than 1.0.9)', async () => {
    const r = rig({ currentVersion: '1.0.9' });
    r.state.disk = '1.0.9';
    r.state.latest = '1.0.10';
    r.state.diskAfterInstall = '1.0.10';
    await createUpdater(r.deps).tick();
    expect(r.calls).toContain('install:1.0.10');
  });

  it('a hub that does not run from the global npm install never installs', async () => {
    const r = rig({ packageRoot: '/src/caddis/cli' });
    const u = createUpdater(r.deps);
    await u.tick();
    await u.tick();
    expect(r.calls.filter((c) => c.startsWith('install') || c.startsWith('restart'))).toEqual([]);
    // It says so once per version, not on every check.
    expect(r.logs.filter((l) => l.includes('update available'))).toHaveLength(1);
  });

  it('auto_update false: check and log only', async () => {
    const r = rig({ autoUpdate: () => false });
    await createUpdater(r.deps).tick();
    expect(r.calls).toEqual(['fetch']);
    expect(r.logs.join('\n')).toMatch(/1\.0\.1 is available.*auto_update/);
  });

  it('a manual install (disk version differs from the running one): restart, no install, no fetch', async () => {
    const r = rig();
    r.state.disk = '1.0.5';
    await createUpdater(r.deps).tick();
    expect(r.calls).toEqual(['restart:1.0.5']);
  });

  it('an install that fails does not restart, and backs off for an hour per version', async () => {
    const r = rig();
    r.state.installOk = false;
    const u = createUpdater(r.deps);
    await u.tick();
    expect(r.calls).toEqual(['fetch', 'npm-root', 'install:1.0.1']);
    expect(r.logs.join('\n')).toMatch(/install of 1\.0\.1 failed.*EBUSY/);

    r.calls.length = 0;
    r.state.clock = RETRY_AFTER_MS - 1;
    await u.tick();
    expect(r.calls).toEqual(['fetch']);

    r.calls.length = 0;
    r.state.clock = RETRY_AFTER_MS;
    await u.tick();
    expect(r.calls).toEqual(['fetch', 'install:1.0.1']);
  });

  it('a new published version is tried at once, even inside the back-off of an older one', async () => {
    const r = rig();
    r.state.installOk = false;
    const u = createUpdater(r.deps);
    await u.tick();
    r.state.latest = '1.0.2';
    r.state.installOk = true;
    r.state.diskAfterInstall = '1.0.2';
    r.calls.length = 0;
    await u.tick();
    expect(r.calls).toEqual(['fetch', 'install:1.0.2', 'restart:1.0.2']);
  });

  it('an install that reports success but leaves another version on disk does not restart', async () => {
    const r = rig();
    r.state.diskAfterInstall = '1.0.0';
    await createUpdater(r.deps).tick();
    expect(r.calls).toEqual(['fetch', 'npm-root', 'install:1.0.1']);
    expect(r.logs.join('\n')).toMatch(/package\.json shows 1\.0\.0/);
  });

  it('installing() is true only while npm runs', async () => {
    const r = rig();
    const u = createUpdater(r.deps);
    const seen: boolean[] = [];
    r.deps.install = async () => {
      seen.push(u.installing());
      r.state.disk = '1.0.1';
      return { ok: true, detail: '' };
    };
    await u.tick();
    expect(seen).toEqual([true]);
    expect(u.installing()).toBe(false);
  });

  it('a failed registry read is logged and never rejects', async () => {
    const r = rig({
      fetchLatest: async () => {
        throw new Error('getaddrinfo ENOTFOUND registry.npmjs.org');
      },
    });
    await expect(createUpdater(r.deps).tick()).resolves.toBeUndefined();
    expect(r.logs.join('\n')).toMatch(/update check failed.*ENOTFOUND/);
  });

  it('npm root -g that fails: no install, try again on the next check', async () => {
    let n = 0;
    const r = rig({
      globalRoot: async () => {
        n++;
        return n === 1 ? null : ROOT;
      },
    });
    const u = createUpdater(r.deps);
    await u.tick();
    expect(r.calls).toEqual(['fetch']);
    await u.tick();
    expect(r.calls).toEqual(['fetch', 'fetch', 'install:1.0.1', 'restart:1.0.1']);
  });

  it('stop cancels the next check', async () => {
    let cancelled = 0;
    const r = rig({
      after: () => () => {
        cancelled++;
      },
    });
    const u = createUpdater(r.deps);
    u.start();
    u.stop();
    expect(cancelled).toBe(1);
  });
});
