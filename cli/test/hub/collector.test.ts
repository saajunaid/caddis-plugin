import { mkdtempSync, rmSync, writeFileSync, mkdirSync, cpSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { createCollectorSource } from '../../src/hub/sources/collector.js';
import { findBin } from '../../src/util/which.js';
import { findScriptsDir } from '../scriptsDir.js';

let dir: string;
beforeEach(() => {
  dir = mkdtempSync(path.join(tmpdir(), 'caddis-hub-'));
});
afterEach(() => {
  rmSync(dir, { recursive: true, force: true });
});

const node = process.execPath;
let counter = 0;

/** Write a fake collector (a node script) and return its path. */
function fake(body: string): string {
  counter += 1;
  const file = path.join(dir, `fake-${counter}.js`);
  writeFileSync(file, body);
  return file;
}
const okScript = (schema: number, fp: string, marker = 'a') =>
  `process.stdout.write(JSON.stringify({schema:${schema},generated_at:"2026-10-24T10:00:00Z",` +
  `repos:[{path:"acme/shop",fingerprint:"${fp}",roadmaps:{m:"${marker}"},plans:{},relays:{}}],` +
  `spend:{s:1},guide:{g:1}}))`;

const emptyOut = JSON.stringify({ schema: 1, generated_at: 'z', repos: [], spend: {}, guide: {} });
const fakeRun = (stdout: string) => async () => ({ ok: true, code: 0, stdout, stderr: '', timedOut: false });

describe('collector source', () => {
  it('parses a good run and exposes data', async () => {
    const src = createCollectorSource({
      repos: () => ['acme/shop'],
      python: node,
      scriptPath: fake(okScript(1, 'f1')),
      now: () => Date.parse('2026-10-24T10:00:00Z'),
    });
    await src.refresh();
    const s = src.get();
    expect(s.ok).toBe(true);
    expect(s.stale).toBe(false);
    expect(s.last_error).toBeNull();
    expect(s.last_ok_at).toBe('2026-10-24T10:00:00.000Z');
    expect(s.data?.repos[0]).toMatchObject({ path: 'acme/shop', fingerprint: 'f1' });
    expect(s.data?.spend).toEqual({ s: 1 });
  });

  it('accepts schema N-1 (0)', async () => {
    const src = createCollectorSource({ repos: () => ['acme/shop'], python: node, scriptPath: fake(okScript(0, 'f1')) });
    await src.refresh();
    expect(src.get().ok).toBe(true);
  });

  it('marks update_needed for a newer schema and keeps the last good data', async () => {
    const good = fake(okScript(1, 'f1'));
    const newer = fake(okScript(2, 'f2'));
    let script = good;
    const src = createCollectorSource({
      repos: () => ['acme/shop'],
      python: node,
      get scriptPath() {
        return script;
      },
    });
    await src.refresh();
    script = newer;
    await src.refresh();
    const s = src.get();
    expect(s.update_needed).toBe(true);
    expect(s.ok).toBe(false);
    expect(s.last_error).toMatch(/update/i);
    expect(s.data?.repos[0]?.fingerprint).toBe('f1');
  });

  it('keeps the last good data on bad JSON and records the error', async () => {
    const good = fake(okScript(1, 'f1'));
    const bad = fake('process.stdout.write("not json{")');
    let script = good;
    const src = createCollectorSource({
      repos: () => ['acme/shop'],
      python: node,
      get scriptPath() {
        return script;
      },
    });
    await src.refresh();
    script = bad;
    await src.refresh();
    const s = src.get();
    expect(s.ok).toBe(false);
    expect(s.last_error).toMatch(/json/i);
    expect(s.data?.repos[0]?.fingerprint).toBe('f1');
    expect(s.last_ok_at).not.toBeNull();
  });

  it('records a failed run (non-zero exit)', async () => {
    const src = createCollectorSource({
      repos: () => ['acme/shop'],
      python: node,
      scriptPath: fake('console.error("boom");process.exit(1)'),
    });
    await src.refresh();
    const s = src.get();
    expect(s.ok).toBe(false);
    expect(s.last_error).toContain('boom');
    expect(s.data).toBeNull();
    expect(s.stale).toBe(true);
  });

  it('replaces a repo only when its fingerprint changed', async () => {
    const first = fake(okScript(1, 'f1', 'first'));
    const same = fake(okScript(1, 'f1', 'second'));
    const changed = fake(okScript(1, 'f9', 'third'));
    let script = first;
    const src = createCollectorSource({
      repos: () => ['acme/shop'],
      python: node,
      get scriptPath() {
        return script;
      },
    });
    await src.refresh();
    const before = src.get().data?.repos[0];
    script = same;
    await src.refresh();
    expect(src.get().data?.repos[0]).toBe(before);
    script = changed;
    await src.refresh();
    expect(src.get().data?.repos[0]).toMatchObject({ fingerprint: 'f9', roadmaps: { m: 'third' } });
  });

  it('goes stale after 3 minutes without a good run', async () => {
    let t = Date.parse('2026-10-24T10:00:00Z');
    const src = createCollectorSource({
      repos: () => ['acme/shop'],
      python: node,
      scriptPath: fake(okScript(1, 'f1')),
      now: () => t,
    });
    await src.refresh();
    t += 179_000;
    expect(src.get().stale).toBe(false);
    t += 2_000;
    expect(src.get().stale).toBe(true);
  });

  it('runs one collector at a time', async () => {
    let calls = 0;
    const src = createCollectorSource({
      repos: () => ['acme/shop'],
      python: 'py',
      scriptPath: 'x.py',
      spawn: async () => {
        calls += 1;
        await new Promise((r) => setTimeout(r, 50));
        return { ok: true, code: 0, stdout: emptyOut, stderr: '', timedOut: false };
      },
    });
    await Promise.all([src.refresh(), src.refresh()]);
    expect(calls).toBe(1);
  });

  it('passes the script, then every repo after --repos, then --json', async () => {
    let seen: string[] = [];
    const src = createCollectorSource({
      repos: () => ['a', 'b'],
      python: 'py',
      scriptPath: 'x.py',
      spawn: async (_c, args) => {
        seen = args;
        return { ok: true, code: 0, stdout: emptyOut, stderr: '', timedOut: false };
      },
    });
    await src.refresh();
    expect(seen).toEqual(['x.py', '--repos', 'a', 'b', '--json']);
  });

  it('with no repos it asks only for spend and guide', async () => {
    let seen: string[] = [];
    const src = createCollectorSource({
      repos: () => [],
      python: 'py',
      scriptPath: 'x.py',
      spawn: async (_c, args) => {
        seen = args;
        return fakeRun(emptyOut)();
      },
    });
    await src.refresh();
    expect(seen.slice(0, 2)).toEqual(['x.py', '--repos']);
    expect(seen.slice(3)).toEqual(['--only', 'spend,guide', '--json']);
    expect(src.get().ok).toBe(true);
  });

  it('reports a timeout', async () => {
    const src = createCollectorSource({
      repos: () => ['a'],
      python: 'py',
      scriptPath: 'x.py',
      spawn: async () => ({ ok: false, code: null, stdout: '', stderr: '', timedOut: true }),
    });
    await src.refresh();
    expect(src.get().last_error).toMatch(/timed out/i);
  });

  const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
  const script = path.join(findScriptsDir() ?? path.join(repoRoot, 'scripts'), 'caddis_hub_collect.py');
  const fixture = path.join(repoRoot, 'scripts', 'tests', 'fixtures', 'hub', 'acme-shop');
  it('runs the real collector on a fixture copy (when python exists)', async () => {
    const py = (await findBin('python')) ?? (await findBin('python3'));
    if (!py || !existsSync(script) || !existsSync(fixture)) return;
    const copy = path.join(dir, 'acme-shop');
    mkdirSync(copy);
    cpSync(fixture, copy, { recursive: true });
    const src = createCollectorSource({ repos: () => [copy], python: py, scriptPath: script });
    await src.refresh();
    const s = src.get();
    expect(s.last_error).toBeNull();
    expect(s.data?.repos[0]?.path).toBe(copy);
  }, 60_000);
});
