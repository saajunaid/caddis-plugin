import { mkdirSync, mkdtempSync, rmSync, writeFileSync, readFileSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { spawnBounded } from '../../src/hub/spawn.js';
import { pidAlive } from '../../src/util/sessions.js';

let dir: string;
beforeEach(() => {
  dir = mkdtempSync(path.join(tmpdir(), 'caddis-hub-'));
});
afterEach(() => {
  rmSync(dir, { recursive: true, force: true });
});

const node = process.execPath;

async function waitFor(fn: () => boolean, ms = 5000): Promise<boolean> {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    if (fn()) return true;
    await new Promise((r) => setTimeout(r, 50));
  }
  return fn();
}

describe('spawnBounded', () => {
  it('captures stdout and the exit code', async () => {
    const r = await spawnBounded(node, ['-e', 'process.stdout.write("hi")'], { timeoutMs: 10_000 });
    expect(r).toMatchObject({ ok: true, code: 0, stdout: 'hi', timedOut: false });
  });

  it('reports a non-zero exit and stderr', async () => {
    const r = await spawnBounded(node, ['-e', 'console.error("bad");process.exit(3)'], { timeoutMs: 10_000 });
    expect(r.ok).toBe(false);
    expect(r.code).toBe(3);
    expect(r.stderr).toContain('bad');
  });

  it('never throws when the binary is missing', async () => {
    const r = await spawnBounded('caddis-no-such-binary-xyz', [], { timeoutMs: 5000 });
    expect(r.ok).toBe(false);
    expect(r.timedOut).toBe(false);
  });

  it('kills the process and its child on timeout', async () => {
    const pidFile = path.join(dir, 'child.pid');
    const script = path.join(dir, 'parent.js');
    writeFileSync(
      script,
      [
        "const cp = require('node:child_process');",
        "const fs = require('node:fs');",
        "const c = cp.spawn(process.execPath, ['-e', 'setInterval(()=>{},1000)'], { stdio: 'ignore' });",
        'fs.writeFileSync(process.argv[2], String(c.pid));',
        'setInterval(()=>{},1000);',
      ].join('\n'),
    );
    const r = await spawnBounded(node, [script, pidFile], { timeoutMs: 1500 });
    expect(r.timedOut).toBe(true);
    expect(r.ok).toBe(false);
    expect(existsSync(pidFile)).toBe(true);
    const childPid = Number(readFileSync(pidFile, 'utf8'));
    expect(childPid).toBeGreaterThan(0);
    expect(await waitFor(() => !pidAlive(childPid))).toBe(true);
  }, 20_000);

  it('caps captured stdout', async () => {
    const r = await spawnBounded(node, ['-e', 'process.stdout.write("x".repeat(200000))'], {
      timeoutMs: 10_000,
      maxBytes: 1000,
    });
    expect(r.stdout.length).toBeLessThanOrEqual(1000);
  });
});

describe.skipIf(process.platform !== 'win32')('spawnBounded .cmd shims (win32)', () => {
  it('runs a .cmd shim that prints JSON, from a path with a space', async () => {
    const sub = path.join(dir, 'with space');
    mkdirSync(sub);
    const shim = path.join(sub, 'tool.cmd');
    writeFileSync(shim, '@echo off\r\necho [{"id":"%1"}]\r\n');
    const r = await spawnBounded(shim, ['demo-1'], { timeoutMs: 10_000 });
    expect(r.ok).toBe(true);
    expect(JSON.parse(r.stdout)).toEqual([{ id: 'demo-1' }]);
  });

  it('refuses an argument with a space or an ampersand, without spawning', async () => {
    const marker = path.join(dir, 'ran.txt');
    const shim = path.join(dir, 'tool.bat');
    writeFileSync(shim, `@echo off\r\necho x> "${marker}"\r\n`);
    for (const bad of ['a b', 'a&b', 'a"b', '%PATH%']) {
      const r = await spawnBounded(shim, [bad], { timeoutMs: 10_000 });
      expect(r.ok).toBe(false);
      expect(r.stderr).toContain('refused argument');
    }
    expect(existsSync(marker)).toBe(false);
  });

  it('refuses a command path with an unsafe character', async () => {
    const r = await spawnBounded(path.join(dir, 'a&b.cmd'), [], { timeoutMs: 10_000 });
    expect(r.ok).toBe(false);
    expect(r.stderr).toContain('unsafe character');
  });

  it('refuses a path with %, ! (cmd expansion), CR or LF, without spawning', async () => {
    const marker = path.join(dir, 'ran.txt');
    for (const name of ['100%PATH%.cmd', 'wow!x!.cmd']) {
      const shim = path.join(dir, name);
      writeFileSync(shim, `@echo off\r\necho x> "${marker}"\r\n`);
      const r = await spawnBounded(shim, [], { timeoutMs: 10_000 });
      expect(r.ok, name).toBe(false);
      expect(r.stderr).toContain('unsafe character');
    }
    for (const name of ['a\rb.cmd', 'a\nb.cmd']) {
      const r = await spawnBounded(path.join(dir, name), [], { timeoutMs: 10_000 });
      expect(r.stderr).toContain('unsafe character');
    }
    expect(existsSync(marker)).toBe(false);
  });

  it('kills the tree when a .cmd shim times out', async () => {
    const pidFile = path.join(dir, 'pid.txt');
    const js = path.join(dir, 'sleep.js');
    writeFileSync(js, `require('fs').writeFileSync(process.argv[2], String(process.pid)); setInterval(()=>{},1000);`);
    const shim = path.join(dir, 'sleepy.cmd');
    writeFileSync(shim, `@echo off\r\n"${node}" "${js}" "${pidFile}"\r\n`);
    const r = await spawnBounded(shim, [], { timeoutMs: 1500 });
    expect(r.timedOut).toBe(true);
    expect(await waitFor(() => existsSync(pidFile))).toBe(true);
    const pid = Number(readFileSync(pidFile, 'utf8'));
    expect(await waitFor(() => !pidAlive(pid))).toBe(true);
  });
});
