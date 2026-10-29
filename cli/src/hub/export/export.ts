/**
 * `caddis hub export`: build the static roadmap page for GitHub Pages (R56, R58, R61).
 *
 * One collector call reads the roadmaps and plans of ONE repo. `exportData` keeps only the allow-listed keys. The
 * page and its data are built in a staging folder beside `--out`. The privacy scan (R62) reads the staging folder.
 * On a hit the command prints the hits, removes the staging folder and exits 3: `--out` is not touched.
 *
 * The command starts no server, reads nothing under `~/.caddis/hub`, and never calls `gh`, `claude`, agy or the network.
 * The only process it starts is the bundled Python collector, through `spawnBounded`.
 *
 * Exit codes: 0 done, 1 error, 2 usage, 3 privacy hit.
 */
import { createHash } from 'node:crypto';
import {
  copyFileSync,
  existsSync,
  lstatSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  rmSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { packageInfo } from '../../util/pkg.js';
import { renameWithRetry } from '../config.js';
import { spawnBounded, type SpawnFn } from '../spawn.js';
import { defaultScriptPath, resolvePython } from '../sources/collector.js';
import { derivedDeny, exportData, GITHUB_RE, type Machine } from './data.js';
import { hitLine, scanExport } from './privacy.js';

export const MARKER = '.caddis-export';
export const PLACEHOLDER = '<!--caddis-export-data-->';
const COLLECT_TIMEOUT_MS = 120_000;

export interface ExportArgs {
  repo?: string;
  out?: string;
  github?: string;
  commit?: string;
  label?: string;
  /** Scan this built folder and nothing else. */
  check?: string;
}

export interface ExportDeps {
  spawn?: SpawnFn;
  python?: string;
  scriptPath?: string;
  /** The built export app: `dist/export` of the package. */
  distDir?: string;
  now?: () => Date;
  machine?: Partial<Machine>;
  allowedUrls?: string;
  stdout?: (line: string) => void;
  stderr?: (line: string) => void;
}

/** The fixed file set of `--out` (R61), plus the 404 page that maps old links. */
export const FIXED_FILES = ['index.html', '404.html'] as const;

const isDir = (p: string): boolean => {
  try {
    return statSync(p).isDirectory();
  } catch {
    return false;
  }
};

/** True when the tree holds a link. A link is never followed or removed by this command. */
function holdsLink(dir: string): boolean {
  for (const name of readdirSync(dir)) {
    const full = path.join(dir, name);
    const st = lstatSync(full);
    if (st.isSymbolicLink()) return true;
    if (st.isDirectory() && holdsLink(full)) return true;
  }
  return false;
}

const samePath = (a: string, b: string): boolean => {
  const norm = (p: string): string => path.resolve(p).replace(/[\\/]+$/, '').toLowerCase();
  return norm(a) === norm(b);
};
const isInside = (child: string, parent: string): boolean => {
  const rel = path.relative(path.resolve(parent), path.resolve(child));
  return rel !== '' && !rel.startsWith('..') && !path.isAbsolute(rel);
};

/** `--out` rules (R61): only an empty folder or one this command made is wiped. Returns an error text, or null. */
export function checkOut(out: string, repo: string): string | null {
  if (samePath(out, repo)) return '--out is the repo itself';
  if (isInside(repo, out)) return '--out holds the repo';
  let st;
  try {
    st = lstatSync(out);
  } catch {
    return null;
  }
  if (st.isSymbolicLink()) return '--out is a link';
  if (!st.isDirectory()) return '--out is a file';
  if (readdirSync(out).length === 0) return null;
  if (!existsSync(path.join(out, MARKER)) || lstatSync(path.join(out, MARKER)).isSymbolicLink()) {
    return `--out is not empty and has no ${MARKER} marker: this command did not make it`;
  }
  if (holdsLink(out)) return '--out holds a link';
  return null;
}

/** R60: `<`, `>`, `&`, U+2028 and U+2029 become \uXXXX, so the text cannot close the script element. */
export function escapeJson(json: string): string {
  return json.replace(/[<>&\u2028\u2029]/g, (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, '0')}`);
}

/**
 * The 404 page (controller ruling, 24 Oct): an old link `<root>/<folder>/<slug>.html` opens `<root>/#/roadmap/<slug>`.
 * Its one inline script is allowed by hash in a meta CSP, so the page needs no 'unsafe-inline'. It redirects only below a
 * repo path (`/<repo>/<folder>/<slug>.html`), so it never leaves the Pages site.
 */
export const NOT_FOUND_SCRIPT =
  "var p=location.pathname.split('/');var f=p.pop();p.pop();var m=/^([A-Za-z0-9._-]+)\\.html$/.exec(f);" +
  "if(m&&p.length>1)location.replace(p.join('/')+'/#/roadmap/'+encodeURIComponent(m[1]));";

export function notFoundPage(): string {
  const hash = createHash('sha256').update(NOT_FOUND_SCRIPT).digest('base64');
  return (
    `<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8" />\n` +
    `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'sha256-${hash}'; base-uri 'none'; form-action 'none'" />\n` +
    `<title>Page moved</title>\n</head>\n<body>\n<p>This link is old. Open the home page of this site to find the roadmap.</p>\n` +
    `<script>${NOT_FOUND_SCRIPT}</script>\n</body>\n</html>\n`
  );
}

/** Copy the fixed set from the built app into `dest`. Anything else in the built folder is left out (R61). */
function copyFixedSet(dist: string, dest: string): void {
  mkdirSync(path.join(dest, 'assets'), { recursive: true });
  mkdirSync(path.join(dest, 'fonts'), { recursive: true });
  mkdirSync(path.join(dest, 'licenses'), { recursive: true });
  copyFileSync(path.join(dist, 'index.html'), path.join(dest, 'index.html'));
  for (const name of readdirSync(path.join(dist, 'assets'))) {
    const from = path.join(dist, 'assets', name);
    if (lstatSync(from).isFile()) copyFileSync(from, path.join(dest, 'assets', name));
  }
  const fonts = path.join(dist, 'fonts');
  if (isDir(fonts)) {
    for (const name of readdirSync(fonts)) {
      const from = path.join(fonts, name);
      if (!lstatSync(from).isFile()) continue;
      if (name.endsWith('.woff2')) copyFileSync(from, path.join(dest, 'fonts', name));
    }
  }
  const licenses = path.join(dist, 'licenses');
  if (isDir(licenses)) {
    for (const name of readdirSync(licenses)) {
      const from = path.join(licenses, name);
      if (lstatSync(from).isFile() && /^(OFL-[A-Za-z]+|LICENSE-Lucide)\.txt$/.test(name)) copyFileSync(from, path.join(dest, 'licenses', name));
    }
  }
}

function countFiles(dir: string): number {
  return readdirSync(dir).reduce((n, name) => {
    const full = path.join(dir, name);
    return n + (lstatSync(full).isDirectory() ? countFiles(full) : name === MARKER ? 0 : 1);
  }, 0);
}

function machineOf(over: Partial<Machine> | undefined, repo: string): Machine {
  let user = '';
  try {
    user = os.userInfo().username;
  } catch {
    /* a service account may have no user entry */
  }
  return { repoPath: repo, home: os.homedir(), user, host: os.hostname(), ...over };
}

export async function hubExport(args: ExportArgs, deps: ExportDeps = {}): Promise<number> {
  const out = deps.stdout ?? ((l: string) => console.log(l));
  const err = deps.stderr ?? ((l: string) => console.error(l));
  const spawn = deps.spawn ?? spawnBounded;
  const now = deps.now ?? (() => new Date());

  if (args.github !== undefined && !GITHUB_RE.test(args.github)) {
    err('error: --github must look like <owner>/<repo>');
    return 2;
  }

  if (args.check !== undefined) {
    const dir = path.resolve(args.check);
    if (!isDir(dir)) {
      err(`error: --check folder not found: ${args.check}`);
      return 1;
    }
    const machine = machineOf(deps.machine, '');
    const deny = derivedDeny({ repos: [] }, machine);
    const hits = scanExport(dir, { deny, github: args.github ?? null, ...(deps.allowedUrls !== undefined ? { allowedUrls: deps.allowedUrls } : {}) });
    for (const h of hits) err(hitLine(h));
    if (hits.length) {
      err(`[BLOCKED] ${hits.length} privacy hit(s)`);
      return 3;
    }
    out(`[CHECK] clean: ${countFiles(dir)} file(s) in ${dir}`);
    return 0;
  }

  if (!args.repo || !args.out) {
    err('usage: caddis hub export --repo <path> --out <dir> [--github <owner>/<repo>] [--commit <sha>] [--label <text>]');
    return 2;
  }
  if (args.commit !== undefined && !/^[0-9a-fA-F]{7,40}$/.test(args.commit)) {
    err('error: --commit must be 7 to 40 hex characters');
    return 2;
  }
  const repo = path.resolve(args.repo);
  const outDir = path.resolve(args.out);
  // R58: a git checkout that holds roadmaps or plans.
  if (!existsSync(path.join(repo, '.git')) || !(isDir(path.join(repo, '.caddis', 'roadmaps')) || isDir(path.join(repo, '.caddis', 'plans')))) {
    err('error: --repo must be a git checkout with .caddis/roadmaps/ or .caddis/plans/');
    return 2;
  }
  const refused = checkOut(outDir, repo);
  if (refused) {
    err(`error: ${refused}`);
    return 2;
  }
  const dist = deps.distDir ?? path.join(packageInfo().root, 'dist', 'export');
  if (!existsSync(path.join(dist, 'index.html')) || !isDir(path.join(dist, 'assets'))) {
    err(`error: the export app is not built (${dist}). Run: npm run build:ui`);
    return 1;
  }

  // R56: one collector call, roadmaps and plans only. The raw output stays in memory.
  let cmd = deps.python;
  let pre: string[] = [];
  if (!cmd) {
    const found = await resolvePython();
    if (!found) {
      err('error: python was not found (tried python, then py -3)');
      return 1;
    }
    cmd = found.cmd;
    pre = found.pre;
  }
  const script = deps.scriptPath ?? defaultScriptPath();
  const run = await spawn(cmd, [...pre, script, '--repos', repo, '--only', 'roadmaps,plans', '--json'], { timeoutMs: COLLECT_TIMEOUT_MS });
  if (run.timedOut || !run.ok) {
    err(`error: the collector ${run.timedOut ? 'timed out' : `failed (exit ${run.code ?? 'none'})`}`);
    return 1;
  }
  let collect: unknown;
  try {
    collect = JSON.parse(run.stdout);
  } catch {
    err('error: the collector output is not valid JSON');
    return 1;
  }

  let data;
  try {
    data = exportData(collect, {
      label: args.label ?? null,
      github: args.github ?? null,
      commit: args.commit ?? null,
      now: now().toISOString().replace(/\.\d{3}Z$/, 'Z'),
    });
  } catch (error) {
    err(`error: ${error instanceof Error ? error.message : String(error)}`);
    return 1;
  }
  const deny = derivedDeny(collect, machineOf(deps.machine, repo));

  // Build in a staging folder beside --out. Only a clean scan replaces --out (R61).
  const staging = `${outDir}.staging-${process.pid}`;
  rmSync(staging, { recursive: true, force: true });
  try {
    copyFixedSet(dist, staging);
    const indexPath = path.join(staging, 'index.html');
    const html = readFileSync(indexPath, 'utf8');
    if (!html.includes(PLACEHOLDER)) throw new Error('the built index.html has no data placeholder');
    const block = `<script type="application/json" id="caddis-export-data">${escapeJson(JSON.stringify(data))}</script>`;
    writeFileSync(indexPath, html.replace(PLACEHOLDER, () => block));
    writeFileSync(path.join(staging, '404.html'), notFoundPage());

    const hits = scanExport(staging, { deny, github: args.github ?? null, ...(deps.allowedUrls !== undefined ? { allowedUrls: deps.allowedUrls } : {}) });
    if (hits.length) {
      for (const h of hits) err(hitLine(h));
      err(`[BLOCKED] ${hits.length} privacy hit(s). Nothing was published.`);
      rmSync(staging, { recursive: true, force: true });
      return 3;
    }

    mkdirSync(path.dirname(outDir), { recursive: true });
    if (existsSync(outDir)) rmSync(outDir, { recursive: true, force: true });
    renameWithRetry(staging, outDir);
    writeFileSync(path.join(outDir, MARKER), 'written by caddis hub export\n');
    out(`[EXPORT] ${countFiles(outDir)} file(s) in ${outDir}`);
    return 0;
  } catch (error) {
    rmSync(staging, { recursive: true, force: true });
    err(`error: ${error instanceof Error ? error.message : String(error)}`);
    return 1;
  }
}
