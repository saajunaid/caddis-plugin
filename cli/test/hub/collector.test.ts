import { mkdtempSync, rmSync, writeFileSync, mkdirSync, cpSync, existsSync, readFileSync } from 'node:fs';
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
const echoScript = (fp = 'f1', extraRepos = '') =>
  `process.stdout.write(JSON.stringify({schema:1,generated_at:"2026-10-24T10:00:00Z",` +
  `repos:[{path:"acme/shop",fingerprint:"${fp}",roadmaps:{argv:process.argv.slice(2)},plans:{},relays:{}}${extraRepos}],` +
  `spend:{s:1},guide:{g:1}}))`;
const unchangedScript =
  `process.stdout.write(JSON.stringify({schema:1,generated_at:"2026-10-24T10:00:00Z",` +
  `repos:[{path:"acme/shop",fingerprint:"f1",unchanged:true}],` +
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

  it('the first run sends no --known', async () => {
    const src = createCollectorSource({
      repos: () => ['acme/shop'],
      python: node,
      scriptPath: fake(echoScript()),
    });
    await src.refresh();
    const argv = src.get().data?.repos[0]?.roadmaps?.argv as string[];
    expect(argv).not.toContain('--known');
  });

  it('the second run sends --known with the cached fingerprint', async () => {
    const first = fake(echoScript('f1'));
    const second = fake(echoScript('f2'));
    let script = first;
    const src = createCollectorSource({
      repos: () => ['acme/shop'],
      python: node,
      get scriptPath() {
        return script;
      },
    });
    await src.refresh();
    script = second;
    await src.refresh();
    const argv = src.get().data?.repos[0]?.roadmaps?.argv as string[];
    const idx = argv.indexOf('--known');
    expect(idx).toBeGreaterThan(-1);
    expect(argv[idx + 1]).toBe('acme/shop=f1');
    expect(argv[argv.length - 1]).toBe('--json');
  });

  describe('an older script that does not know --known', () => {
    const good = JSON.stringify({ schema: 1, generated_at: 'z', repos: [{ path: 'acme/shop', fingerprint: 'f1' }], spend: {}, guide: {} });
    const unknownKnown = { ok: false, code: 2, stdout: '', stderr: 'caddis_hub_collect.py: error: unrecognized arguments: --known acme/shop=f1', timedOut: false };
    const okRun = { ok: true, code: 0, stdout: good, stderr: '', timedOut: false };

    it('retries once without --known and stops sending it', async () => {
      const calls: string[][] = [];
      const logs: string[] = [];
      const src = createCollectorSource({
        repos: () => ['acme/shop'],
        python: node,
        scriptPath: 'x.py',
        log: (t) => logs.push(t),
        spawn: async (_c, args) => {
          calls.push(args);
          return args.includes('--known') ? unknownKnown : okRun;
        },
      });
      await src.refresh(); // first cycle: no --known
      await src.refresh(); // second cycle: --known, exit 2, retry without it
      await src.refresh(); // third cycle: never sends --known again
      expect(src.get().ok).toBe(true);
      expect(calls.map((a) => a.includes('--known'))).toEqual([false, true, false, false]);
      expect(logs).toHaveLength(1);
    });

    it('does not retry on exit 2 with other stderr', async () => {
      let n = 0;
      const src = createCollectorSource({
        repos: () => ['acme/shop'],
        python: node,
        scriptPath: 'x.py',
        spawn: async () => {
          n += 1;
          return n === 1 ? okRun : { ok: false, code: 2, stdout: '', stderr: 'error: the following arguments are required: --repos', timedOut: false };
        },
      });
      await src.refresh();
      await src.refresh();
      expect(n).toBe(2);
      expect(src.get().ok).toBe(false);
      expect(src.get().last_error).toMatch(/exit 2.*required/);
    });

    it('a normal script keeps getting --known', async () => {
      const calls: string[][] = [];
      const src = createCollectorSource({
        repos: () => ['acme/shop'],
        python: node,
        scriptPath: 'x.py',
        spawn: async (_c, args) => {
          calls.push(args);
          return okRun;
        },
      });
      await src.refresh();
      await src.refresh();
      expect(calls.map((a) => a.includes('--known'))).toEqual([false, true]);
    });
  });

  it('an unchanged entry keeps the cached data', async () => {
    const first = fake(okScript(1, 'f1', 'first'));
    const second = fake(unchangedScript);
    let script = first;
    const src = createCollectorSource({
      repos: () => ['acme/shop'],
      python: node,
      get scriptPath() {
        return script;
      },
    });
    await src.refresh();
    script = second;
    await src.refresh();
    const repo = src.get().data?.repos[0];
    expect(repo).toMatchObject({ fingerprint: 'f1', roadmaps: { m: 'first' } });
    expect(repo && 'unchanged' in repo).toBe(false);
  });

  it('an unchanged entry with no cached data is ignored', async () => {
    const src = createCollectorSource({
      repos: () => ['acme/shop'],
      python: node,
      scriptPath: fake(unchangedScript),
    });
    await src.refresh();
    expect(src.get().data?.repos).toHaveLength(0);
  });

  it('a repo whose cached entry is an error is not in --known', async () => {
    const first = fake(echoScript('f1', ',{path:"acme/bad",fingerprint:"f2",error:"broken"}'));
    const second = fake(echoScript('f3', ',{path:"acme/bad",fingerprint:"f2",error:"broken"}'));
    let script = first;
    const src = createCollectorSource({
      repos: () => ['acme/shop', 'acme/bad'],
      python: node,
      get scriptPath() {
        return script;
      },
    });
    await src.refresh();
    script = second;
    await src.refresh();
    const argv = src.get().data?.repos[0]?.roadmaps?.argv as string[];
    expect(argv).toContain('--known');
    expect(argv).toContain('acme/shop=f1');
    expect(argv.some((a) => a.startsWith('acme/bad='))).toBe(false);
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

describe('PR heads file', () => {
  let prsDir: string;
  beforeEach(() => {
    prsDir = mkdtempSync(path.join(tmpdir(), 'caddis-hub-prs-'));
  });
  afterEach(() => {
    rmSync(prsDir, { recursive: true, force: true });
  });

  const item = { number: 7, head_ref: 'feat/cart', draft: false, fork: false, updated_at: '2026-10-24T09:00:00Z' };

  it('writes the PR file and passes --prs-file before --json', async () => {
    const file = path.join(prsDir, 'sub', 'collector-prs.json');
    let seen: string[] = [];
    const src = createCollectorSource({
      repos: () => ['acme/shop'],
      python: 'py',
      scriptPath: 'x.py',
      prs: () => ({ 'acme/shop': [item] }),
      prsFile: file,
      spawn: async (_c, args) => {
        seen = args;
        return fakeRun(emptyOut)();
      },
    });
    await src.refresh();
    const idx = seen.indexOf('--prs-file');
    expect(idx).toBeGreaterThan(-1);
    expect(seen[idx + 1]).toBe(file);
    expect(idx).toBeLessThan(seen.indexOf('--json'));
    expect(JSON.parse(readFileSync(file, 'utf8'))).toEqual({
      schema: 1,
      repos: { 'acme/shop': [item] },
    });
  });

  it('sends no --prs-file without the prs option', async () => {
    let seen: string[] = [];
    const src = createCollectorSource({
      repos: () => ['acme/shop'],
      python: 'py',
      scriptPath: 'x.py',
      spawn: async (_c, args) => {
        seen = args;
        return fakeRun(emptyOut)();
      },
    });
    await src.refresh();
    expect(seen).not.toContain('--prs-file');
  });

  it('retries once without --prs-file for an old script and stops sending it', async () => {
    const file = path.join(prsDir, 'collector-prs.json');
    const calls: string[][] = [];
    const logs: string[] = [];
    const good = JSON.stringify({ schema: 1, generated_at: 'z', repos: [{ path: 'acme/shop', fingerprint: 'f1' }], spend: {}, guide: {} });
    const src = createCollectorSource({
      repos: () => ['acme/shop'],
      python: 'py',
      scriptPath: 'x.py',
      prs: () => ({ 'acme/shop': [item] }),
      prsFile: file,
      log: (t) => logs.push(t),
      spawn: async (_c, args) => {
        calls.push(args);
        if (args.includes('--prs-file')) {
          return { ok: false, code: 1, stdout: '', stderr: 'caddis-hub-collect: unrecognized arguments: --prs-file x', timedOut: false };
        }
        return { ok: true, code: 0, stdout: good, stderr: '', timedOut: false };
      },
    });
    await src.refresh();
    await src.refresh();
    await src.refresh();
    expect(calls.map((a) => a.includes('--prs-file'))).toEqual([true, false, false, false]);
    expect(src.get().ok).toBe(true);
    expect(logs).toHaveLength(1);
  });
});

describe('done plans cache (plan D2)', () => {
  const doneList = (tree: string) => ({ tree, plans: [{ path: '.caddis/plans/done/x.md', title: 'X', closed_at: 1, phases: 2, pr: 3 }] });
  const out = (repo: Record<string, unknown>) =>
    JSON.stringify({ schema: 1, generated_at: 'z', repos: [{ path: 'acme/shop', ...repo }], spend: {}, guide: {} });
  const run = (stdout: string) => ({ ok: true, code: 0, stdout, stderr: '', timedOut: false });

  /** A source whose spawn answers from `answers` in order and records every argv. */
  function sourceWith(answers: ReturnType<typeof run>[], calls: string[][], logs: string[] = []) {
    let n = 0;
    return createCollectorSource({
      repos: () => ['acme/shop'],
      python: 'py',
      scriptPath: 'x.py',
      log: (t) => logs.push(t),
      spawn: async (_c, args) => {
        calls.push(args);
        return answers[Math.min(n++, answers.length - 1)]!;
      },
    });
  }

  it('sends --done-known for a cached tree, and not on the first run', async () => {
    const calls: string[][] = [];
    const src = sourceWith([run(out({ fingerprint: 'f1', plans: { done: doneList('t1') } }))], calls);
    await src.refresh();
    await src.refresh();
    expect(calls[0]).not.toContain('--done-known');
    const argv = calls[1]!;
    expect(argv[argv.indexOf('--done-known') + 1]).toBe('acme/shop=t1');
    expect(argv[argv.length - 1]).toBe('--json');
  });

  it('sends no --done-known when the cached repo has no done tree', async () => {
    const calls: string[][] = [];
    const src = sourceWith([run(out({ fingerprint: 'f1', plans: { done: { tree: null, plans: [] } } }))], calls);
    await src.refresh();
    await src.refresh();
    expect(calls[1]).toContain('--known');
    expect(calls[1]).not.toContain('--done-known');
  });

  it('a new fingerprint with an unchanged done tree keeps the old list', async () => {
    const calls: string[][] = [];
    const src = sourceWith(
      [
        run(out({ fingerprint: 'f1', plans: { done: doneList('t1') } })),
        run(out({ fingerprint: 'f2', plans: { plans: [], done: { tree: 't1', unchanged: true } } })),
      ],
      calls,
    );
    await src.refresh();
    await src.refresh();
    const repo = src.get().data?.repos[0];
    expect(repo?.fingerprint).toBe('f2');
    expect(repo?.plans?.done).toEqual(doneList('t1'));
  });

  it('unchanged with a different or missing cached tree gives the error slot, which has no tree', async () => {
    const calls: string[][] = [];
    const src = sourceWith(
      [
        run(out({ fingerprint: 'f1', plans: { done: doneList('t1') } })),
        run(out({ fingerprint: 'f2', plans: { done: { tree: 't9', unchanged: true } } })),
        run(out({ fingerprint: 'f3', plans: { done: { tree: 't9', unchanged: true } } })),
      ],
      calls,
    );
    await src.refresh();
    await src.refresh();
    expect(src.get().data?.repos[0]?.plans?.done).toEqual({ error: 'done plans not cached' });
    await src.refresh();
    expect(calls[2]).not.toContain('--done-known');
    // The error slot drops the fingerprint, so the next run sends no --known and takes the fresh entry.
    expect(calls[2]).not.toContain('--known');
    const fresh: string[][] = [];
    const cold = sourceWith([run(out({ fingerprint: 'f1', plans: { done: { tree: 't1', unchanged: true } } }))], fresh);
    await cold.refresh();
    expect(cold.get().data?.repos[0]?.plans?.done).toEqual({ error: 'done plans not cached' });
  });

  it('a hub that restarts has no cache: it sends no --done-known', async () => {
    const calls: string[][] = [];
    const src = sourceWith([run(out({ fingerprint: 'f1', plans: { done: doneList('t1') } }))], calls);
    await src.refresh();
    const restarted: string[][] = [];
    const again = sourceWith([run(out({ fingerprint: 'f1', plans: { done: doneList('t1') } }))], restarted);
    await again.refresh();
    expect(restarted[0]).not.toContain('--done-known');
    expect(again.get().data?.repos[0]?.plans?.done).toEqual(doneList('t1'));
  });

  it('retries once without --done-known for an old script and stops sending it', async () => {
    const calls: string[][] = [];
    const logs: string[] = [];
    const oldScript = { ok: false, code: 2, stdout: '', stderr: 'caddis_hub_collect.py: error: unrecognized arguments: --done-known acme/shop=t1', timedOut: false };
    const good = run(out({ fingerprint: 'f1', plans: { done: doneList('t1') } }));
    let n = 0;
    const src = createCollectorSource({
      repos: () => ['acme/shop'],
      python: 'py',
      scriptPath: 'x.py',
      log: (t) => logs.push(t),
      spawn: async (_c, args) => {
        calls.push(args);
        n += 1;
        return args.includes('--done-known') ? oldScript : good;
      },
    });
    await src.refresh(); // no cache: no flag
    await src.refresh(); // flag sent, exit 2, retry without it
    await src.refresh(); // never sent again
    expect(n).toBe(4);
    expect(calls.map((a) => a.includes('--done-known'))).toEqual([false, true, false, false]);
    expect(calls[2]).toContain('--known');
    expect(src.get().ok).toBe(true);
    expect(logs).toHaveLength(1);
  });
});
