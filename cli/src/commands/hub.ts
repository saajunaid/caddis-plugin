/**
 * `caddis hub start | stop | status | open | serve` — the hub lifecycle (H1.3).
 *
 * - `serve` runs the server in the foreground. It holds `hub.lock` while it runs.
 * - `start` spawns a hidden, detached `caddis hub serve` and waits for its health check.
 * - `stop` asks the server to exit (key header). When it does not answer, it kills the pid.
 * - The CLI sends the key only to a port whose `GET /api/hub/whoami` answers the lock's `instance`.
 * - `status` asks for health. Exit 1 when the hub is down.
 * - `open` gets a one-time login code and opens the browser. It always prints the URL.
 *
 * The server key never goes into output, a log, the lock file or a URL.
 * Every function takes injectable deps, so tests use a temp home, port 0 and fakes.
 */
import http from 'node:http';
import path from 'node:path';
import { mkdirSync, readFileSync } from 'node:fs';
import { randomBytes } from 'node:crypto';
import { autostartStatus, disableAutostart, enableAutostart, type AutostartDeps } from '../hub/autostart.js';
import { readConfig } from '../hub/config.js';
import { ensureKey, type RunCmd } from '../hub/keyfile.js';
import {
  acquireLock,
  holderAlive,
  readLock,
  releaseLock,
  removeLockIf,
  writeLock,
  type LockInfo,
} from '../hub/lock.js';
import { hubDir, keyPath } from '../hub/paths.js';
import { createRestarter, readInstalledVersion, type RestartDeps } from '../hub/restart.js';
import { KEY_HEADER, startServer } from '../hub/server.js';
import { createHub, type StateHub } from '../hub/state.js';
import { run } from '../util/exec.js';
import { errorLine, line } from '../util/log.js';
import { bundleManifest, packageInfo } from '../util/pkg.js';
import { caddisHome, pidAlive } from '../util/sessions.js';

export interface Spawned {
  pid?: number;
  /** Resolves with the exit code when the child exits. */
  exited: Promise<number | null>;
}
export type Spawner = (cmd: string, args: string[], opts?: { cwd?: string }) => Spawned | Promise<Spawned>;

export interface HubDeps {
  home?: string;
  /** Port override for tests (0 = OS picks). Skips the config.json port rule. */
  port?: number;
  versions?: Record<string, string>;
  /** The state and its source timers. Default: the real sources (`claude`, `gh`, python). Tests pass a fake. */
  state?: StateHub;
  /** Clock in ms for timestamps (lock `started_at`, uptime). Waits use real time. */
  now?: () => number;
  spawn?: Spawner;
  /** The CLI entry script for `start`. Default: `process.argv[1]`. */
  entry?: string;
  /** Opens a URL in the default browser. Resolves false when no browser opened. */
  opener?: (url: string) => Promise<boolean>;
  alive?: (pid: number) => boolean;
  /** Kills a process tree. */
  kill?: (pid: number) => Promise<void>;
  /** Process start time in ms (UTC), or null. Guards against a reused pid. */
  processStart?: (pid: number) => Promise<number | null>;
  /** True when the pid is a node process (second guard for `stop`). */
  isHubPid?: (pid: number) => Promise<boolean>;
  /** Runs icacls for the key file. */
  runCmd?: RunCmd;
  startWaitMs?: number;
  stopWaitMs?: number;
}

export interface RunningHub {
  port: number;
  /** Close the server and remove the lock. Safe to call more than once. */
  stop: () => Promise<void>;
  /** Resolves when the hub has stopped. */
  done: Promise<void>;
}

/** Options for the real `hub serve` child. The child is the long-running server, so it has no timeout (R22 exemption). */
export const SPAWN_OPTIONS = {
  detached: true,
  stdio: 'ignore',
  windowsHide: true,
  shell: false,
  cleanup: false,
  reject: false,
} as const;

/** How long `start` waits for the child's health. A cold first start under AV took 7.6 s. */
export const START_WAIT_MS = 20_000;
const WHOAMI_TIMEOUT_MS = 1_500;
const CODE_RE = /^[A-Za-z0-9_-]+$/;
const STOP_WAIT_MS = 5_000;
const HEALTH_TIMEOUT_MS = 3_000;
const TOOL_TIMEOUT_MS = 15_000;

class HubError extends Error {}

const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));
const hubUrl = (port: number): string => `http://127.0.0.1:${port}/`;
const message = (e: unknown): string => (e instanceof Error ? e.message : String(e));

function defaultVersions(): Record<string, string> {
  return { cli: packageInfo().version, caddis: bundleManifest().poolVersion };
}

/** The port to bind: the test override, or config.json `port`, which must be a whole number in 1-65535. */
function resolvePort(deps: HubDeps): number {
  if (deps.port !== undefined) return deps.port;
  const cfg = readConfig(deps.home);
  if (cfg.error) errorLine(`${cfg.error}; using the last good config`);
  const p = cfg.value.port;
  if (!Number.isInteger(p) || p < 1 || p > 65535) {
    throw new HubError(`config.json port ${p} is not valid: use a whole number in 1-65535`);
  }
  return p;
}

/** Read the key without creating it. Null when it is missing or corrupt. */
function readKeyQuiet(home?: string): string | null {
  try {
    const k = readFileSync(keyPath(home), 'utf8').trim();
    return /^[0-9a-f]{64}$/.test(k) ? k : null;
  } catch {
    return null;
  }
}

interface HubResponse {
  status: number;
  body: Record<string, unknown>;
}

/**
 * One request to the local hub. `key` null: no key header (whoami). Null on any network error or timeout.
 * Callers send a key only to a port that answered whoami with the lock's instance.
 */
function hubRequest(
  method: string,
  port: number,
  p: string,
  key: string | null,
  timeoutMs: number,
): Promise<HubResponse | null> {
  return new Promise((resolve) => {
    const req = http.request(
      {
        host: '127.0.0.1',
        port,
        method,
        path: p,
        headers: { host: `127.0.0.1:${port}`, 'content-length': 0, ...(key ? { [KEY_HEADER]: key } : {}) },
        agent: false,
        timeout: timeoutMs,
      },
      (res) => {
        const chunks: Buffer[] = [];
        res.on('data', (c: Buffer) => chunks.push(c));
        res.on('end', () => {
          let body: Record<string, unknown> = {};
          try {
            body = JSON.parse(Buffer.concat(chunks).toString('utf8')) as Record<string, unknown>;
          } catch {
            /* not JSON */
          }
          resolve({ status: res.statusCode ?? 0, body });
        });
        res.on('error', () => resolve(null));
      },
    );
    req.on('timeout', () => req.destroy());
    req.on('error', () => resolve(null));
    req.end();
  });
}

async function defaultSpawn(cmd: string, args: string[], opts: { cwd?: string } = {}): Promise<Spawned> {
  const { execa } = await import('execa');
  const child = execa(cmd, args, { ...SPAWN_OPTIONS, cwd: opts.cwd });
  child.unref();
  return {
    pid: child.pid,
    exited: child.then(
      (r) => r.exitCode ?? null,
      () => null,
    ),
  };
}

/** Kill a process tree: `taskkill /T /F` on Windows, else SIGTERM to the group, then to the pid. */
export async function killTree(pid: number): Promise<void> {
  if (process.platform === 'win32') {
    await run('taskkill', ['/T', '/F', '/PID', String(pid)], { timeout: TOOL_TIMEOUT_MS });
    return;
  }
  try {
    process.kill(-pid, 'SIGTERM');
  } catch {
    try {
      process.kill(pid, 'SIGTERM');
    } catch {
      /* already gone */
    }
  }
}

/** True when the pid runs node (or this runtime). Guards against killing a reused pid. */
export async function isNodeProcess(pid: number): Promise<boolean> {
  const r =
    process.platform === 'win32'
      ? await run('tasklist', ['/FI', `PID eq ${pid}`, '/FO', 'CSV', '/NH'], { timeout: TOOL_TIMEOUT_MS })
      : await run('ps', ['-p', String(pid), '-o', 'comm='], { timeout: TOOL_TIMEOUT_MS });
  if (!r.ok) return false;
  const name = (r.stdout.split(/\r?\n/)[0] ?? '').replace(/^"([^"]*)".*$/, '$1').trim().toLowerCase();
  if (!name) return false;
  const runtime = path.basename(process.execPath).toLowerCase().replace(/\.exe$/, '');
  return name.includes('node') || name.includes(runtime);
}

/** Open the default browser. Windows: `cmd /c start "" <url>`; macOS: `open`; else `xdg-open`. */
async function defaultOpener(url: string): Promise<boolean> {
  const r =
    process.platform === 'win32'
      ? await run('cmd', ['/c', 'start', '', url], { timeout: TOOL_TIMEOUT_MS })
      : process.platform === 'darwin'
        ? await run('open', [url], { timeout: TOOL_TIMEOUT_MS })
        : await run('xdg-open', [url], { timeout: TOOL_TIMEOUT_MS });
  return r.ok;
}

/**
 * The process start time in ms (UTC), or null when it cannot be read.
 * Windows: PowerShell `Get-Process ... StartTime`. Elsewhere: `ps -o lstart=` (1 s resolution, rounded down).
 */
export async function processStartMs(pid: number): Promise<number | null> {
  if (!Number.isInteger(pid) || pid <= 0) return null;
  const r =
    process.platform === 'win32'
      ? await run(
          'powershell',
          ['-NoProfile', '-NonInteractive', '-Command', `(Get-Process -Id ${pid}).StartTime.ToUniversalTime().ToString('o')`],
          { timeout: TOOL_TIMEOUT_MS },
        )
      : await run('ps', ['-o', 'lstart=', '-p', String(pid)], { timeout: TOOL_TIMEOUT_MS, env: { LC_ALL: 'C' } });
  if (!r.ok) return null;
  // .NET prints 7 fractional digits; keep 3 for Date.parse.
  const text = r.stdout.trim().replace(/(\.\d{3})\d+/, '$1');
  const t = Date.parse(text);
  return Number.isNaN(t) ? null : t;
}

/** The instance id that answers on this port, or null. No key is sent. */
async function whoami(port: number): Promise<string | null> {
  const r = await hubRequest('GET', port, '/api/hub/whoami', null, WHOAMI_TIMEOUT_MS);
  const id = r?.status === 200 ? r.body.instance : undefined;
  return typeof id === 'string' ? id : null;
}

type HubState =
  | { kind: 'none' }
  /** The lock port answers whoami with the lock's instance. Only then may the CLI send the key. */
  | { kind: 'running'; lock: LockInfo }
  /** A young lock of a process that started before the lock: a serve that is not listening yet. */
  | { kind: 'starting'; lock: LockInfo }
  /**
   * A live pid that started no later than the lock, so it is the hub that wrote it, but whoami does not answer
   * (CPU load, Defender, a long file rename). Never stale: taking its lock would leave an orphan hub (I5).
   */
  | { kind: 'unresponsive'; lock: LockInfo }
  /** Dead pid, or a reused pid (it started after the lock was written). */
  | { kind: 'stale'; lock: LockInfo };

/**
 * Is the lock pid the process that wrote the lock? `same`: it started no later than the lock's `started_at`.
 * `other`: it started later (a reused pid). `unknown`: its start time cannot be read (for example the
 * PowerShell call timed out under load). Never treat `unknown` as `other`: that deletes a live hub's lock.
 */
async function sameProcess(lock: LockInfo, deps: HubDeps): Promise<'same' | 'other' | 'unknown'> {
  const home = deps.home ?? caddisHome();
  if (lock.pid === process.pid) return holderAlive(lock, home, () => false) ? 'same' : 'other';
  const started = Date.parse(lock.started_at);
  if (Number.isNaN(started)) return 'other';
  const t = await (deps.processStart ?? processStartMs)(lock.pid);
  if (t === null) return 'unknown';
  return t <= started ? 'same' : 'other';
}

/** Decide what the lock means. The key is never sent here. */
async function inspect(deps: HubDeps, lock: LockInfo | null = readLock(deps.home ?? caddisHome())): Promise<HubState> {
  const home = deps.home ?? caddisHome();
  if (!lock) return { kind: 'none' };
  if (!holderAlive(lock, home, deps.alive ?? pidAlive)) return { kind: 'stale', lock };
  if (lock.instance && lock.port > 0 && (await whoami(lock.port)) === lock.instance) return { kind: 'running', lock };
  // A reused pid always starts after the old process died, so after the lock was written: the start time
  // proves identity, whatever the lock's age.
  if ((await sameProcess(lock, deps)) === 'other') return { kind: 'stale', lock };
  const started = Date.parse(lock.started_at);
  const young = !Number.isNaN(started) && (deps.now ?? Date.now)() - started < START_WAIT_MS;
  return young ? { kind: 'starting', lock } : { kind: 'unresponsive', lock };
}

const alreadyRunning = (l: LockInfo): string => `caddis hub is already running (pid ${l.pid}, port ${l.port})`;
const unresponsive = (l: LockInfo): string =>
  `caddis hub pid ${l.pid} holds the lock but does not answer: run caddis hub stop`;
/** Why `start` or `serve` refuses a lock that is not stale. */
const refusal = (st: Exclude<HubState, { kind: 'none' } | { kind: 'stale' }>): string =>
  st.kind === 'unresponsive' ? unresponsive(st.lock) : alreadyRunning(st.lock);

/**
 * Start the hub in this process: take the lock, ensure the key, start the server, write the real port.
 * A stale lock (dead pid, reused pid, or no whoami answer) is taken over.
 * Throws when a live hub holds the lock, the port rule fails, or the server cannot listen.
 */
export async function startHub(deps: HubDeps = {}): Promise<RunningHub> {
  const home = deps.home ?? caddisHome();
  const now = deps.now ?? Date.now;
  const port = resolvePort(deps);
  const info: LockInfo = {
    pid: process.pid,
    started_at: new Date(now()).toISOString(),
    port,
    instance: randomBytes(16).toString('hex'),
  };
  let got = acquireLock(info, home, deps.alive ?? pidAlive);
  if (!got.ok) {
    const st = await inspect(deps, got.holder);
    if (st.kind === 'running' || st.kind === 'starting' || st.kind === 'unresponsive') throw new HubError(refusal(st));
    removeLockIf(got.holder, home);
    got = acquireLock(info, home, deps.alive ?? pidAlive);
    if (!got.ok) throw new HubError(alreadyRunning(got.holder));
  }
  let server: Awaited<ReturnType<typeof startServer>>;
  const state = deps.state ?? createHub({ home, now });
  let stopping: Promise<void> | null = null;
  let resolveDone!: () => void;
  const done = new Promise<void>((r) => (resolveDone = r));
  const stop = (): Promise<void> => {
    stopping ??= (async () => {
      try {
        state.stop();
        await server.close();
      } finally {
        releaseLock(process.pid, home);
        resolveDone();
      }
    })();
    return stopping;
  };
  try {
    const key = await ensureKey({ home, runCmd: deps.runCmd });
    server = await startServer({
      host: '127.0.0.1',
      port,
      key,
      getState: () => state.getState(),
      versions: deps.versions ?? defaultVersions(),
      now,
      instance: info.instance,
      onStop: () => void stop(),
    });
  } catch (e) {
    releaseLock(process.pid, home);
    if ((e as NodeJS.ErrnoException).code === 'EADDRINUSE') {
      throw new HubError(`port ${port} is in use by another program: free it or set "port" in the hub config.json`);
    }
    throw e;
  }
  writeLock({ ...info, port: server.port }, home);
  state.start();
  return { port: server.port, stop, done };
}

/** Options to test the self-restart. Production uses the defaults. */
export interface ServeDeps extends HubDeps {
  /** Replace the restarter's side effects (timer, file read, probe, exit). */
  restart?: Partial<RestartDeps>;
}

/** Kill the child of a failed restart, but only when it still runs. */
async function killChild(child: { pid?: number }, deps: HubDeps): Promise<void> {
  if (child.pid && (deps.alive ?? pidAlive)(child.pid)) await (deps.kill ?? killTree)(child.pid);
}

/** `caddis hub serve`: foreground server until SIGINT, SIGTERM, `POST /api/hub/stop` or a self-restart. */
export async function hubServe(deps: ServeDeps = {}): Promise<number> {
  const home = deps.home ?? caddisHome();
  let hub: RunningHub;
  try {
    hub = await startHub(deps);
  } catch (e) {
    errorLine(message(e));
    return 1;
  }
  let restarting = false;
  let exitCode = 0;
  let resolveFinished!: () => void;
  const finished = new Promise<void>((r) => (resolveFinished = r));
  const watch = (h: RunningHub): void => {
    void h.done.then(() => {
      if (!restarting) resolveFinished();
    });
  };
  watch(hub);
  const onSignal = (): void => void hub.stop();
  const onExit = (): void => releaseLock(process.pid, home);
  process.once('SIGINT', onSignal);
  process.once('SIGTERM', onSignal);
  process.once('exit', onExit);
  line(`caddis hub serving on ${hubUrl(hub.port)} (pid ${process.pid}); stop it with: caddis hub stop`);

  const pkgRoot = packageInfo().root;
  // The child runs the code next to the package.json that was read, so the version read and the code run match.
  const newEntry = path.join(pkgRoot, 'dist', 'cli.js');
  const runningVersion = (deps.versions ?? defaultVersions()).cli ?? packageInfo().version;
  const restarter = createRestarter({
    currentVersion: runningVersion,
    readVersion: () => readInstalledVersion(pkgRoot),
    closeServer: async () => {
      restarting = true;
      await hub.stop();
    },
    spawnNew: () =>
      (deps.spawn ?? defaultSpawn)(process.execPath, [newEntry, 'hub', 'serve'], { cwd: hubDir(home) }),
    probe: async (child) => {
      const lock = readLock(home);
      const key = readKeyQuiet(home);
      if (!lock || !key || lock.pid !== child.pid || lock.port <= 0 || !lock.instance) return null;
      if ((await whoami(lock.port)) !== lock.instance) return null;
      const h = await hubRequest('GET', lock.port, '/api/health', key, 1_000);
      const v = (h?.body.versions as Record<string, unknown> | undefined)?.cli;
      return h?.status === 200 && typeof v === 'string' ? v : null;
    },
    restartOwn: async () => {
      try {
        hub = await startHub({ ...deps, port: hub.port });
        watch(hub);
      } finally {
        restarting = false;
      }
    },
    killChild: (child) => killChild(child, deps),
    exit: (code) => {
      exitCode = code;
      resolveFinished();
    },
    log: errorLine,
    every: (fn, ms) => {
      const t = setInterval(fn, ms);
      t.unref();
      return () => clearInterval(t);
    },
    ...deps.restart,
  });
  restarter.start();
  await finished;
  restarter.stop();
  process.off('SIGINT', onSignal);
  process.off('SIGTERM', onSignal);
  process.off('exit', onExit);
  return exitCode;
}

/** `caddis hub start`: spawn a hidden `caddis hub serve` and wait for its health check. */
export async function hubStart(deps: HubDeps = {}): Promise<number> {
  const home = deps.home ?? caddisHome();
  const alive = deps.alive ?? pidAlive;
  try {
    resolvePort(deps);
  } catch (e) {
    errorLine(message(e));
    return 1;
  }
  const st = await inspect(deps);
  if (st.kind === 'running' || st.kind === 'starting' || st.kind === 'unresponsive') {
    errorLine(refusal(st));
    return 1;
  }
  if (st.kind === 'stale') removeLockIf(st.lock, home);
  let key: string;
  try {
    key = await ensureKey({ home, runCmd: deps.runCmd });
  } catch (e) {
    errorLine(message(e));
    return 1;
  }
  const entry = deps.entry ?? process.argv[1];
  if (!entry) {
    errorLine('cannot find the caddis CLI entry script to start the hub');
    return 1;
  }
  // The serve lives long. Its cwd is the hub folder, so it never holds a repo or worktree folder open (I6).
  const cwd = hubDir(home);
  mkdirSync(cwd, { recursive: true });
  const child = await (deps.spawn ?? defaultSpawn)(process.execPath, [entry, 'hub', 'serve'], { cwd });
  let exited = false;
  let exitCode: number | null = null;
  void child.exited.then((c) => {
    exited = true;
    exitCode = c;
  });
  const waitMs = deps.startWaitMs ?? START_WAIT_MS;
  const deadline = Date.now() + waitMs;
  while (Date.now() < deadline) {
    if (exited) {
      errorLine(`caddis hub serve exited (code ${exitCode}) before it answered; run "caddis hub serve" to see the error`);
      return 1;
    }
    const lock = readLock(home);
    // Send the key only to the port that answers our child's instance.
    if (lock && lock.pid === child.pid && lock.port > 0 && lock.instance && (await whoami(lock.port)) === lock.instance) {
      const h = await hubRequest('GET', lock.port, '/api/health', key, 1_000);
      if (h?.status === 200) {
        line(`caddis hub running on ${hubUrl(lock.port)}`);
        line('open it with: caddis hub open');
        return 0;
      }
    }
    await sleep(100);
  }
  if (child.pid && alive(child.pid)) await (deps.kill ?? killTree)(child.pid);
  errorLine(
    `caddis hub did not answer within ${Math.round(waitMs / 1000)} s; run "caddis hub serve" to see the error`,
  );
  return 1;
}

/** The running hub's lock and key, or null when it is down. The key goes only to a port that passed whoami. */
async function runningHub(deps: HubDeps): Promise<{ lock: LockInfo; key: string; body: Record<string, unknown> } | null> {
  const home = deps.home ?? caddisHome();
  const st = await inspect(deps);
  if (st.kind !== 'running') return null;
  const key = readKeyQuiet(home);
  if (!key) return null;
  const h = await hubRequest('GET', st.lock.port, '/api/health', key, HEALTH_TIMEOUT_MS);
  return h?.status === 200 ? { lock: st.lock, key, body: h.body } : null;
}

function formatUptime(ms: number): string {
  let s = Math.max(0, Math.floor(ms / 1000));
  const d = Math.floor(s / 86_400);
  s -= d * 86_400;
  const h = Math.floor(s / 3600);
  s -= h * 3600;
  const m = Math.floor(s / 60);
  s -= m * 60;
  const parts: string[] = [];
  if (d) parts.push(`${d}d`);
  if (d || h) parts.push(`${h}h`);
  if (d || h || m) parts.push(`${m}m`);
  parts.push(`${s}s`);
  return parts.join(' ');
}

/** `caddis hub status`: health, port, pid, versions, uptime. Exit 1 when down. */
export async function hubStatus(opts: HubDeps & { json?: boolean } = {}): Promise<number> {
  const now = opts.now ?? Date.now;
  const hub = await runningHub(opts);
  if (!hub) {
    if (opts.json) line(JSON.stringify({ schema: 1, running: false, port: null, pid: null, versions: null }));
    else line('caddis hub is not running; start it with: caddis hub start');
    return 1;
  }
  const versions = (hub.body.versions ?? {}) as Record<string, string>;
  if (opts.json) {
    line(JSON.stringify({ schema: 1, running: true, port: hub.lock.port, pid: hub.lock.pid, versions }));
    return 0;
  }
  const started = Date.parse(hub.lock.started_at);
  line(`caddis hub running on ${hubUrl(hub.lock.port)}`);
  line(`  pid ${hub.lock.pid}, uptime ${Number.isNaN(started) ? 'unknown' : formatUptime(now() - started)}`);
  line(`  versions: ${Object.entries(versions).map(([k, v]) => `${k} ${v}`).join(', ')}`);
  return 0;
}

/**
 * `caddis hub stop`. Exit 0 when stopped or already down.
 * - whoami matches: ask the server to stop (key header), then kill after the wait if needed.
 * - whoami does not match: kill the lock pid only when it started no later than the lock and it is a node
 *   process. Otherwise the pid belongs to another program: remove the stale lock and kill nothing.
 */
export async function hubStop(deps: HubDeps = {}): Promise<number> {
  const home = deps.home ?? caddisHome();
  const alive = deps.alive ?? pidAlive;
  const waitMs = deps.stopWaitMs ?? STOP_WAIT_MS;
  const st = await inspect(deps);
  if (st.kind === 'none') {
    line('caddis hub is not running');
    return 0;
  }
  const lock = st.lock;
  if (st.kind === 'running') {
    const key = readKeyQuiet(home);
    const r = key ? await hubRequest('POST', lock.port, '/api/hub/stop', key, waitMs) : null;
    if (r?.status === 200) {
      const deadline = Date.now() + waitMs;
      while (Date.now() < deadline) {
        const cur = readLock(home);
        if (!cur || cur.instance !== lock.instance || !holderAlive(cur, home, alive)) {
          line('caddis hub stopped');
          return 0;
        }
        await sleep(50);
      }
    }
  }
  if (!holderAlive(lock, home, alive)) {
    removeLockIf(lock, home);
    line('caddis hub is not running (removed a stale lock)');
    return 0;
  }
  // Kill only our own hub: the pid must predate the lock AND run node. The OS may have reused the pid.
  const same = await sameProcess(lock, deps);
  if (same === 'unknown') {
    errorLine(`caddis hub pid ${lock.pid} does not answer and its start time cannot be read; lock kept. Retry, or end that pid by hand`);
    return 1;
  }
  const ours = same === 'same' && (await (deps.isHubPid ?? isNodeProcess)(lock.pid));
  if (!ours) {
    removeLockIf(lock, home);
    line(`caddis hub is not running (removed a stale lock; pid ${lock.pid} is another program, not killed)`);
    return 0;
  }
  await (deps.kill ?? killTree)(lock.pid);
  const deadline = Date.now() + waitMs;
  while (alive(lock.pid) && Date.now() < deadline) await sleep(50);
  if (alive(lock.pid)) {
    errorLine(`could not stop caddis hub (pid ${lock.pid})`);
    return 1;
  }
  removeLockIf(lock, home);
  line(`caddis hub stopped (killed pid ${lock.pid})`);
  return 0;
}

/** `caddis hub open`: get a one-time code and open the login URL. Always print the URL. */
export async function hubOpen(deps: HubDeps = {}): Promise<number> {
  const now = deps.now ?? Date.now;
  const hub = await runningHub(deps);
  if (!hub) {
    errorLine('caddis hub is not running; start it with: caddis hub start');
    return 1;
  }
  const r = await hubRequest('POST', hub.lock.port, '/api/hub/code', hub.key, HEALTH_TIMEOUT_MS);
  const code = r?.status === 200 ? r.body.code : undefined;
  // Check the format here, so the cmd.exe safety of the URL does not depend on the server.
  if (typeof code !== 'string' || !CODE_RE.test(code)) {
    errorLine(`caddis hub did not give a valid login code (HTTP ${r?.status ?? 'no answer'})`);
    return 1;
  }
  const url = `${hubUrl(hub.lock.port)}login?code=${code}`;
  const expires = Date.parse(String(r?.body.expires_at ?? ''));
  const secs = Number.isNaN(expires) ? 60 : Math.round((expires - now()) / 1000);
  line(url);
  line(`the code works once, for ${secs} s`);
  let opened = false;
  try {
    opened = await (deps.opener ?? defaultOpener)(url);
  } catch {
    opened = false;
  }
  if (!opened) line('no browser opened: open this URL in your browser');
  return 0;
}

/** `caddis hub autostart enable | disable | status`. Status exits 1 when autostart is off. */
export async function hubAutostart(action: string, deps: AutostartDeps = {}): Promise<number> {
  try {
    const r =
      action === 'enable'
        ? await enableAutostart(deps)
        : action === 'disable'
          ? await disableAutostart(deps)
          : action === 'status'
            ? await autostartStatus(deps)
            : null;
    if (!r) {
      errorLine(`unknown action "${action}": use enable, disable or status`);
      return 1;
    }
    (r.ok || action === 'status' ? line : errorLine)(r.message);
    return r.ok ? 0 : 1;
  } catch (e) {
    errorLine(message(e));
    return 1;
  }
}
