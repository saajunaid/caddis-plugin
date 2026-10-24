/**
 * Self-restart on update (H1.8, spec section 9).
 *
 * Each minute the serving process reads the installed package.json from disk. When the version
 * differs from the running one and the file parses, it hands the port to a new server:
 * 1. close its own server and release the lock,
 * 2. start the new server hidden and detached (cwd outside the package),
 * 3. wait up to 20 s until the new server answers with the NEW version,
 * 4. exit.
 * On failure it starts its own server again on the same port and remembers the version as failed.
 * It tries again only when the version changes once more, so there is no restart loop.
 * Everything with a side effect is injected, so tests use fakes.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';

export const RESTART_CHECK_MS = 60_000;
export const RESTART_WAIT_MS = 20_000;
const POLL_MS = 250;

/** The `version` of the installed package.json, read fresh from disk. Null when it is missing or does not parse. */
export function readInstalledVersion(packageRoot: string): string | null {
  try {
    const parsed = JSON.parse(readFileSync(path.join(packageRoot, 'package.json'), 'utf8')) as { version?: unknown };
    return typeof parsed.version === 'string' && parsed.version ? parsed.version : null;
  } catch {
    return null;
  }
}

export interface ChildHandle {
  pid?: number;
  /** Resolves when the child exits. */
  exited: Promise<number | null>;
}

export interface RestartDeps {
  /** The version this process runs. */
  currentVersion: string;
  /** The installed version, or null when package.json is missing or corrupt. */
  readVersion: () => string | null;
  /** Close the server and release the lock. */
  closeServer: () => Promise<void>;
  /** Start the new hidden, detached server. */
  spawnNew: () => Promise<ChildHandle> | ChildHandle;
  /** The version that answers on the hub port, or null when nothing healthy answers. */
  probe: (child: ChildHandle) => Promise<string | null>;
  /** Start this process's server again on the same port and take the lock back. */
  restartOwn: () => Promise<void>;
  /** Kill a child that did not become healthy. */
  killChild?: (child: ChildHandle) => Promise<void>;
  /** Called after a successful hand-over. */
  exit: (code: number) => void;
  log: (text: string) => void;
  /** Schedule `fn` every `ms`. Returns a cancel function. */
  every: (fn: () => void, ms: number) => () => void;
  sleep?: (ms: number) => Promise<void>;
  now?: () => number;
  waitMs?: number;
}

export interface Restarter {
  start: () => void;
  stop: () => void;
  /** One check. Resolves when the check, and any restart it began, is done. */
  tick: () => Promise<void>;
}

export function createRestarter(deps: RestartDeps): Restarter {
  const sleep = deps.sleep ?? ((ms: number) => new Promise<void>((r) => setTimeout(r, ms)));
  const now = deps.now ?? Date.now;
  const waitMs = deps.waitMs ?? RESTART_WAIT_MS;
  const failed = new Set<string>();
  let busy = false;
  let cancel: (() => void) | null = null;

  async function handOver(version: string): Promise<void> {
    deps.log(`caddis hub: version ${deps.currentVersion} -> ${version}; starting the new server`);
    let child: ChildHandle | null = null;
    let error = '';
    try {
      // Inside the try: a close that fails takes the rollback path, never an unhandled rejection.
      await deps.closeServer();
      child = await deps.spawnNew();
      let exited = false;
      void child.exited.then(() => {
        exited = true;
      });
      const deadline = now() + waitMs;
      while (now() < deadline) {
        await Promise.resolve(); // let a child that already exited set the flag
        if (exited) {
          error = 'the new server exited before it answered';
          break;
        }
        if ((await deps.probe(child)) === version) {
          deps.exit(0);
          return;
        }
        await sleep(POLL_MS);
      }
      if (!error) error = `the new server did not answer with version ${version} in ${Math.round(waitMs / 1000)} s`;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
    failed.add(version);
    deps.log(`caddis hub: restart to ${version} failed (${error}); keeping version ${deps.currentVersion}`);
    if (child && deps.killChild) {
      try {
        await deps.killChild(child);
      } catch {
        /* the child may be gone */
      }
    }
    try {
      await deps.restartOwn();
    } catch (e) {
      deps.log(`caddis hub: could not restart the old server: ${e instanceof Error ? e.message : String(e)}`);
      deps.exit(1);
    }
  }

  async function tick(): Promise<void> {
    if (busy) return;
    busy = true;
    try {
      const v = deps.readVersion();
      if (v === null || v === deps.currentVersion || failed.has(v)) return;
      await handOver(v);
    } catch (e) {
      // `tick` runs from a timer as `void tick()`: it must never reject.
      try {
        deps.log(`caddis hub: restart check failed: ${e instanceof Error ? e.message : String(e)}`);
      } catch {
        /* nothing more to report to */
      }
    } finally {
      busy = false;
    }
  }

  return {
    start: () => {
      cancel ??= deps.every(() => void tick(), RESTART_CHECK_MS);
    },
    stop: () => {
      cancel?.();
      cancel = null;
    },
    tick,
  };
}
