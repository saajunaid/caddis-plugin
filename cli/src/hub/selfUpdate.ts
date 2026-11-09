/**
 * Self-update of the running hub.
 *
 * 60 s after start, then every 30 min, the hub reads the latest `@caddis/cli` from the npm registry.
 * - The installed package.json differs from the running version (a manual `npm i -g`): restart, no install.
 * - A newer version is published and the hub runs from the global npm install: `npm i -g @caddis/cli@<version>`,
 *   read package.json back, and restart only when it shows that version.
 * - A dev checkout, `npm link` or `npx` never installs. It logs "update available" once per version.
 * - `auto_update: false` in the hub config.json: check and log only.
 * A failed install does not restart. The same version is tried again after an hour at the earliest.
 * The restart itself is the restarter's hand-over (`restart.ts`).
 *
 * Windows file locks: the package and its runtime deps hold no native `.node` files and no install scripts.
 * Node reads each JavaScript file and closes it, and the hub's cwd is the hub folder. So npm can replace the
 * package folder while the hub runs. A lock from another program (an antivirus scan) fails the install: the
 * hub logs it, keeps running and tries again later.
 * Everything with a side effect is injected, so tests never touch npm, the network or the real home.
 */
import path from 'node:path';
import { compareVersions } from '../util/semver.js';

export const REGISTRY_URL = 'https://registry.npmjs.org/@caddis/cli/latest';
export const UPDATE_FIRST_MS = 60_000;
export const UPDATE_EVERY_MS = 30 * 60_000;
export const RETRY_AFTER_MS = 60 * 60_000;
export const INSTALL_TIMEOUT_MS = 5 * 60_000;
const FETCH_TIMEOUT_MS = 10_000;
/** The version goes into an npm command line: plain x.y.z only. */
const PLAIN_VERSION = /^\d+\.\d+\.\d+$/;

/** The latest published version, or null when the answer holds no plain x.y.z. Throws on a network or HTTP error. */
export async function fetchLatestVersion(fetchFn: typeof fetch = fetch): Promise<string | null> {
  const res = await fetchFn(REGISTRY_URL, {
    headers: { accept: 'application/json' },
    signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
  });
  if (!res.ok) throw new Error(`the npm registry answered HTTP ${res.status}`);
  const body = (await res.json()) as { version?: unknown };
  return typeof body.version === 'string' && PLAIN_VERSION.test(body.version) ? body.version : null;
}

/** True when `packageRoot` is `<npm root -g>/@caddis/cli`. Case-insensitive on Windows only. */
export function isGlobalInstall(packageRoot: string, globalRoot: string, platform: NodeJS.Platform = process.platform): boolean {
  // The path rules follow `platform`, not the host, so tests check Windows rules on any OS.
  const p = platform === 'win32' ? path.win32 : path.posix;
  const norm = (dir: string): string => {
    const r = p.resolve(dir).replace(/[\\/]+$/, '');
    return platform === 'win32' ? r.toLowerCase() : r;
  };
  return norm(packageRoot) === norm(p.join(globalRoot, '@caddis', 'cli'));
}

export interface InstallResult {
  ok: boolean;
  /** Why it failed, for the log. */
  detail: string;
}

export interface UpdateDeps {
  /** The version this process runs. */
  currentVersion: string;
  /** The package root of the running entry. */
  packageRoot: string;
  /** `auto_update` from the hub config.json, read on each check. */
  autoUpdate: () => boolean;
  /** The latest published version, or null. May throw. */
  fetchLatest: () => Promise<string | null>;
  /** `npm root -g`, or null when npm does not answer. */
  globalRoot: () => Promise<string | null>;
  /** `npm i -g @caddis/cli@<version>`. */
  install: (version: string) => Promise<InstallResult>;
  /** The installed package.json version, read fresh from disk, or null. */
  readVersion: () => string | null;
  /** Start the hand-over to the version on disk. */
  onInstalled: (version: string) => Promise<void>;
  log: (text: string) => void;
  now: () => number;
  /** Run `fn` once after `ms`. Returns a cancel function. */
  after: (fn: () => void, ms: number) => () => void;
  platform?: NodeJS.Platform;
}

export interface Updater {
  start: () => void;
  stop: () => void;
  /** One check. Never rejects. */
  tick: () => Promise<void>;
  /** True while npm installs. The restarter must not read a half-written package. */
  installing: () => boolean;
  /** Resolves when the running check is done. For tests. */
  idle: () => Promise<void>;
}

export function createUpdater(deps: UpdateDeps): Updater {
  const tried = new Map<string, number>();
  const noted = new Set<string>();
  let globalRoot: string | null = null;
  let installing = false;
  let running: Promise<void> = Promise.resolve();
  let cancel: (() => void) | null = null;
  let stopped = false;

  const once = (key: string, text: string): void => {
    if (noted.has(key)) return;
    noted.add(key);
    deps.log(text);
  };

  async function isGlobal(): Promise<boolean> {
    globalRoot ??= await deps.globalRoot();
    return globalRoot !== null && isGlobalInstall(deps.packageRoot, globalRoot, deps.platform);
  }

  async function check(): Promise<void> {
    const disk = deps.readVersion();
    if (disk !== null && disk !== deps.currentVersion) {
      once(`disk:${disk}`, `caddis hub: version ${disk} is installed (running ${deps.currentVersion}); restarting`);
      await deps.onInstalled(disk);
      return;
    }
    const latest = await deps.fetchLatest();
    if (latest === null || compareVersions(latest, deps.currentVersion) !== 1) return;
    if (!deps.autoUpdate()) {
      once(`off:${latest}`, `caddis hub: version ${latest} is available (running ${deps.currentVersion}); auto_update is off`);
      return;
    }
    if (!(await isGlobal())) {
      once(
        `local:${latest}`,
        `caddis hub: update available ${deps.currentVersion} -> ${latest}; this hub does not run from the global npm install, so it does not install it`,
      );
      return;
    }
    const last = tried.get(latest);
    if (last !== undefined && deps.now() - last < RETRY_AFTER_MS) return;
    tried.set(latest, deps.now());
    deps.log(`caddis hub: installing @caddis/cli@${latest} (running ${deps.currentVersion})`);
    let result: InstallResult;
    installing = true;
    try {
      result = await deps.install(latest);
    } finally {
      installing = false;
    }
    if (!result.ok) {
      deps.log(`caddis hub: install of ${latest} failed (${result.detail}); keeping ${deps.currentVersion}, next try in 1 h`);
      return;
    }
    const after = deps.readVersion();
    if (after !== latest) {
      deps.log(`caddis hub: npm finished, but package.json shows ${after ?? 'nothing'}, not ${latest}; no restart`);
      return;
    }
    deps.log(`caddis hub: installed ${latest}; restarting`);
    await deps.onInstalled(latest);
  }

  function tick(): Promise<void> {
    running = check().catch((e: unknown) => {
      // `tick` runs from a timer: it must never reject.
      try {
        deps.log(`caddis hub: update check failed: ${e instanceof Error ? e.message : String(e)}`);
      } catch {
        /* nothing more to report to */
      }
    });
    return running;
  }

  function schedule(ms: number): void {
    if (stopped) return;
    cancel = deps.after(() => {
      void tick().then(() => schedule(UPDATE_EVERY_MS));
    }, ms);
  }

  return {
    start: () => {
      if (cancel) return;
      stopped = false;
      schedule(UPDATE_FIRST_MS);
    },
    stop: () => {
      stopped = true;
      cancel?.();
      cancel = null;
    },
    tick,
    installing: () => installing,
    idle: () => running,
  };
}
