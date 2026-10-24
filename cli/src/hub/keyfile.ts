/**
 * The hub server key `~/.caddis/hub/key` (R19): 32 random bytes, hex.
 *
 * The key never goes into output, a log, the lock file or a URL.
 * Owner-only access:
 * - Windows: `icacls <file> /inheritance:r /grant:r <DOMAIN\USER>:F`. We do not add SYSTEM.
 * - POSIX: mode 0600.
 * We create an EMPTY temp file, set the ACL, write the key, then hard-link it to the final name.
 * So the key bytes never sit under a loose ACL, and two first starts cannot both win.
 */
import { chmodSync, linkSync, mkdirSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs';
import { randomBytes } from 'node:crypto';
import path from 'node:path';
import { keyPath } from './paths.js';
import { run, type RunOptions, type RunResult } from '../util/exec.js';

export type RunCmd = (cmd: string, args: string[], opts?: RunOptions) => Promise<RunResult>;

export interface KeyDeps {
  home?: string;
  platform?: NodeJS.Platform;
  /** Runs icacls. Tests inject a fake. */
  runCmd?: RunCmd;
  /** The Windows account to grant. Default: `windowsAccount(process.env)`. */
  account?: string;
  /** Sets the owner-only ACL on the (empty) temp file. Default: `ownerOnly`. Tests inject it to check the order. */
  setAcl?: (file: string) => Promise<void>;
}

const KEY_RE = /^[0-9a-f]{64}$/;
const ICACLS_TIMEOUT_MS = 15_000;

/** `DOMAIN\USER` when USERDOMAIN is set, else `USER`. The domain stops a same-name local account from matching. */
export function windowsAccount(env: NodeJS.ProcessEnv = process.env): string {
  const user = env.USERNAME ?? '';
  return env.USERDOMAIN ? `${env.USERDOMAIN}\\${user}` : user;
}

/** The exact icacls arguments: remove inherited entries, then grant full control to the user only. */
export function icaclsArgs(file: string, account: string): string[] {
  return [file, '/inheritance:r', '/grant:r', `${account}:F`];
}

function removeQuiet(file: string): void {
  try {
    unlinkSync(file);
  } catch {
    /* already gone */
  }
}

function readKey(file: string, platform: NodeJS.Platform): string | null {
  let text: string;
  try {
    text = readFileSync(file, 'utf8').trim();
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === 'ENOENT') return null;
    throw e;
  }
  if (!KEY_RE.test(text)) throw new Error(`the hub key file is corrupt: delete ${file} and start again`);
  if (platform !== 'win32') chmodSync(file, 0o600); // self-heal the mode on POSIX
  return text;
}

/** Owner-only access: icacls on Windows, mode 0600 elsewhere. Throws when icacls fails. */
async function ownerOnly(file: string, platform: NodeJS.Platform, deps: KeyDeps): Promise<void> {
  if (platform !== 'win32') {
    chmodSync(file, 0o600);
    return;
  }
  const account = deps.account ?? windowsAccount();
  if (!account) throw new Error('icacls: cannot find the current user name (USERNAME is not set)');
  const r = await (deps.runCmd ?? run)('icacls', icaclsArgs(file, account), { timeout: ICACLS_TIMEOUT_MS });
  if (!r.ok) throw new Error(`icacls could not set the owner-only ACL on the hub key file (exit ${r.code})`);
}

/** Return the server key. Create it with the owner-only ACL when it does not exist. */
export async function ensureKey(deps: KeyDeps = {}): Promise<string> {
  const platform = deps.platform ?? process.platform;
  const file = keyPath(deps.home);
  const existing = readKey(file, platform);
  if (existing) return existing;

  mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  const key = randomBytes(32).toString('hex');
  const tmp = `${file}.${process.pid}.${randomBytes(4).toString('hex')}.tmp`;
  try {
    // Order matters: create the file EMPTY, set the owner-only ACL, and only then write the key bytes.
    // A handle that another user opens before the ACL change sees no key.
    writeFileSync(tmp, '', { mode: 0o600, flag: 'wx' });
    await (deps.setAcl ?? ((f: string) => ownerOnly(f, platform, deps)))(tmp);
    writeFileSync(tmp, key, { flag: 'r+' });
    // A hard link, not a rename: it never replaces a key that another start wrote first.
    try {
      linkSync(tmp, file);
    } catch (e) {
      // Another start created the key first. Use that one.
      if ((e as NodeJS.ErrnoException).code !== 'EEXIST') throw e;
    }
  } finally {
    removeQuiet(tmp);
  }
  const back = readKey(file, platform);
  if (!back) throw new Error('the hub key file disappeared after create');
  return back;
}
