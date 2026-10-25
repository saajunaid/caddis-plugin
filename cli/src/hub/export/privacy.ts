/**
 * The privacy scan of the Pages export (R62).
 *
 * The allow-list in data.ts stops the keys we know. This scan reads the built files and fails closed on anything
 * private that people typed into a roadmap or plan, or that a parser added. It reports file, offset and rule.
 * It never prints the matched text: the text may be the private value.
 */
import { lstatSync, readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';

export interface Hit {
  file: string;
  offset: number;
  rule: string;
}

export interface ScanOptions {
  /** Private values from `derivedDeny` (R62 a). */
  deny: string[];
  /** `<owner>/<repo>` of the `--github` value, or null. Only its PR URLs pass. */
  github: string | null;
  /** The allow-list file text. Defaults to the file next to this module. */
  allowedUrls?: string;
}

/** Key names and file names of private state (R62 b). Checked in `index.html`, so also in the data block. */
export const PRIVATE_NAMES = [
  'sessionId',
  'session_id',
  'waitingFor',
  'waiting_for',
  'prompt',
  'cap_eur',
  'committed_eur',
  'coordinator.json',
  'requests.jsonl',
  'audit.jsonl',
  'coordinator_session',
  'heartbeat_at',
  'roadmap-pages',
  'X-Caddis-Hub',
];

/** Patterns (R62 c). Checked in `index.html`. The drive rule needs a non-letter before it, so `https:/` does not match. */
export const PATTERNS: { name: string; re: RegExp }[] = [
  { name: 'windows-drive-path', re: /(?<![A-Za-z0-9])[A-Za-z]:[\\/]/g },
  { name: 'unc-path', re: /\\\\/g },
  { name: 'home-path', re: /\/home\//g },
  { name: 'users-path', re: /\/Users\//g },
  { name: 'root-path', re: /\/root\//g },
  { name: 'runner-path', re: /\/runner\//g },
  { name: 'email-address', re: /[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}/g },
  { name: 'ipv4-address', re: /(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])/g },
  { name: 'sha-40', re: /(?<![0-9A-Fa-f])[0-9A-Fa-f]{40}(?![0-9A-Fa-f])/g },
];

const URL_RE = /(?:https?|wss?|ftp):\/\/[^\s"'`<>)\\]+/g;
const BINARY_EXT = new Set(['.woff2', '.woff', '.ttf', '.otf', '.png', '.ico', '.jpg', '.gif', '.webp']);

/** The allow-list file: one exact URL per line, `#` starts a comment, `template: <prefix>` is a JS template prefix. */
export function parseAllowedUrls(text: string): { exact: Set<string>; templates: string[] } {
  const exact = new Set<string>();
  const templates: string[] = [];
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith('#')) continue;
    if (line.startsWith('template:')) templates.push(line.slice('template:'.length).trim());
    else exact.add(line);
  }
  return { exact, templates };
}

export function defaultAllowedUrls(): string {
  return readFileSync(new URL('./allowed-urls.txt', import.meta.url), 'utf8');
}

const escapeRe = (s: string): string => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

function walk(dir: string, base = ''): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir).sort()) {
    const rel = base ? `${base}/${name}` : name;
    const full = path.join(dir, name);
    if (lstatSync(full).isDirectory()) out.push(...walk(full, rel));
    else out.push(rel);
  }
  return out;
}

/** A plain short word can be UI text ("dev", "build"). It is not scanned in the shared build output. */
const isSoft = (v: string): boolean => /^[A-Za-z][A-Za-z0-9_-]{2,6}$/.test(v);
const isNumeric = (v: string): boolean => /^\d+$/.test(v);

/** `\uXXXX` escapes (R60) decoded, so an escaped character cannot hide a value from a text rule. */
const decodeEscapes = (s: string): string => s.replace(/\\u([0-9a-fA-F]{4})/g, (_m, h: string) => String.fromCharCode(parseInt(h, 16)));

function scanDeny(file: string, buf: Buffer, text: string | null, deny: string[], hits: Hit[]): void {
  const inAssets = file.startsWith('assets/');
  for (const value of deny) {
    if (text === null) {
      // Binary: exact bytes only. A short or all-digit value would match noise.
      if (value.length < 6 || isNumeric(value)) continue;
      let at = buf.indexOf(value);
      while (at !== -1) {
        hits.push({ file, offset: at, rule: 'derived-private-value' });
        at = buf.indexOf(value, at + value.length);
      }
      continue;
    }
    if (inAssets && isSoft(value)) continue;
    const re = isNumeric(value)
      ? new RegExp(`(?<![0-9])${escapeRe(value)}(?![0-9])`, 'gi')
      : new RegExp(escapeRe(value), 'gi');
    for (const m of text.matchAll(re)) hits.push({ file, offset: m.index ?? 0, rule: 'derived-private-value' });
  }
}

function scanUrls(file: string, text: string, opts: ScanOptions, hits: Hit[]): void {
  const allowed = parseAllowedUrls(opts.allowedUrls ?? defaultAllowedUrls());
  const pull = opts.github ? new RegExp(`^https://github\\.com/${escapeRe(opts.github)}/pull/\\d+$`) : null;
  for (const m of text.matchAll(URL_RE)) {
    const url = m[0].replace(/[.,;:]+$/, '');
    if (allowed.exact.has(url) || pull?.test(url)) continue;
    // The bundle builds PR links from a template. The value is `github` and a number, both checked elsewhere.
    if (file.endsWith('.js') && allowed.templates.some((t) => url.startsWith(`${t}\${`))) continue;
    hits.push({ file, offset: m.index ?? 0, rule: 'url-not-allowed' });
  }
}

export function scanExport(dir: string, opts: ScanOptions): Hit[] {
  const hits: Hit[] = [];
  for (const file of walk(dir)) {
    const full = path.join(dir, ...file.split('/'));
    if (lstatSync(full).isSymbolicLink()) {
      hits.push({ file, offset: 0, rule: 'symbolic-link' });
      continue;
    }
    const buf = readFileSync(full);
    const binary = BINARY_EXT.has(path.extname(file).toLowerCase());
    const text = binary ? null : buf.toString('utf8');
    scanDeny(file, buf, text, opts.deny, hits);
    if (text === null) continue;
    scanUrls(file, text, opts, hits);
    if (file !== 'index.html') continue;
    const decoded = decodeEscapes(text);
    for (const variant of decoded === text ? [text] : [text, decoded]) {
      for (const name of PRIVATE_NAMES) {
        let at = variant.indexOf(name);
        while (at !== -1) {
          hits.push({ file, offset: at, rule: `private-name:${name}` });
          at = variant.indexOf(name, at + name.length);
        }
      }
      for (const { name, re } of PATTERNS) {
        for (const m of variant.matchAll(re)) hits.push({ file, offset: m.index ?? 0, rule: `pattern:${name}` });
      }
    }
  }
  return hits;
}

export const hitLine = (h: Hit): string => `privacy: ${h.file}:${h.offset}: ${h.rule}`;
