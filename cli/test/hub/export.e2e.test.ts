import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, lstatSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { exportData } from '../../src/hub/export/data.js';
import { hubExport, MARKER, notFoundPage, NOT_FOUND_SCRIPT } from '../../src/hub/export/export.js';
import { spawnBounded, type SpawnFn, type SpawnResult } from '../../src/hub/spawn.js';
import { CANARY, git, MACHINE, makeDist, makeRepo, put, roadmapText, SHA40, type Fixture } from '../fixtures/export/canary.js';

/**
 * H6.5: `caddis hub export` end to end, with the real bundled collector on a canary git fixture.
 * The repo, the machine and CADDIS_HOME hold planted private values. Every name is a sample.
 * The fixture is built in a temp folder (prefix `caddis-hub-`) and removed after each test.
 */
// Each test starts git and python: a slow machine needs time.
vi.setConfig({ testTimeout: 60_000 });

const probe = spawnSync('python', ['-c', 'print(1)'], { stdio: 'ignore' });
const HAVE_PYTHON = probe.status === 0;

let base: string;
beforeEach(() => {
  base = mkdtempSync(path.join(tmpdir(), 'caddis-hub-export-'));
});
afterEach(() => rmSync(base, { recursive: true, force: true }));

const EXPECTED_FILES = [
  '.caddis-export',
  '404.html',
  'assets/app-1.css',
  'assets/app-1.js',
  'fonts/sample-400.abc.woff2',
  'index.html',
  'licenses/LICENSE-Lucide.txt',
  'licenses/OFL-Atkinson.txt',
  'licenses/OFL-MapleMono.txt',
];

function walk(dir: string, rel = ''): string[] {
  return readdirSync(dir).flatMap((n) => {
    const r = rel ? `${rel}/${n}` : n;
    return lstatSync(path.join(dir, n)).isDirectory() ? walk(path.join(dir, n), r) : [r];
  });
}

interface Run {
  code: number;
  out: string[];
  err: string[];
  calls: { cmd: string; args: string[] }[];
  collectorStdout: string;
}

async function run(fx: Fixture, outDir: string, extra: { github?: string; commit?: string; label?: string; distDir?: string; check?: string } = {}): Promise<Run> {
  const result: Run = { code: -1, out: [], err: [], calls: [], collectorStdout: '' };
  // Only python may start. A call to anything else fails the test.
  const spawn: SpawnFn = async (cmd, args, o): Promise<SpawnResult> => {
    result.calls.push({ cmd, args });
    expect(path.basename(cmd).toLowerCase()).toMatch(/^py(thon3?)?(\.exe)?$/);
    const r = await spawnBounded(cmd, args, { ...o, env: { ...process.env, CADDIS_HOME: fx.home } });
    result.collectorStdout = r.stdout;
    return r;
  };
  result.code = await hubExport(
    { repo: fx.repo, out: outDir, github: 'acme/shop', commit: SHA40, ...extra },
    {
      spawn,
      distDir: extra.distDir ?? makeDist(base),
      now: () => new Date('2026-10-24T10:05:00.000Z'),
      machine: { ...MACHINE, home: path.join(base, 'sample-user-home') },
      stdout: (l) => result.out.push(l),
      stderr: (l) => result.err.push(l),
    },
  );
  return result;
}

const dataBlock = (html: string): { text: string; data: unknown } => {
  const m = /<script type="application\/json" id="caddis-export-data">([\s\S]*?)<\/script>/.exec(html);
  expect(m, 'the data block').not.toBeNull();
  return { text: m![1]!, data: JSON.parse(m![1]!) };
};

describe.skipIf(!HAVE_PYTHON)('caddis hub export (R56, R58, R61)', () => {
  it('exits 0, writes the fixed file set and nothing else', async () => {
    const fx = makeRepo(base);
    const out = path.join(base, 'site');
    const r = await run(fx, out);
    expect(r.err).toEqual([]);
    expect(r.code).toBe(0);
    expect(walk(out).sort()).toEqual(EXPECTED_FILES);
    expect(r.out.join('\n')).toBe(`[EXPORT] 8 file(s) in ${out}`);
    expect(existsSync(`${out}.staging-${process.pid}`)).toBe(false);
  });

  it('holds no canary from the repo, the machine or CADDIS_HOME', async () => {
    const fx = makeRepo(base);
    const out = path.join(base, 'site');
    expect((await run(fx, out)).code).toBe(0);
    const all = walk(out).map((f) => readFileSync(path.join(out, f)).toString('latin1')).join('\n');
    for (const value of [
      ...Object.values(CANARY),
      fx.repo,
      fx.repo.replace(/\\/g, '/'),
      'sample-home-canary',
      'coordinator.json',
      'audit.jsonl',
      'cap_eur',
      'session_id',
      MACHINE.user,
      MACHINE.host,
      SHA40,
    ]) {
      expect(all, value).not.toContain(value);
    }
    // The page does hold the roadmap data it is for.
    expect(all).toContain('Load the catalog');
    expect(all).toContain('"github":"acme/shop"');
  });

  it('starts only python, once, for roadmaps and plans of the one repo', async () => {
    const fx = makeRepo(base);
    const r = await run(fx, path.join(base, 'site'));
    expect(r.calls).toHaveLength(1);
    const args = r.calls[0]!.args;
    expect(args).toContain('--only');
    expect(args[args.indexOf('--only') + 1]).toBe('roadmaps,plans');
    expect(args[args.indexOf('--repos') + 1]).toBe(path.resolve(fx.repo));
    expect(args).toContain('--json');
  });

  it('the embedded JSON round-trips to exportData of the same collector output', async () => {
    const fx = makeRepo(base);
    const out = path.join(base, 'site');
    const r = await run(fx, out);
    const { data } = dataBlock(readFileSync(path.join(out, 'index.html'), 'utf8'));
    const expected = exportData(JSON.parse(r.collectorStdout), { label: null, github: 'acme/shop', commit: SHA40, now: '2026-10-24T10:05:00Z' });
    expect(data).toEqual(JSON.parse(JSON.stringify(expected)));
    expect(JSON.stringify(data)).not.toContain('runner_host');
  });

  it('a phase name that closes the script stays inside the data block', async () => {
    const evil = '</script><script>x</script>';
    const fx = makeRepo(base, { phaseName: evil });
    const out = path.join(base, 'site');
    const r = await run(fx, out);
    expect(r.code).toBe(0);
    const html = readFileSync(path.join(out, 'index.html'), 'utf8');
    expect(html).not.toContain(evil);
    expect(html.match(/<script\b/g)).toHaveLength(1);
    const { text, data } = dataBlock(html);
    expect(text).not.toMatch(/[<>&]/);
    expect(JSON.stringify(data)).toContain(evil);
  });

  it('a Runner host value that also sits in a blocker reason blocks the export and leaves --out unchanged', async () => {
    const fx = makeRepo(base, { blockerReason: `wait for ${CANARY.runnerHost} to free up` });
    const out = path.join(base, 'site');
    put(path.join(out, MARKER), 'x\n');
    put(path.join(out, 'index.html'), 'OLD PAGE\n');
    const r = await run(fx, out);
    expect(r.code).toBe(3);
    expect(r.err.some((l) => /^privacy: index\.html:\d+: derived-private-value$/.test(l))).toBe(true);
    expect(r.err.join('\n')).not.toContain(CANARY.runnerHost);
    expect(readFileSync(path.join(out, 'index.html'), 'utf8')).toBe('OLD PAGE\n');
    expect(walk(out).sort()).toEqual([MARKER, 'index.html']);
    expect(readdirSync(base).filter((n) => n.includes('.staging-'))).toEqual([]);
  });

  it('a blocked export publishes nothing when --out did not exist', async () => {
    const fx = makeRepo(base, { blockerReason: `wait for ${CANARY.runnerHost}` });
    const out = path.join(base, 'site');
    expect((await run(fx, out)).code).toBe(3);
    expect(existsSync(out)).toBe(false);
  });

  it('refuses a non-empty --out without the marker, the repo itself, a folder that holds the repo, and a file', async () => {
    const fx = makeRepo(base);
    const keep = path.join(base, 'precious');
    put(path.join(keep, 'notes.txt'), 'keep me\n');
    let r = await run(fx, keep);
    expect(r.code).toBe(2);
    expect(r.err.join('\n')).toContain(MARKER);
    expect(readFileSync(path.join(keep, 'notes.txt'), 'utf8')).toBe('keep me\n');
    r = await run(fx, fx.repo);
    expect(r.code).toBe(2);
    expect(r.err.join('\n')).toContain('the repo itself');
    r = await run(fx, base);
    expect(r.code).toBe(2);
    expect(r.err.join('\n')).toContain('holds the repo');
    const file = path.join(base, 'a-file');
    writeFileSync(file, 'x');
    r = await run(fx, file);
    expect(r.code).toBe(2);
    expect(r.err.join('\n')).toContain('--out is a file');
    expect(existsSync(path.join(fx.repo, '.caddis'))).toBe(true);
  });

  it('replaces a folder it made before, and an empty folder', async () => {
    const fx = makeRepo(base);
    const out = path.join(base, 'site');
    expect((await run(fx, out)).code).toBe(0);
    put(path.join(out, 'stale.txt'), 'old\n');
    expect((await run(fx, out)).code).toBe(0);
    expect(walk(out).sort()).toEqual(EXPECTED_FILES);
    const empty = path.join(base, 'empty');
    mkdirSync(empty);
    expect((await run(fx, empty)).code).toBe(0);
  });

  it('usage and argument errors', async () => {
    const fx = makeRepo(base);
    const stray = path.join(base, 'not-a-repo');
    mkdirSync(stray);
    const out = path.join(base, 'site');
    expect((await run({ ...fx, repo: stray }, out)).code).toBe(2);
    expect((await run(fx, out, { github: 'no-slash' })).code).toBe(2);
    expect((await run(fx, out, { commit: 'not hex' })).code).toBe(2);
    expect(await hubExport({}, { stderr: () => {}, stdout: () => {} })).toBe(2);
    expect(existsSync(out)).toBe(false);
  });

  it('an unbuilt app is an error (exit 1)', async () => {
    const fx = makeRepo(base);
    const r = await run(fx, path.join(base, 'site'), { distDir: path.join(base, 'no-dist') });
    expect(r.code).toBe(1);
    expect(r.err.join('\n')).toContain('npm run build:ui');
  });

  it('--check on a clean folder exits 0, and on a folder with a private value exits 3', async () => {
    const fx = makeRepo(base);
    const out = path.join(base, 'site');
    expect((await run(fx, out)).code).toBe(0);
    const lines: string[] = [];
    const errs: string[] = [];
    const deps = { machine: MACHINE, stdout: (l: string) => lines.push(l), stderr: (l: string) => errs.push(l) };
    expect(await hubExport({ check: out, github: 'acme/shop' }, deps)).toBe(0);
    expect(lines.join('\n')).toContain('[CHECK] clean');
    writeFileSync(path.join(out, 'assets', 'app-1.js'), `const u = "https://evil.test/x"; // ${MACHINE.host}\n`);
    expect(await hubExport({ check: out, github: 'acme/shop' }, deps)).toBe(3);
    expect(errs.some((l) => l.includes('url-not-allowed'))).toBe(true);
    expect(errs.some((l) => l.includes('derived-private-value'))).toBe(true);
  });

  it('the 404 page maps an old <folder>/<slug>.html link to the hash route, under a hashed inline script', async () => {
    const fx = makeRepo(base);
    const out = path.join(base, 'site');
    expect((await run(fx, out)).code).toBe(0);
    const html = readFileSync(path.join(out, '404.html'), 'utf8');
    expect(html).toBe(notFoundPage());
    const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
    expect(scripts).toHaveLength(1);
    expect(scripts[0]![1]).toBe(NOT_FOUND_SCRIPT);
    const hash = createHash('sha256').update(NOT_FOUND_SCRIPT).digest('base64');
    expect(html).toContain(`script-src 'sha256-${hash}'`);
    expect(html).not.toContain('unsafe-inline');
    const go = (pathname: string): string | null => {
      let target: string | null = null;
      vm.runInNewContext(NOT_FOUND_SCRIPT, { location: { pathname, replace: (u: string) => (target = u) }, encodeURIComponent });
      return target;
    };
    expect(go('/serve-sight/launch-1a2b3c/ui-unification.html')).toBe('/serve-sight/#/roadmap/ui-unification');
    expect(go('/serve-sight/launch-1a2b3c/nope')).toBeNull();
    expect(go('/serve-sight/ui.html')).toBeNull();
    expect(go('/launch-1a2b3c/ui.html')).toBeNull();
    expect(go('/serve-sight/a/b/c.html')).toBe('/serve-sight/a/#/roadmap/c');
  });
});

/**
 * The canary matrix: each forbidden kind is typed into a roadmap blocker (the text that people write), and the export
 * must exit 3 and publish nothing. The kinds are the ones of R62 (a) to (d).
 */
const KINDS: [string, string, string][] = [
  ['runner host (the Runner host: line value)', `wait for ${CANARY.runnerHost}`, 'derived-private-value'],
  ['runner lock host', `wait for ${CANARY.lockHost}`, 'derived-private-value'],
  ['the machine host name', `ssh ${MACHINE.host}`, 'derived-private-value'],
  ['the machine user name', `ask ${MACHINE.user}`, 'derived-private-value'],
  ['the repo absolute path (posix form)', 'see @REPO@/notes', 'derived-private-value'],
  ['session name key', 'set sessionId in the file', 'private-name:sessionId'],
  ['session name key (snake)', 'copy session_id over', 'private-name:session_id'],
  ['waiting_for key', 'read waiting_for first', 'private-name:waiting_for'],
  ['a prompt', 'paste the prompt here', 'private-name:prompt'],
  ['spend', 'cap_eur is 200', 'private-name:cap_eur'],
  ['spend (committed)', 'committed_eur is 12', 'private-name:committed_eur'],
  ['coordinator file', 'edit coordinator.json', 'private-name:coordinator.json'],
  ['relay request file', 'append to requests.jsonl', 'private-name:requests.jsonl'],
  ['audit file', 'read audit.jsonl', 'private-name:audit.jsonl'],
  ['heartbeat', 'heartbeat_at is old', 'private-name:heartbeat_at'],
  ['old pages folder', 'under roadmap-pages', 'private-name:roadmap-pages'],
  ['a Windows path', ['C:', 'Users', 'sample', 'work'].join('/'), 'pattern:windows-drive-path'],
  ['a /home/ path', 'open /home/sample/work', 'pattern:home-path'],
  ['an e-mail address', 'ask sample.person@example.invalid', 'pattern:email-address'],
  ['an IPv4 address', 'ssh 10.20.30.40', 'pattern:ipv4-address'],
  ['a full SHA', `reset to ${SHA40}`, 'pattern:sha-40'],
  ['a URL that is not allowed', 'see https://evil.test/page', 'url-not-allowed'],
  ['a PR URL of another repo', 'see https://github.com/other/repo/pull/1', 'url-not-allowed'],
];

describe.skipIf(!HAVE_PYTHON)('canary matrix: every forbidden kind blocks the export', () => {
  it.each(KINDS)('%s', async (_name, text, rule) => {
    const fx = makeRepo(base);
    const reason = text.replace('@REPO@', fx.repo.replace(/\\/g, '/'));
    // Rewrite the fixture roadmap with the planted text, as a new commit on origin.
    put(path.join(fx.repo, '.caddis', 'roadmaps', 'launch', 'roadmap.md'), roadmapText(reason, 'Load the catalog'));
    git(fx.repo, 'add', '.caddis/roadmaps/launch/roadmap.md');
    git(fx.repo, 'commit', '-q', '-m', 'plant');
    git(fx.repo, 'push', '-q');
    const out = path.join(base, 'site');
    const r = await run(fx, out);
    expect(r.code, r.err.join('\n')).toBe(3);
    expect(r.err.some((l) => l.endsWith(`: ${rule}`)), `${rule} in ${r.err.join(' | ')}`).toBe(true);
    expect(existsSync(out)).toBe(false);
    expect(readdirSync(base).filter((n) => n.includes('.staging-'))).toEqual([]);
  });
});

// The real build: the export of the canary repo into the built app. Skipped when `dist/export` is missing.
const REAL_DIST = fileURLToPath(new URL('../../dist/export', import.meta.url));
describe.skipIf(!HAVE_PYTHON || !existsSync(path.join(REAL_DIST, 'index.html')))('with the real dist/export', () => {
  it('exports and scans clean', async () => {
    const fx = makeRepo(base);
    const out = path.join(base, 'site');
    const r = await run(fx, out, { distDir: REAL_DIST });
    expect(r.err).toEqual([]);
    expect(r.code).toBe(0);
    const files = walk(out);
    expect(files).toContain('index.html');
    expect(files).toContain('404.html');
    expect(files.filter((f) => f.startsWith('licenses/')).sort()).toEqual(['licenses/LICENSE-Lucide.txt', 'licenses/OFL-Atkinson.txt', 'licenses/OFL-MapleMono.txt']);
    expect(files.filter((f) => f.endsWith('.woff2')).length).toBeGreaterThanOrEqual(3);
  });
});
