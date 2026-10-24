import http from 'node:http';
import net from 'node:net';
import { mkdtempSync, rmSync, readFileSync, existsSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { spawn, spawnSync, type ChildProcess } from 'node:child_process';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { lockPath, keyPath, configPath } from '../../src/hub/paths.js';
import { readLock } from '../../src/hub/lock.js';
import { writeJsonAtomic, resetHubCache } from '../../src/hub/config.js';
import { packageInfo } from '../../src/util/pkg.js';
import {
  startHub,
  hubServe,
  hubStart,
  hubStop,
  hubStatus,
  hubOpen,
  isNodeProcess,
  killTree,
  SPAWN_OPTIONS,
  START_WAIT_MS,
  processStartMs,
  type HubDeps,
  type RunningHub,
  type Spawner,
} from '../../src/commands/hub.js';

let home: string;
let out: string[];
let err: string[];
let hubs: RunningHub[];
let fakes: http.Server[];
let children: ChildProcess[];
const savedHome = process.env.CADDIS_HOME;
const versions = { cli: '0.0.0-test', caddis: '0.0.0-test' };
const fakeIcacls = async () => ({ ok: true, code: 0, stdout: '', stderr: '' });

beforeEach(() => {
  home = mkdtempSync(path.join(tmpdir(), 'caddis-hub-'));
  process.env.CADDIS_HOME = home;
  resetHubCache();
  out = [];
  err = [];
  hubs = [];
  fakes = [];
  children = [];
  vi.spyOn(process.stdout, 'write').mockImplementation((c: unknown) => {
    out.push(String(c));
    return true;
  });
  vi.spyOn(process.stderr, 'write').mockImplementation((c: unknown) => {
    err.push(String(c));
    return true;
  });
});
afterEach(async () => {
  for (const h of hubs) await h.stop();
  for (const f of fakes) {
    f.closeAllConnections();
    await new Promise<void>((r) => f.close(() => r()));
  }
  for (const c of children) c.kill();
  if (savedHome === undefined) delete process.env.CADDIS_HOME;
  else process.env.CADDIS_HOME = savedHome;
  rmSync(home, { recursive: true, force: true });
});

// eslint-disable-next-line no-control-regex
const plain = (a: string[]): string => a.join('').replace(/\x1b\[[0-9;]*m/g, '');
const stdout = (): string => plain(out);
const stderr = (): string => plain(err);

// A state with no timers: lifecycle tests never run the real `claude`, `gh` or python sources.
const fakeState = (): NonNullable<HubDeps['state']> => ({
  start: () => {},
  stop: () => {},
  refreshAll: async () => {},
  repoPaths: () => [],
  getState: () => ({
    schema: 1,
    generated_at: '2026-10-24T10:00:00.000Z',
    versions: { hub: '0.0.0-test', pool: null, plugin: null },
    sources: {
      collector: { ok: false, last_ok_at: null, last_error: null, stale: true },
      agents: { ok: false, last_ok_at: null, last_error: null, stale: true },
      github: { ok: false, last_ok_at: null, last_error: null, stale: true },
      coordinator: { ok: false, last_ok_at: null, last_error: null, stale: true },
    },
    update_needed: false,
    repos: [],
    sessions: [],
    spend: null,
    guide: null,
  }),
});

function deps(extra: Partial<HubDeps> = {}): HubDeps {
  return { home, port: 0, versions, runCmd: fakeIcacls, state: fakeState(), ...extra };
}

async function serveInProcess(extra: Partial<HubDeps> = {}): Promise<RunningHub> {
  const h = await startHub(deps(extra));
  hubs.push(h);
  return h;
}

/** A spawner that runs `hub serve` inside this test process (no child). */
function inProcessSpawner(extra: Partial<HubDeps> = {}): { spawn: Spawner; calls: string[][] } {
  const calls: string[][] = [];
  const spawn: Spawner = (cmd, args) => {
    calls.push([cmd, ...args]);
    const exited = startHub(deps(extra)).then(
      (h) => {
        hubs.push(h);
        return h.done.then(() => 0);
      },
      () => 1,
    );
    return { pid: process.pid, exited };
  };
  return { spawn, calls };
}

function get(port: number, p: string, headers: Record<string, string> = {}): Promise<{ status: number; body: string }> {
  return new Promise((resolve, reject) => {
    const r = http.request(
      { host: '127.0.0.1', port, path: p, method: 'GET', headers: { host: `127.0.0.1:${port}`, ...headers }, agent: false },
      (res) => {
        const c: Buffer[] = [];
        res.on('data', (d: Buffer) => c.push(d));
        res.on('end', () => resolve({ status: res.statusCode ?? 0, body: Buffer.concat(c).toString('utf8') }));
      },
    );
    r.on('error', reject);
    r.end();
  });
}

/** The pid of a process that has already exited. */
function deadPid(): number {
  const r = spawnSync(process.execPath, ['-e', ''], { windowsHide: true });
  return r.pid!;
}

async function closedPort(): Promise<number> {
  const s = net.createServer();
  await new Promise<void>((r) => s.listen(0, '127.0.0.1', () => r()));
  const port = (s.address() as net.AddressInfo).port;
  await new Promise<void>((r) => s.close(() => r()));
  return port;
}

const HOUR_AGO = (): string => new Date(Date.now() - 3_600_000).toISOString();

function writeLockFile(pid: number, port: number, extra: Record<string, unknown> = {}): void {
  mkdirSync(path.dirname(lockPath(home)), { recursive: true });
  writeJsonAtomic(lockPath(home), { pid, started_at: HOUR_AGO(), port, ...extra });
}

interface FakeHub {
  port: number;
  seen: http.IncomingHttpHeaders[];
}

/** A local listener that records every request's headers. afterEach closes it. */
async function fakeHub(handler: (req: http.IncomingMessage, res: http.ServerResponse) => void): Promise<FakeHub> {
  const seen: http.IncomingHttpHeaders[] = [];
  const s = http.createServer((req, res) => {
    seen.push(req.headers);
    handler(req, res);
  });
  await new Promise<void>((r) => s.listen(0, '127.0.0.1', () => r()));
  fakes.push(s);
  return { port: (s.address() as net.AddressInfo).port, seen };
}

const json = (res: http.ServerResponse, status: number, body: unknown): void => {
  res.writeHead(status, { 'content-type': 'application/json' });
  res.end(JSON.stringify(body));
};

const key = (): string => readFileSync(keyPath(home), 'utf8').trim();

describe('serve (in process)', () => {
  it('takes the lock, writes the real port, answers health with the key', async () => {
    const h = await serveInProcess();
    expect(h.port).toBeGreaterThan(0);
    const lock = readLock(home);
    expect(lock).toMatchObject({ pid: process.pid, port: h.port });
    expect(lock?.started_at).toMatch(/Z$/);
    const r = await get(h.port, '/api/health', { 'x-caddis-hub-key': key() });
    expect(r.status).toBe(200);
    expect(readFileSync(lockPath(home), 'utf8').includes(key())).toBe(false);
  });

  it('removes the lock when it stops', async () => {
    const h = await serveInProcess();
    await h.stop();
    await h.done;
    expect(existsSync(lockPath(home))).toBe(false);
  });

  it('a second serve refuses while the first holds the lock', async () => {
    await serveInProcess();
    await expect(startHub(deps())).rejects.toThrow(/already running/);
  });

  it('hubServe runs until stop, returns 0, and removes its signal handlers', async () => {
    const before = process.listenerCount('SIGTERM');
    const serving = hubServe(deps());
    const deadline = Date.now() + 5000;
    while (!readLock(home)?.port && Date.now() < deadline) await new Promise((r) => setTimeout(r, 20));
    expect(process.listenerCount('SIGTERM')).toBe(before + 1);
    expect(await hubStop(deps())).toBe(0);
    expect(await serving).toBe(0);
    expect(process.listenerCount('SIGTERM')).toBe(before);
    expect(existsSync(lockPath(home))).toBe(false);
  });

  it('hubServe returns 1 with a clear message when the lock is held', async () => {
    const h = await serveInProcess();
    expect(await hubServe(deps())).toBe(1);
    expect(stderr()).toMatch(new RegExp(`already running.*pid ${process.pid}.*port ${h.port}`));
  });
});

describe('start', () => {
  it('spawns `hub serve`, waits for health, prints the URL and the open hint', async () => {
    const { spawn, calls } = inProcessSpawner();
    const code = await hubStart(deps({ spawn, entry: 'cli-entry.js' }));
    expect(code).toBe(0);
    expect(calls).toEqual([[process.execPath, 'cli-entry.js', 'hub', 'serve']]);
    const port = readLock(home)!.port;
    expect(stdout()).toContain(`caddis hub running on http://127.0.0.1:${port}/`);
    expect(stdout()).toContain('open it with: caddis hub open');
    expect(stdout() + stderr()).not.toContain(key());
  });

  it('a second start refuses with exit 1 and names the pid and port', async () => {
    const h = await serveInProcess();
    const { spawn, calls } = inProcessSpawner();
    expect(await hubStart(deps({ spawn }))).toBe(1);
    expect(calls).toHaveLength(0);
    expect(stderr()).toContain(`pid ${process.pid}`);
    expect(stderr()).toContain(`port ${h.port}`);
  });

  it('takes over a stale lock (dead pid)', async () => {
    writeLockFile(deadPid(), 1);
    const { spawn } = inProcessSpawner();
    expect(await hubStart(deps({ spawn }))).toBe(0);
    expect(readLock(home)?.pid).toBe(process.pid);
  });

  it('fails with exit 1 when the child exits before it is healthy', async () => {
    const spawn: Spawner = () => ({ pid: 999_999, exited: Promise.resolve(1) });
    expect(await hubStart(deps({ spawn, startWaitMs: 2000 }))).toBe(1);
    expect(stderr()).toMatch(/exited/);
  });

  it('fails with exit 1 after the wait and kills the silent child', async () => {
    const kills: number[] = [];
    const spawn: Spawner = () => ({ pid: 999_998, exited: new Promise(() => {}) });
    const code = await hubStart(
      deps({ spawn, startWaitMs: 300, alive: () => true, kill: async (pid) => void kills.push(pid) }),
    );
    expect(code).toBe(1);
    expect(kills).toEqual([999_998]);
    expect(stderr()).toMatch(/did not answer/);
  });

  it('the real spawn is detached, hidden, no shell, stdio ignored', () => {
    expect(SPAWN_OPTIONS).toMatchObject({ detached: true, stdio: 'ignore', windowsHide: true, shell: false });
    expect(START_WAIT_MS).toBe(20_000);
  });
});

describe('port rule (config.json)', () => {
  for (const bad of [0, 70000, -1, 1.5]) {
    it(`start and serve refuse port ${bad} with a clear error`, async () => {
      writeJsonAtomic(configPath(home), { schema: 1, port: bad });
      resetHubCache();
      const { spawn, calls } = inProcessSpawner();
      const d: HubDeps = { home, versions, runCmd: fakeIcacls, spawn };
      expect(await hubStart(d)).toBe(1);
      expect(await hubServe(d)).toBe(1);
      expect(calls).toHaveLength(0);
      expect(stderr()).toMatch(/port .*1-65535/);
      expect(existsSync(lockPath(home))).toBe(false);
    });
  }
});

describe('status', () => {
  it('prints port, pid, versions and uptime when running', async () => {
    let t = Date.parse('2026-10-24T10:00:00.000Z');
    const h = await serveInProcess({ now: () => t });
    t += 125_000;
    expect(await hubStatus(deps({ now: () => t }))).toBe(0);
    const s = stdout();
    expect(s).toContain(`http://127.0.0.1:${h.port}/`);
    expect(s).toContain(`pid ${process.pid}`);
    expect(s).toContain('0.0.0-test');
    expect(s).toMatch(/uptime 2m 5s/);
  });

  it('--json prints {schema, running, port, pid, versions}', async () => {
    const h = await serveInProcess();
    expect(await hubStatus({ ...deps(), json: true })).toBe(0);
    expect(JSON.parse(stdout())).toEqual({ schema: 1, running: true, port: h.port, pid: process.pid, versions });
  });

  it('exits 1 when down (text and json)', async () => {
    expect(await hubStatus(deps())).toBe(1);
    expect(stdout() + stderr()).toMatch(/not running/);
    out.length = 0;
    expect(await hubStatus({ ...deps(), json: true })).toBe(1);
    expect(JSON.parse(stdout())).toEqual({ schema: 1, running: false, port: null, pid: null, versions: null });
  });
});

describe('stop', () => {
  it('asks the server to stop with the key; the lock goes; status then says down', async () => {
    const h = await serveInProcess();
    expect(await hubStop(deps())).toBe(0);
    await h.done;
    expect(existsSync(lockPath(home))).toBe(false);
    expect(stdout()).toMatch(/stopped/);
    expect(await hubStatus(deps())).toBe(1);
  });

  it('exits 0 when already down', async () => {
    expect(await hubStop(deps())).toBe(0);
    expect(stdout()).toMatch(/not running/);
  });

  it('removes a stale lock and exits 0', async () => {
    writeLockFile(deadPid(), 1);
    expect(await hubStop(deps())).toBe(0);
    expect(existsSync(lockPath(home))).toBe(false);
  });

  it('kills a live pid that does not answer, then removes the lock', async () => {
    writeLockFile(424_242, await closedPort());
    let killed = false;
    const kills: number[] = [];
    const code = await hubStop(
      deps({
        stopWaitMs: 300,
        alive: () => !killed,
        isHubPid: async () => true,
        processStart: async () => Date.now() - 7_200_000, // started before the lock: our hub
        kill: async (pid) => {
          kills.push(pid);
          killed = true;
        },
      }),
    );
    expect(code).toBe(0);
    expect(kills).toEqual([424_242]);
    expect(existsSync(lockPath(home))).toBe(false);
  });

  it('does not kill a live pid that is not a node process; removes the stale lock', async () => {
    writeLockFile(424_242, await closedPort());
    const kills: number[] = [];
    const code = await hubStop(
      deps({
        stopWaitMs: 300,
        alive: () => true,
        isHubPid: async () => false,
        processStart: async () => Date.now() - 7_200_000,
        kill: async (p) => void kills.push(p),
      }),
    );
    expect(code).toBe(0);
    expect(kills).toEqual([]);
    expect(existsSync(lockPath(home))).toBe(false);
  });

  it('does not kill a pid that started after the lock (pid reuse); removes the stale lock', async () => {
    writeLockFile(424_242, await closedPort());
    const kills: number[] = [];
    const code = await hubStop(
      deps({
        stopWaitMs: 300,
        alive: () => true,
        isHubPid: async () => true,
        processStart: async () => Date.now(),
        kill: async (p) => void kills.push(p),
      }),
    );
    expect(code).toBe(0);
    expect(kills).toEqual([]);
    expect(existsSync(lockPath(home))).toBe(false);
  });
});

describe('kill helpers (real child process)', () => {
  it('isNodeProcess is true for a live node child; killTree ends it; then false', async () => {
    const child = spawn(process.execPath, ['-e', 'setTimeout(() => {}, 60000)'], { windowsHide: true, stdio: 'ignore' });
    const pid = child.pid!;
    const gone = new Promise<void>((r) => child.once('exit', () => r()));
    try {
      expect(await isNodeProcess(pid)).toBe(true);
      await killTree(pid);
      await gone;
      expect(await isNodeProcess(pid)).toBe(false);
    } finally {
      child.kill();
    }
  }, 30_000);
});

describe('lock identity: a reused pid held by an unrelated node process', () => {
  const INSTANCE = 'aa'.repeat(16);

  async function unrelatedNode(): Promise<ChildProcess> {
    const c = spawn(process.execPath, ['-e', 'setTimeout(() => {}, 20000)'], { windowsHide: true, stdio: 'ignore' });
    children.push(c);
    await new Promise<void>((r) => c.once('spawn', () => r()));
    return c;
  }

  const sentKey = (f: FakeHub): boolean => f.seen.some((h) => h['x-caddis-hub-key'] !== undefined);

  async function makeKey(): Promise<void> {
    const { ensureKey } = await import('../../src/hub/keyfile.js');
    await ensureKey({ home, runCmd: fakeIcacls });
  }

  it('processStartMs gives the real start time of a live process', async () => {
    const before = Date.now();
    const c = await unrelatedNode();
    const t = await processStartMs(c.pid!);
    expect(t).not.toBeNull();
    expect(t!).toBeGreaterThanOrEqual(before - 2000);
    expect(t!).toBeLessThanOrEqual(Date.now() + 1000);
  }, 30_000);

  it('status and open report down and never send the key to the lock port', async () => {
    await makeKey();
    const f = await fakeHub((_req, res) => json(res, 200, { instance: 'bb'.repeat(16), ok: true, code: 'x' }));
    const c = await unrelatedNode();
    writeLockFile(c.pid!, f.port, { instance: INSTANCE });
    expect(await hubStatus(deps())).toBe(1);
    expect(await hubOpen(deps({ opener: async () => true }))).toBe(1);
    expect(f.seen.length).toBeGreaterThan(0); // whoami was asked
    expect(sentKey(f)).toBe(false);
  }, 30_000);

  it('stop does not kill it, removes the stale lock, and never sends the key', async () => {
    await makeKey();
    const f = await fakeHub((_req, res) => json(res, 404, { error: 'not_found' }));
    const c = await unrelatedNode();
    writeLockFile(c.pid!, f.port, { instance: INSTANCE });
    expect(await hubStop(deps({ stopWaitMs: 300 }))).toBe(0);
    expect(c.exitCode).toBeNull();
    expect(c.signalCode).toBeNull();
    expect(existsSync(lockPath(home))).toBe(false);
    expect(sentKey(f)).toBe(false);
  }, 30_000);

  it('start takes the lock over and never sends the key to the old port', async () => {
    await makeKey();
    const f = await fakeHub((_req, res) => json(res, 404, { error: 'not_found' }));
    const c = await unrelatedNode();
    writeLockFile(c.pid!, f.port, { instance: INSTANCE });
    const { spawn: sp } = inProcessSpawner();
    expect(await hubStart(deps({ spawn: sp }))).toBe(0);
    const lock = readLock(home)!;
    expect(lock.pid).toBe(process.pid);
    expect(lock.instance).toMatch(/^[0-9a-f]{32}$/);
    expect(lock.instance).not.toBe(INSTANCE);
    expect(c.exitCode).toBeNull();
    expect(sentKey(f)).toBe(false);
  }, 30_000);

  it('serve (the logon-task path) also takes the lock over', async () => {
    const c = await unrelatedNode();
    writeLockFile(c.pid!, await closedPort(), { instance: INSTANCE });
    const h = await serveInProcess();
    expect(readLock(home)).toMatchObject({ pid: process.pid, port: h.port });
    expect(c.exitCode).toBeNull();
  }, 30_000);

  it('a live hub refuses a second start', async () => {
    await serveInProcess();
    const { spawn: sp, calls } = inProcessSpawner();
    expect(await hubStart(deps({ spawn: sp }))).toBe(1);
    expect(calls).toHaveLength(0);
  });

  it('open refuses a login code with characters outside [A-Za-z0-9_-]', async () => {
    await makeKey();
    const f = await fakeHub((req, res) => {
      if (req.url === '/api/hub/whoami') return json(res, 200, { instance: INSTANCE });
      if (req.url === '/api/health') return json(res, 200, { schema: 1, ok: true, versions });
      return json(res, 200, { schema: 1, code: 'a&calc', expires_at: new Date(Date.now() + 60_000).toISOString() });
    });
    writeLockFile(424_242, f.port, { instance: INSTANCE });
    const opened: string[] = [];
    const code = await hubOpen(
      deps({
        alive: () => true,
        opener: async (u) => {
          opened.push(u);
          return true;
        },
      }),
    );
    expect(code).toBe(1);
    expect(opened).toEqual([]);
    expect(stderr()).toMatch(/login code/);
    expect(stdout()).not.toContain('a&calc');
  });
});

describe('open', () => {
  it('gets a one-time 60 s code, opens /login?code=..., and always prints the URL', async () => {
    const h = await serveInProcess();
    const opened: string[] = [];
    const opener = async (u: string): Promise<boolean> => {
      opened.push(u);
      return true;
    };
    expect(await hubOpen(deps({ opener }))).toBe(0);
    expect(opened).toHaveLength(1);
    const url = opened[0]!;
    expect(url).toMatch(new RegExp(`^http://127\\.0\\.0\\.1:${h.port}/login\\?code=[A-Za-z0-9_-]+$`));
    expect(stdout()).toContain(url);
    expect(stdout()).toMatch(/60 s/);
    expect(url.includes(key())).toBe(false);
    expect(stdout() + stderr()).not.toContain(key());
    // The code works once.
    const p = new URL(url).pathname + new URL(url).search;
    expect((await get(h.port, p)).status).toBe(303);
    expect((await get(h.port, p)).status).toBe(401);
  });

  it('prints the URL and exits 0 when no browser opens', async () => {
    const h = await serveInProcess();
    expect(await hubOpen(deps({ opener: async () => false }))).toBe(0);
    expect(stdout()).toContain(`http://127.0.0.1:${h.port}/login?code=`);
    expect(stdout()).toMatch(/open this URL/);
  });

  it('exits 1 when the hub is down', async () => {
    const opened: string[] = [];
    const opener = async (u: string): Promise<boolean> => {
      opened.push(u);
      return true;
    };
    expect(await hubOpen(deps({ opener }))).toBe(1);
    expect(opened).toEqual([]);
    expect(stderr()).toMatch(/not running/);
  });
});

describe('state (H1.7)', () => {
  function raw(port: number, p: string, headers: Record<string, string> = {}) {
    return new Promise<{ status: number; body: string; cookie: string; location: string }>((resolve, reject) => {
      const r = http.request(
        { host: '127.0.0.1', port, path: p, method: 'GET', headers: { host: `127.0.0.1:${port}`, ...headers }, agent: false },
        (res) => {
          const c: Buffer[] = [];
          res.on('data', (d: Buffer) => c.push(d));
          res.on('end', () =>
            resolve({
              status: res.statusCode ?? 0,
              body: Buffer.concat(c).toString('utf8'),
              cookie: String(res.headers['set-cookie']?.[0] ?? '').split(';')[0] ?? '',
              location: String(res.headers.location ?? ''),
            }),
          );
        },
      );
      r.on('error', reject);
      r.end();
    });
  }

  it('starts the state timers with the server, serves its state behind the session, and stops them', async () => {
    const calls: string[] = [];
    const state = { ...fakeState(), start: () => void calls.push('start'), stop: () => void calls.push('stop') };
    const h = await serveInProcess({ state });
    expect(calls).toEqual(['start']);
    expect((await raw(h.port, '/api/state')).status).toBe(401);
    const opened: string[] = [];
    await hubOpen(deps({ opener: async (u) => (opened.push(u), true) }));
    const u = new URL(opened[0]!);
    const login = await raw(h.port, u.pathname + u.search);
    expect(login.status).toBe(303);
    const tab = /^\/#tab=([A-Za-z0-9_-]{43})$/.exec(login.location)?.[1] ?? '';
    expect(tab).not.toBe('');
    expect((await raw(h.port, '/api/state', { cookie: login.cookie })).status).toBe(401); // the cookie alone (I2)
    const res = await raw(h.port, '/api/state', { cookie: login.cookie, 'x-caddis-hub-tab': tab });
    expect(res.status).toBe(200);
    expect(JSON.parse(res.body)).toMatchObject({ schema: 1, update_needed: false, repos: [], spend: null });
    await h.stop();
    expect(calls).toEqual(['start', 'stop']);
  });
});

describe('an alive hub that does not answer (final review I5)', () => {
  // A live pid that started before its lock (so it wrote the lock), a silent port, a lock 60 s old.
  async function silentHub(): Promise<Partial<HubDeps>> {
    mkdirSync(path.dirname(lockPath(home)), { recursive: true });
    writeJsonAtomic(lockPath(home), {
      pid: 424_242,
      started_at: new Date(Date.now() - 60_000).toISOString(),
      port: await closedPort(),
      instance: 'a'.repeat(32),
    });
    return { alive: (pid) => pid === 424_242, processStart: async () => Date.now() - 7_200_000 };
  }

  it('start refuses with a clear message, spawns nothing and keeps the lock', async () => {
    const extra = await silentHub();
    const before = readFileSync(lockPath(home), 'utf8');
    const { spawn, calls } = inProcessSpawner();
    expect(await hubStart(deps({ ...extra, spawn }))).toBe(1);
    expect(calls).toHaveLength(0);
    expect(stderr()).toContain('caddis hub pid 424242 holds the lock but does not answer: run caddis hub stop');
    expect(readFileSync(lockPath(home), 'utf8')).toBe(before);
  });

  it('serve refuses it too and keeps the lock', async () => {
    const extra = await silentHub();
    const before = readFileSync(lockPath(home), 'utf8');
    expect(await hubServe(deps(extra))).toBe(1);
    expect(stderr()).toContain('holds the lock but does not answer');
    expect(readFileSync(lockPath(home), 'utf8')).toBe(before);
  });

  it('an unreadable start time is unknown, never stale: start refuses and keeps the lock (I5 re-review)', async () => {
    const extra = await silentHub();
    const before = readFileSync(lockPath(home), 'utf8');
    const { spawn, calls } = inProcessSpawner();
    expect(await hubStart(deps({ ...extra, processStart: async () => null, spawn }))).toBe(1);
    expect(calls).toHaveLength(0);
    expect(stderr()).toContain('holds the lock but does not answer');
    expect(readFileSync(lockPath(home), 'utf8')).toBe(before);
  });

  it('stop with an unreadable start time keeps the lock and kills nothing (I5 re-review)', async () => {
    const extra = await silentHub();
    const before = readFileSync(lockPath(home), 'utf8');
    const killed: number[] = [];
    const code = await hubStop(deps({ ...extra, processStart: async () => null, kill: async (pid: number) => { killed.push(pid); } }));
    expect(code).toBe(1);
    expect(killed).toEqual([]);
    expect(stderr()).toContain('its start time cannot be read; lock kept');
    expect(readFileSync(lockPath(home), 'utf8')).toBe(before);
  });

  it('a pid that started after the lock is still stale (pid reuse) and is taken over', async () => {
    const extra = await silentHub();
    const { spawn } = inProcessSpawner();
    expect(await hubStart(deps({ ...extra, processStart: async () => Date.now(), spawn }))).toBe(0);
    expect(readLock(home)?.pid).toBe(process.pid);
  });
});

describe('cwd of the long-lived serve (final review I6)', () => {
  it('start runs serve with cwd = the hub folder, and creates it first', async () => {
    const seen: { cwd?: string; existed: boolean }[] = [];
    const { spawn: inner } = inProcessSpawner();
    const spawn: Spawner = (cmd, args, opts) => {
      seen.push({ cwd: opts?.cwd, existed: opts?.cwd ? existsSync(opts.cwd) : false });
      return inner(cmd, args, opts);
    };
    expect(await hubStart(deps({ spawn, entry: 'cli-entry.js' }))).toBe(0);
    expect(seen).toEqual([{ cwd: path.dirname(lockPath(home)), existed: true }]);
  });
});

describe('self-restart wiring (H1.8 review)', () => {
  it('the new server runs <package root>/dist/cli.js from the hub folder', async () => {
    let check: (() => void) | null = null;
    const spawned: { args: string[]; cwd?: string }[] = [];
    const spawn: Spawner = (_cmd, args, opts) => {
      spawned.push({ args, cwd: opts?.cwd });
      return { pid: 4242, exited: new Promise(() => {}) };
    };
    const serving = hubServe({
      ...deps({ spawn }),
      restart: {
        readVersion: () => '9.9.9',
        probe: async () => '9.9.9',
        every: (fn) => {
          check = fn;
          return () => {};
        },
      },
    });
    const deadline = Date.now() + 5000;
    while ((!check || !readLock(home)?.port) && Date.now() < deadline) await new Promise((r) => setTimeout(r, 20));
    check!();
    expect(await serving).toBe(0);
    expect(spawned).toEqual([
      { args: [path.join(packageInfo().root, 'dist', 'cli.js'), 'hub', 'serve'], cwd: path.dirname(lockPath(home)) },
    ]);
  });
});
