import { mkdtempSync, rmSync, writeFileSync, readFileSync, existsSync, statSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { keyPath, hubDir } from '../../src/hub/paths.js';
import { ensureKey, icaclsArgs, windowsAccount } from '../../src/hub/keyfile.js';
import { run } from '../../src/util/exec.js';

let home: string;

beforeEach(() => {
  home = mkdtempSync(path.join(tmpdir(), 'caddis-hub-'));
});
afterEach(() => {
  rmSync(home, { recursive: true, force: true });
});

const okRunner = () => {
  const calls: string[][] = [];
  const sizes: number[] = [];
  const fn = async (cmd: string, args: string[]) => {
    calls.push([cmd, ...args]);
    sizes.push(statSync(args[0]!).size);
    return { ok: true, code: 0, stdout: '', stderr: '' };
  };
  return { calls, sizes, fn };
};

describe('hub key file', () => {
  it('creates a 32-byte hex key, reads it back, and keeps it on the next call', async () => {
    const r = okRunner();
    const k1 = await ensureKey({ home, runCmd: r.fn });
    expect(k1).toMatch(/^[0-9a-f]{64}$/);
    expect(readFileSync(keyPath(home), 'utf8').trim()).toBe(k1);
    const k2 = await ensureKey({ home, runCmd: r.fn });
    expect(k2).toBe(k1);
  });

  it('on Windows runs icacls once, on create: inheritance removed, only the user granted', async () => {
    const r = okRunner();
    await ensureKey({ home, runCmd: r.fn, platform: 'win32', account: 'DOM\\owner' });
    await ensureKey({ home, runCmd: r.fn, platform: 'win32', account: 'DOM\\owner' });
    expect(r.calls).toHaveLength(1);
    expect(r.sizes).toEqual([0]); // icacls runs before the key bytes exist
    const [cmd, file, ...rest] = r.calls[0]!;
    expect(cmd).toBe('icacls');
    expect(path.dirname(file!)).toBe(hubDir(home));
    expect(rest).toEqual(['/inheritance:r', '/grant:r', 'DOM\\owner:F']);
    expect(icaclsArgs('f', 'DOM\\owner')).toEqual(['f', '/inheritance:r', '/grant:r', 'DOM\\owner:F']);
  });

  it('sets the ACL on an EMPTY temp file, then writes the key bytes', async () => {
    const order: string[] = [];
    const key = await ensureKey({
      home,
      setAcl: async (file) => {
        order.push(`acl size=${statSync(file).size}`);
      },
    });
    expect(order).toEqual(['acl size=0']);
    expect(readFileSync(keyPath(home), 'utf8').trim()).toBe(key);
  });

  it('the Windows account is DOMAIN\\USER when USERDOMAIN is set, else USER', () => {
    expect(windowsAccount({ USERNAME: 'owner', USERDOMAIN: 'DOM' })).toBe('DOM\\owner');
    expect(windowsAccount({ USERNAME: 'owner' })).toBe('owner');
  });

  it('when icacls fails, no key file is left and ensureKey throws', async () => {
    const fail = async () => ({ ok: false, code: 5, stdout: '', stderr: 'denied' });
    await expect(ensureKey({ home, runCmd: fail, platform: 'win32', account: 'x' })).rejects.toThrow(/icacls/);
    expect(existsSync(keyPath(home))).toBe(false);
  });

  it('refuses a corrupt key file', async () => {
    mkdirSync(hubDir(home), { recursive: true });
    writeFileSync(keyPath(home), 'short');
    await expect(ensureKey({ home, runCmd: okRunner().fn })).rejects.toThrow(/corrupt/);
  });

  it.runIf(process.platform !== 'win32')('POSIX: the key file has mode 0600', async () => {
    await ensureKey({ home });
    expect(statSync(keyPath(home)).mode & 0o777).toBe(0o600);
  });

  it.runIf(process.platform === 'win32')('Windows: the real icacls ACL names only the current user', async () => {
    await ensureKey({ home });
    const out = await run('icacls', [keyPath(home)], { timeout: 15_000 });
    expect(out.ok).toBe(true);
    const user = (process.env.USERNAME ?? '').toLowerCase();
    // icacls prints "<file> <ACE>" then one ACE per line, then a summary line.
    const aces = out.stdout
      .split(/\r?\n/)
      .map((l) => l.replace(keyPath(home), '').trim())
      .filter((l) => l.includes(':('));
    expect(aces.length).toBeGreaterThan(0);
    for (const ace of aces) {
      const who = ace.slice(0, ace.indexOf(':(')).toLowerCase();
      const allowed = who.endsWith(`\\${user}`) || who === user || /system$|administrators$/.test(who);
      expect(allowed, ace).toBe(true);
      expect(ace).not.toMatch(/\(I\)/); // nothing inherited
    }
    expect(aces.some((a) => a.toLowerCase().includes(user))).toBe(true);
  });
});
