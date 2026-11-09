/**
 * `caddis email setup` and `caddis email check` — the one-time setup for the send-email skill.
 *
 * The skill reads `~/.caddis/email.toml` (settings) and an env file (secrets). Before this command a new
 * machine meant copying the example, editing it, and writing the env file by hand. Now it is one command and a
 * few answers.
 *
 * Rules this command holds to:
 *  * A secret is NEVER printed, logged or echoed. Prompts for secrets are masked.
 *  * A secret NEVER goes into `email.toml`. It goes into `email.env` (mode 0600) or stays in the env file the
 *    owner already has.
 *  * A secret never comes from a flag, so it never lands in shell history. Non-interactive runs read it from
 *    `CADDIS_EMAIL_CLIENT_SECRET` / `CADDIS_EMAIL_SMTP_PASSWORD` or from the env file.
 *  * An existing `email.toml` or `email.env` is never replaced without a yes (default no) or `--force`.
 */
import { chmodSync, existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { cancel, confirm, intro, isCancel, outro, password, select, text } from '@clack/prompts';
import { run as defaultRun, type RunResult } from '../util/exec.js';
import { color, errorLine } from '../util/log.js';
import { packageInfo } from '../util/pkg.js';
import { compareVersions } from '../util/semver.js';
import { caddisHome } from '../util/sessions.js';

export type Provider = 'graph' | 'smtp';
export type Security = 'starttls' | 'ssl' | 'none';

/** The key names in the env file. They are the defaults of `email.toml.example`. */
export const GRAPH_TENANT_KEY = 'ALERT_GRAPH_TENANT_ID';
export const GRAPH_CLIENT_KEY = 'ALERT_GRAPH_CLIENT_ID';
export const GRAPH_SECRET_KEY = 'ALERT_GRAPH_CLIENT_SECRET'; // caddis: not-secret
export const SMTP_PASSWORD_KEY = 'EMAIL_SMTP_PASSWORD'; // caddis: not-secret

/** Where a non-interactive run reads the secret. Never a flag. */
export const SECRET_ENV_GRAPH = 'CADDIS_EMAIL_CLIENT_SECRET'; // caddis: not-secret
export const SECRET_ENV_SMTP = 'CADDIS_EMAIL_SMTP_PASSWORD'; // caddis: not-secret

const SECURITIES: Security[] = ['starttls', 'ssl', 'none'];
const SMTP_PORTS: Record<Security, number> = { starttls: 587, ssl: 465, none: 25 };

export interface SmtpSettings {
  host: string;
  security: Security;
  port: number;
  username: string;
}

export interface TomlAnswers {
  provider: Provider;
  sender: string;
  /** Path to the env file. Left out of the toml when empty. */
  envFile?: string;
  smtp?: SmtpSettings;
}

// ── pure parts ──────────────────────────────────────────────────────────────────────────────────────────────

export function defaultPort(security: Security): number {
  return SMTP_PORTS[security];
}

export function isGuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
}

function isMailbox(value: string): boolean {
  return /^[^\s@"'\\]+@[^\s@"'\\]+\.[^\s@"'\\]+$/.test(value);
}

/**
 * A TOML literal string (single quotes, no escapes), so a Windows path needs no doubling of backslashes.
 * A literal string cannot hold a single quote or a line break.
 */
export function tomlLiteral(value: string): string {
  if (value.includes("'")) throw new Error('the path contains a single quote; move the file to a path without one');
  if (/[\r\n]/.test(value)) throw new Error('the path contains a line break');
  return `'${value}'`;
}

/** A TOML basic string. JSON string escapes are a valid subset of TOML basic string escapes. */
function tomlString(value: string): string {
  return JSON.stringify(value);
}

/** The text of `email.toml`. It holds settings and key NAMES only, never a secret. */
export function buildToml(a: TomlAnswers): string {
  const lines = [
    '# Written by `caddis email setup`. Secrets are never stored in this file.',
    '# Every key is described in email.toml.example in the send-email skill folder.',
    `provider = ${tomlString(a.provider)}`,
    `sender = ${tomlString(a.sender)}`,
  ];
  if (a.envFile) lines.push(`env_file = ${tomlLiteral(a.envFile)}`);
  lines.push('');
  if (a.provider === 'graph') {
    lines.push(
      '[graph]',
      `tenant_id_key = ${tomlString(GRAPH_TENANT_KEY)}`,
      `client_id_key = ${tomlString(GRAPH_CLIENT_KEY)}`,
      `client_secret_key = ${tomlString(GRAPH_SECRET_KEY)}`,
    );
  } else {
    const s = a.smtp;
    if (!s) throw new Error('smtp settings are required for provider smtp');
    lines.push(
      '[smtp]',
      `host = ${tomlString(s.host)}`,
      `security = ${tomlString(s.security)}`,
      `port = ${s.port}`,
      `username = ${tomlString(s.username)}`,
      `password_key = ${tomlString(SMTP_PASSWORD_KEY)}`,
      'timeout = 30',
    );
  }
  lines.push('');
  return lines.join('\n');
}

/** The text of `email.env`: KEY=value lines, the format the skill reads. */
export function buildEnvText(values: Record<string, string>): string {
  const lines = ['# Written by `caddis email setup`. Keep this file private.'];
  for (const [key, value] of Object.entries(values)) lines.push(`${key}=${value}`);
  return `${lines.join('\n')}\n`;
}

/**
 * The names (never values) of keys that are absent or empty in env file text. The parse rules are those of
 * `read_env` in send_email.py: skip blank and `#` lines, split at the first `=`, strip surrounding quotes.
 */
export function envFileMissingKeys(envText: string, required: string[]): string[] {
  const present = new Set<string>();
  for (const raw of envText.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith('#') || !line.includes('=')) continue;
    const at = line.indexOf('=');
    const value = line
      .slice(at + 1)
      .trim()
      .replace(/^"+|"+$/g, '')
      .replace(/^'+|'+$/g, '');
    if (value) present.add(line.slice(0, at).trim());
  }
  return required.filter((key) => !present.has(key));
}

/**
 * A secret is written as `KEY=value` and read back by a parser that trims it and strips quotes. Refuse a value that
 * would not survive the round trip, instead of writing one that fails later.
 */
function secretProblem(label: string, value: string): string | undefined {
  if (!value) return `${label} is empty`;
  if (/[\r\n]/.test(value)) return `${label} must be one line`;
  if (value !== value.trim()) return `${label} has leading or trailing spaces`;
  if (/^["']|["']$/.test(value)) return `${label} cannot start or end with a quote (the reader strips quotes)`;
  return undefined;
}

const NON_SECRET_LINE = /^\s*(provider|sender|env_file|host|security|port|username|password_key|tenant_id_key|client_id_key|client_secret_key|timeout)\s*=/;

/** The lines of an existing `email.toml` that are safe to show: a whitelist of setting names, never a value of any other key. */
export function summariseExisting(tomlText: string): string[] {
  return tomlText
    .split(/\r?\n/)
    .filter((line) => NON_SECRET_LINE.test(line))
    .map((line) => line.trim());
}

// ── paths ───────────────────────────────────────────────────────────────────────────────────────────────────

export function emailPaths(home: string): { dir: string; toml: string; env: string } {
  const dir = path.join(home, '.caddis');
  return { dir, toml: path.join(dir, 'email.toml'), env: path.join(dir, 'email.env') };
}

const SCRIPT_REL = ['skills', 'send-email', 'scripts', 'send_email.py'];
/** Older caddis-extras installs ship the skill under its first name. */
const LEGACY_SCRIPT_REL = ['skills', 'graph-email', 'scripts', 'send_email.py'];

export interface FindScriptOptions {
  home: string;
  packageRoot?: string;
}

function versionsDesc(dir: string): string[] {
  let names: string[];
  try {
    names = readdirSync(dir);
  } catch {
    return [];
  }
  return names.sort((a, b) => (compareVersions(b, a) ?? 0) || b.localeCompare(a));
}

/**
 * Find `send_email.py`. The installed Claude Code plugin copy is preferred, because it is the one `/caddis:graph-email`
 * runs: the core plugin first (the skill ships there), then caddis-extras (older installs). Then the copy in the npm package bundles, then a source checkout.
 */
export function findEmailScript({ home, packageRoot = packageInfo().root }: FindScriptOptions): string | null {
  const core: string[] = [];
  const extras: string[] = [];
  const pluginsDir = path.join(home, '.claude', 'plugins');

  try {
    const parsed = JSON.parse(readFileSync(path.join(pluginsDir, 'installed_plugins.json'), 'utf8')) as {
      plugins?: Record<string, unknown>;
    };
    for (const [key, entries] of Object.entries(parsed.plugins ?? {})) {
      if (!(key.startsWith('caddis@') || key.startsWith('caddis-extras@')) || !Array.isArray(entries)) continue;
      for (const entry of entries) {
        const installPath = (entry as { installPath?: unknown })?.installPath;
        if (typeof installPath !== 'string' || !installPath) continue;
        // The core plugin first: the skill ships there. Extras is the fallback for an older install.
        if (key.startsWith('caddis@')) core.push(path.join(installPath, ...SCRIPT_REL));
        else extras.push(path.join(installPath, ...LEGACY_SCRIPT_REL));
      }
    }
  } catch {
    /* no plugin list: fall through to the cache scan */
  }

  for (const [plugin, into] of [['caddis', core], ['caddis-extras', extras]] as const) {
    const base = path.join(pluginsDir, 'cache', 'caddis', plugin);
    const rel = plugin === 'caddis' ? SCRIPT_REL : LEGACY_SCRIPT_REL;
    for (const version of versionsDesc(base)) into.push(path.join(base, version, ...rel));
  }

  const candidates = [...core, ...extras];
  candidates.push(path.join(packageRoot, 'bundles', 'antigravity-plugin', ...SCRIPT_REL));
  candidates.push(path.join(packageRoot, '..', '.github', 'skills', 'devops', 'send-email', 'scripts', 'send_email.py'));

  for (const file of candidates) {
    try {
      if (statSync(file).isFile()) return file;
    } catch {
      /* try the next one */
    }
  }
  return null;
}

// ── prompts ─────────────────────────────────────────────────────────────────────────────────────────────────

/** A null answer means the owner cancelled. */
export interface Prompter {
  select<T extends string>(o: {
    message: string;
    options: Array<{ value: T; label: string; hint?: string }>;
    initialValue?: T;
  }): Promise<T | null>;
  text(o: {
    message: string;
    placeholder?: string;
    initialValue?: string;
    validate?: (value: string) => string | undefined;
  }): Promise<string | null>;
  password(o: { message: string; validate?: (value: string) => string | undefined }): Promise<string | null>;
  confirm(o: { message: string; initialValue?: boolean }): Promise<boolean | null>;
}

const clackPrompts: Prompter = {
  async select(o) {
    const answer = await select({ message: o.message, options: o.options as never, initialValue: o.initialValue as never });
    return isCancel(answer) ? null : (answer as never);
  },
  async text(o) {
    const answer = await text({
      message: o.message,
      placeholder: o.placeholder,
      initialValue: o.initialValue,
      validate: o.validate ? (value) => o.validate!(String(value ?? '')) : undefined,
    });
    return isCancel(answer) ? null : String(answer ?? '');
  },
  async password(o) {
    const answer = await password({
      message: o.message,
      validate: o.validate ? (value) => o.validate!(String(value ?? '')) : undefined,
    });
    return isCancel(answer) ? null : String(answer ?? '');
  },
  async confirm(o) {
    const answer = await confirm({ message: o.message, initialValue: o.initialValue });
    return isCancel(answer) ? null : Boolean(answer);
  },
};

// ── check ───────────────────────────────────────────────────────────────────────────────────────────────────

type Runner = (cmd: string, args: string[], opts?: { env?: Record<string, string>; timeout?: number }) => Promise<RunResult>;

export interface CheckOptions {
  home?: string;
  env?: Record<string, string | undefined>;
  run?: Runner;
  packageRoot?: string;
  /** The config file to check. Default: `CADDIS_EMAIL_CONFIG`, else `~/.caddis/email.toml`. */
  configPath?: string;
}

const PYTHON_CANDIDATES: Array<{ cmd: string; pre: string[] }> = [
  { cmd: 'python', pre: [] },
  { cmd: 'python3', pre: [] },
  { cmd: 'py', pre: ['-3'] },
];

async function findPython(run: Runner): Promise<{ cmd: string; pre: string[] } | null> {
  for (const candidate of PYTHON_CANDIDATES) {
    const res = await run(candidate.cmd, [...candidate.pre, '--version'], { timeout: 15_000 });
    if (!res.ok) continue;
    const m = /Python (\d+)\.(\d+)/.exec(`${res.stdout}\n${res.stderr}`);
    if (m && (Number(m[1]) < 3 || (Number(m[1]) === 3 && Number(m[2]) < 11))) continue; // the script needs tomllib
    return candidate;
  }
  return null;
}

const FALLBACK = 'Run `/caddis:graph-email --check` in a Claude Code session instead.';

/** `caddis email check`: run the skill's `send_email.py --check`. It sends nothing and prints no secret. */
export async function emailCheck(options: CheckOptions = {}): Promise<number> {
  const home = options.home ?? caddisHome();
  const env = options.env ?? process.env;
  const run = options.run ?? defaultRun;
  const config = options.configPath ?? ((env.CADDIS_EMAIL_CONFIG || '').trim() || emailPaths(home).toml);

  const script = findEmailScript({ home, packageRoot: options.packageRoot });
  if (!script) {
    process.stdout.write(`  could not find send_email.py (the send-email skill is not installed here).\n  ${FALLBACK}\n`);
    return 1;
  }
  const python = await findPython(run);
  if (!python) {
    process.stdout.write(`  Python 3.11 or later was not found on PATH.\n  ${FALLBACK}\n`);
    return 1;
  }

  const result = await run(python.cmd, [...python.pre, '-I', script, '--check'], {
    env: { CADDIS_EMAIL_CONFIG: config },
    timeout: 60_000,
  });
  if (result.failure) {
    process.stdout.write(`  could not run the check (${result.failure}).\n  ${FALLBACK}\n`);
    return 1;
  }
  for (const line of `${result.stdout}\n${result.stderr}`.split(/\r?\n/)) {
    if (line.trim()) process.stdout.write(`  ${line}\n`);
  }
  return result.code ?? 1;
}

// ── setup ───────────────────────────────────────────────────────────────────────────────────────────────────

export interface SetupOptions {
  provider?: string;
  sender?: string;
  envFile?: string;
  tenantId?: string;
  clientId?: string;
  smtpHost?: string;
  smtpSecurity?: string;
  smtpPort?: string | number;
  smtpUsername?: string;
  /** Never prompt. A missing value is an error. */
  yes?: boolean;
  /** Replace an existing email.toml / email.env without asking. */
  force?: boolean;
  dryRun?: boolean;
  /** Skip the check after writing (tests). */
  noCheck?: boolean;
}

export interface SetupDeps {
  home?: string;
  env?: Record<string, string | undefined>;
  prompts?: Prompter;
  run?: Runner;
  packageRoot?: string;
}

class Cancelled extends Error {}
class Invalid extends Error {}

function expandHome(p: string, home: string): string {
  if (p === '~') return home;
  if (p.startsWith('~/') || p.startsWith('~\\')) return path.join(home, p.slice(2));
  return p;
}

function writePrivate(file: string, content: string): void {
  writeFileSync(file, content, { encoding: 'utf8', mode: 0o600 });
  // mode only applies when the file is created. On Windows the user profile ACL is already private.
  if (process.platform !== 'win32') chmodSync(file, 0o600);
}

export async function emailSetup(options: SetupOptions = {}, deps: SetupDeps = {}): Promise<number> {
  const home = deps.home ?? caddisHome();
  const env = deps.env ?? process.env;
  const paths = emailPaths(home);
  const interactive = !options.yes && (deps.prompts !== undefined || Boolean(process.stdin.isTTY));
  const prompts = deps.prompts ?? clackPrompts;
  const say = (line = ''): void => void process.stdout.write(`${line}\n`);

  /** Each ask returns the flag value when given; else prompts; else (non-interactive) records a missing value. */
  const missing: string[] = [];
  const need = <T>(value: T | undefined, flag: string): T | undefined => {
    if (value === undefined || value === '') missing.push(flag);
    return value === '' ? undefined : value;
  };
  const orCancel = <T>(value: T | null): T => {
    if (value === null) throw new Cancelled();
    return value;
  };

  if (interactive) intro('caddis email setup');

  try {
    // 1. Never replace an existing file without a yes.
    const existingToml = existsSync(paths.toml) ? readFileSync(paths.toml, 'utf8') : null;
    if (existingToml !== null && !options.force) {
      say(`  ${paths.toml} already exists. Its settings:`);
      for (const line of summariseExisting(existingToml)) say(`    ${line}`);
      if (!interactive) {
        say('  Nothing written. Use --force to replace it.');
        return 1;
      }
      const yes = orCancel(await prompts.confirm({ message: 'Overwrite it?', initialValue: false }));
      if (!yes) {
        cancel('kept the existing file; nothing written');
        return 1;
      }
    }

    // 2. Provider and sender.
    let provider: Provider;
    if (options.provider !== undefined) {
      if (options.provider !== 'graph' && options.provider !== 'smtp') throw new Invalid('--provider must be graph or smtp');
      provider = options.provider;
    } else if (interactive) {
      provider = orCancel(
        await prompts.select<Provider>({
          message: 'Provider',
          options: [
            { value: 'graph', label: 'Microsoft Graph', hint: 'Entra app registration, client credentials' },
            { value: 'smtp', label: 'SMTP' },
          ],
          initialValue: 'graph',
        }),
      );
    } else {
      provider = 'graph';
    }

    let sender = options.sender?.trim();
    if (sender === undefined && interactive) {
      sender = orCancel(
        await prompts.text({
          message: 'Sender mailbox (the address mail is sent from)',
          placeholder: 'ba-bot@example.com',
          validate: (v) => (isMailbox(v.trim()) ? undefined : 'enter an email address'),
        }),
      ).trim();
    }
    need(sender, '--sender');
    if (sender && !isMailbox(sender)) throw new Invalid('the sender must be an email address');

    // 3. SMTP settings.
    let smtp: SmtpSettings | undefined;
    if (provider === 'smtp') {
      let host = options.smtpHost?.trim();
      if (host === undefined && interactive) {
        host = orCancel(
          await prompts.text({
            message: 'SMTP host',
            validate: (v) => (v.trim() && !/\s/.test(v.trim()) ? undefined : 'enter a host name'),
          }),
        ).trim();
      }
      need(host, '--smtp-host');
      if (host && /\s/.test(host)) throw new Invalid('the SMTP host cannot contain spaces');

      let security: Security | undefined;
      if (options.smtpSecurity !== undefined) {
        if (!SECURITIES.includes(options.smtpSecurity as Security)) throw new Invalid('--smtp-security must be starttls, ssl or none');
        security = options.smtpSecurity as Security;
      } else if (interactive) {
        security = orCancel(
          await prompts.select<Security>({
            message: 'SMTP security',
            options: [
              { value: 'starttls', label: 'starttls', hint: 'port 587' },
              { value: 'ssl', label: 'ssl', hint: 'port 465' },
              { value: 'none', label: 'none', hint: 'port 25, no encryption, no login' },
            ],
            initialValue: 'starttls',
          }),
        );
      } else {
        security = 'starttls';
      }

      let port: number | undefined;
      if (options.smtpPort !== undefined && options.smtpPort !== '') {
        port = Number(options.smtpPort);
      } else if (interactive) {
        const answer = orCancel(
          await prompts.text({
            message: 'SMTP port',
            initialValue: String(defaultPort(security)),
            validate: (v) => (/^\d+$/.test(v.trim()) && Number(v) >= 1 && Number(v) <= 65535 ? undefined : 'enter a port from 1 to 65535'),
          }),
        );
        port = Number(answer.trim());
      } else {
        port = defaultPort(security);
      }
      if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Invalid('the SMTP port must be a number from 1 to 65535');

      let username = options.smtpUsername?.trim();
      if (username === undefined && interactive) {
        username = orCancel(await prompts.text({ message: 'SMTP username (leave empty if the server needs no login)' })).trim();
      }
      username = username ?? '';
      if (/[\r\n]/.test(username)) throw new Invalid('the SMTP username must be one line');
      if (security === 'none' && username) {
        throw new Invalid('SMTP security "none" cannot carry a login (it would go in clear text); use starttls or ssl');
      }
      if (host) smtp = { host, security, port, username };
    }

    // 4. Where the secrets live.
    const requiredKeys =
      provider === 'graph' ? [GRAPH_TENANT_KEY, GRAPH_CLIENT_KEY, GRAPH_SECRET_KEY] : smtp?.username ? [SMTP_PASSWORD_KEY] : [];
    let envFile = options.envFile?.trim();
    let envValues: Record<string, string> | null = null;

    if (requiredKeys.length) {
      let source: 'file' | 'values' | undefined = envFile ? 'file' : undefined;
      const secretFromEnv = (provider === 'graph' ? env[SECRET_ENV_GRAPH] : env[SECRET_ENV_SMTP])?.trim();
      if (!source && interactive) {
        source = orCancel(
          await prompts.select<'file' | 'values'>({
            message: 'Where are the secrets',
            options: [
              { value: 'file', label: 'I have an env file', hint: `it holds ${requiredKeys.join(', ')}` },
              { value: 'values', label: 'Enter the values', hint: 'saved to ~/.caddis/email.env, never to email.toml' },
            ],
            initialValue: 'values',
          }),
        );
      } else if (!source && !interactive) {
        source = 'values';
      }

      if (source === 'file') {
        if (!envFile && interactive) {
          envFile = orCancel(
            await prompts.text({
              message: 'Path to the env file',
              validate: (v) => {
                const p = path.resolve(expandHome(v.trim(), home));
                return v.trim() && existsSync(p) && statSync(p).isFile() ? undefined : 'that file does not exist';
              },
            }),
          ).trim();
        }
        const resolved = path.resolve(expandHome(envFile ?? '', home));
        if (!envFile || !existsSync(resolved) || !statSync(resolved).isFile()) throw new Invalid(`the env file does not exist: ${envFile || '(none given)'}`);
        const absent = envFileMissingKeys(readFileSync(resolved, 'utf8'), requiredKeys);
        if (absent.length) throw new Invalid(`the env file is missing: ${absent.join(', ')}`);
        envFile = resolved;
      } else {
        // The owner gives the values. They go to email.env.
        if (existsSync(paths.env) && !options.force) {
          if (!interactive) {
            say(`  ${paths.env} already exists. Nothing written. Use --force to replace it.`);
            return 1;
          }
          const yes = orCancel(await prompts.confirm({ message: `Overwrite ${paths.env}?`, initialValue: false }));
          if (!yes) {
            cancel('kept the existing file; nothing written');
            return 1;
          }
        }
        if (provider === 'graph') {
          let tenant = options.tenantId?.trim();
          if (tenant === undefined && interactive) {
            tenant = orCancel(
              await prompts.text({
                message: 'Tenant ID (a GUID)',
                validate: (v) => (isGuid(v.trim()) ? undefined : 'a GUID looks like 00000000-0000-0000-0000-000000000000'),
              }),
            ).trim();
          }
          let client = options.clientId?.trim();
          if (client === undefined && interactive) {
            client = orCancel(
              await prompts.text({
                message: 'Client ID (a GUID)',
                validate: (v) => (isGuid(v.trim()) ? undefined : 'a GUID looks like 00000000-0000-0000-0000-000000000000'),
              }),
            ).trim();
          }
          let secret = secretFromEnv || undefined;
          if (secret === undefined && interactive) {
            secret = orCancel(await prompts.password({ message: 'Client secret', validate: (v) => secretProblem('the secret', v.trim()) })).trim();
          }
          need(tenant, '--tenant-id');
          need(client, '--client-id');
          need(secret, `${SECRET_ENV_GRAPH} (environment variable)`);
          if (tenant && !isGuid(tenant)) throw new Invalid('the tenant ID must be a GUID');
          if (client && !isGuid(client)) throw new Invalid('the client ID must be a GUID');
          if (secret) {
            const problem = secretProblem('the client secret', secret);
            if (problem) throw new Invalid(problem);
          }
          if (tenant && client && secret) {
            envValues = { [GRAPH_TENANT_KEY]: tenant, [GRAPH_CLIENT_KEY]: client, [GRAPH_SECRET_KEY]: secret };
          }
        } else {
          let pw = secretFromEnv || undefined;
          if (pw === undefined && interactive) {
            pw = orCancel(await prompts.password({ message: 'SMTP password', validate: (v) => secretProblem('the password', v.trim()) })).trim();
          }
          need(pw, `${SECRET_ENV_SMTP} (environment variable)`);
          if (pw) {
            const problem = secretProblem('the SMTP password', pw);
            if (problem) throw new Invalid(problem);
            envValues = { [SMTP_PASSWORD_KEY]: pw };
          }
        }
        if (envValues) envFile = paths.env;
      }
    }

    if (missing.length) throw new Invalid(`missing: ${missing.join(', ')}. Run without --yes to be asked.`);
    if (!sender) throw new Invalid('missing: --sender');

    // 5. Build, then write.
    const toml = buildToml({ provider, sender, envFile, smtp });

    if (options.dryRun) {
      say('  dry run: would write these non-secret settings to ' + paths.toml);
      for (const line of toml.split('\n')) say(`    ${line}`);
      if (envValues) say(`  and the keys ${Object.keys(envValues).join(', ')} to ${paths.env} (values not shown)`);
      if (interactive) outro('dry run: nothing written');
      return 0;
    }

    mkdirSync(paths.dir, { recursive: true });
    if (envValues) writePrivate(paths.env, buildEnvText(envValues));
    writeFileSync(paths.toml, toml, { encoding: 'utf8' });

    say();
    say(`  wrote ${paths.toml}`);
    if (envValues) say(`  wrote ${paths.env} (${Object.keys(envValues).join(', ')}; values not shown)`);
    else if (envFile) say(`  using your env file ${envFile}`);
  } catch (error) {
    if (error instanceof Cancelled) {
      cancel('cancelled: nothing written');
      return 1;
    }
    errorLine(error instanceof Error ? error.message : String(error));
    return 2;
  }

  // 6. Check.
  if (options.noCheck) {
    if (interactive) outro('done');
    return 0;
  }
  say();
  say('  checking the setup (sends nothing):');
  const code = await emailCheck({ home, env, run: deps.run, packageRoot: deps.packageRoot, configPath: paths.toml });
  if (interactive) {
    outro(code === 0 ? color.green('email is set up. Try /caddis:graph-email in a session.') : 'written, but the check did not pass. Fix the item above, then run `caddis email check`.');
  }
  return code;
}
