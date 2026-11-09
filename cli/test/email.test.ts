import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  buildEnvText,
  buildToml,
  defaultPort,
  emailCheck,
  emailSetup,
  envFileMissingKeys,
  findEmailScript,
  isGuid,
  summariseExisting,
  tomlLiteral,
  type Prompter,
} from '../src/commands/email.js';
import { captureStdout } from './helpers.js';

const TENANT = '11111111-2222-3333-4444-555555555555';
const CLIENT = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';
const SECRET = 'Sup3r~Secret.value_XYZ'; // caddis: not-secret
const SMTP_PASS = 'smtp-Pa55w0rd!';

let home: string;
beforeEach(() => {
  home = mkdtempSync(path.join(tmpdir(), 'caddis-email-test-'));
});
afterEach(() => rmSync(home, { recursive: true, force: true }));

const tomlPath = () => path.join(home, '.caddis', 'email.toml');
const envPath = () => path.join(home, '.caddis', 'email.env');

/** Capture stdout and stderr together, so one assertion covers every printed line. */
function capture(): { output: () => string; restore: () => void } {
  const out = captureStdout();
  const err = vi.spyOn(process.stderr, 'write').mockImplementation(() => true);
  return {
    output: () => out.output() + err.mock.calls.map((c) => String(c[0])).join(''),
    restore: () => {
      out.restore();
      err.mockRestore();
    },
  };
}

/** A runner that records calls and answers like python running send_email.py --check. */
function fakeRunner(code = 0, stdout = 'provider: graph\ncheck ok: all settings and credentials are present (nothing sent)') {
  const calls: Array<{ cmd: string; args: string[]; env?: Record<string, string> }> = [];
  const run = vi.fn(async (cmd: string, args: string[], opts: { env?: Record<string, string> } = {}) => {
    calls.push({ cmd, args, env: opts.env });
    if (args[0] === '--version') return { ok: true, code: 0, stdout: 'Python 3.12.1', stderr: '' };
    return { ok: code === 0, code, stdout, stderr: '' };
  });
  return { run, calls };
}

/** A fake script so findEmailScript has something to find under the injected home. */
function plantScript(): string {
  const dir = path.join(home, '.claude', 'plugins', 'cache', 'caddis', 'caddis-extras', '1.3.51', 'skills', 'graph-email', 'scripts');
  mkdirSync(dir, { recursive: true });
  const file = path.join(dir, 'send_email.py');
  writeFileSync(file, '# fake\n');
  return file;
}

describe('pure builders', () => {
  it('builds the exact toml for graph with a Windows env file path', () => {
    const text = buildToml({ provider: 'graph', sender: 'ba-bot@example.com', envFile: 'C:\\Users\\jshaik\\.caddis\\email.env' });
    expect(text).toBe(
      [
        '# Written by `caddis email setup`. Secrets are never stored in this file.',
        '# Every key is described in email.toml.example in the send-email skill folder.',
        'provider = "graph"',
        'sender = "ba-bot@example.com"',
        "env_file = 'C:\\Users\\jshaik\\.caddis\\email.env'",
        '',
        '[graph]',
        'tenant_id_key = "ALERT_GRAPH_TENANT_ID"',
        'client_id_key = "ALERT_GRAPH_CLIENT_ID"',
        'client_secret_key = "ALERT_GRAPH_CLIENT_SECRET"', // caddis: not-secret
        '',
      ].join('\n'),
    );
  });

  it('builds the exact toml for smtp', () => {
    const text = buildToml({
      provider: 'smtp',
      sender: 'bot@example.com',
      envFile: 'D:\\secrets\\mail.env',
      smtp: { host: 'smtp.example.com', security: 'starttls', port: 587, username: 'bot' },
    });
    expect(text).toBe(
      [
        '# Written by `caddis email setup`. Secrets are never stored in this file.',
        '# Every key is described in email.toml.example in the send-email skill folder.',
        'provider = "smtp"',
        'sender = "bot@example.com"',
        "env_file = 'D:\\secrets\\mail.env'",
        '',
        '[smtp]',
        'host = "smtp.example.com"',
        'security = "starttls"',
        'port = 587',
        'username = "bot"',
        'password_key = "EMAIL_SMTP_PASSWORD"', // caddis: not-secret
        'timeout = 30',
        '',
      ].join('\n'),
    );
  });

  it('leaves env_file out when smtp needs no login and no env file', () => {
    const text = buildToml({
      provider: 'smtp',
      sender: 'bot@example.com',
      smtp: { host: 'relay.local', security: 'none', port: 25, username: '' },
    });
    expect(text).not.toContain('env_file');
    expect(text).toContain('username = ""');
  });

  it('refuses an env file path that cannot be a TOML literal string', () => {
    expect(() => tomlLiteral("C:\\it's\\here.env")).toThrow(/single quote/);
    expect(tomlLiteral('C:\\a\\b.env')).toBe("'C:\\a\\b.env'");
  });

  it('builds the env file text', () => {
    expect(buildEnvText({ A_KEY: 'one', B_KEY: 'two' })).toBe(
      '# Written by `caddis email setup`. Keep this file private.\nA_KEY=one\nB_KEY=two\n',
    );
  });

  it('picks the default port by security', () => {
    expect([defaultPort('starttls'), defaultPort('ssl'), defaultPort('none')]).toEqual([587, 465, 25]);
  });

  it('checks the GUID shape', () => {
    expect(isGuid(TENANT)).toBe(true);
    expect(isGuid(TENANT.toUpperCase())).toBe(true);
    expect(isGuid('not-a-guid')).toBe(false);
    expect(isGuid(`${TENANT}x`)).toBe(false);
    expect(isGuid('')).toBe(false);
  });

  it('finds missing env file keys by name only, and ignores comments and empty values', () => {
    const text = ['# comment', 'ALERT_GRAPH_TENANT_ID=abc', 'ALERT_GRAPH_CLIENT_ID=', `ALERT_GRAPH_CLIENT_SECRET="${SECRET}"`].join('\n');
    const missing = envFileMissingKeys(text, ['ALERT_GRAPH_TENANT_ID', 'ALERT_GRAPH_CLIENT_ID', 'ALERT_GRAPH_CLIENT_SECRET']);
    expect(missing).toEqual(['ALERT_GRAPH_CLIENT_ID']);
    expect(JSON.stringify(missing)).not.toContain(SECRET);
  });

  it('summarises an existing email.toml with non-secret lines only', () => {
    const lines = summariseExisting(
      'provider = "smtp"\nsender = "a@b.co"\nenv_file = \'C:\\x.env\'\npassword = "leak"\n[smtp]\nhost = "h"\nsecret_thing = "leak2"\n',
    );
    expect(lines.join('\n')).toContain('provider = "smtp"');
    expect(lines.join('\n')).toContain('host = "h"');
    expect(lines.join('\n')).not.toMatch(/leak/);
  });
});

describe('findEmailScript', () => {
  it('prefers the installed plugin copy', () => {
    const planted = plantScript();
    expect(findEmailScript({ home, packageRoot: path.join(home, 'nowhere') })).toBe(planted);
  });

  it('prefers the core plugin copy over the extras copy', () => {
    plantScript(); // extras
    const dir = path.join(home, '.claude', 'plugins', 'cache', 'caddis', 'caddis', '1.3.186', 'skills', 'send-email', 'scripts');
    mkdirSync(dir, { recursive: true });
    writeFileSync(path.join(dir, 'send_email.py'), '# core');
    expect(findEmailScript({ home, packageRoot: path.join(home, 'nowhere') })).toBe(path.join(dir, 'send_email.py'));
  });

  it('falls back to the bundle in the npm package', () => {
    const root = path.join(home, 'pkg');
    const dir = path.join(root, 'bundles', 'antigravity-plugin', 'skills', 'send-email', 'scripts');
    mkdirSync(dir, { recursive: true });
    writeFileSync(path.join(dir, 'send_email.py'), '#');
    expect(findEmailScript({ home, packageRoot: root })).toBe(path.join(dir, 'send_email.py'));
  });

  it('returns null when no copy exists', () => {
    expect(findEmailScript({ home, packageRoot: path.join(home, 'nowhere') })).toBeNull();
  });
});

describe('emailCheck', () => {
  it('runs the script with -I --check and prints its lines', async () => {
    plantScript();
    const { run, calls } = fakeRunner();
    const out = capture();
    const code = await emailCheck({ home, run, env: {} });
    const printed = out.output();
    out.restore();
    expect(code).toBe(0);
    const call = calls.find((c) => c.args[0] === '-I')!;
    expect(call.args).toEqual(['-I', expect.stringContaining('send_email.py'), '--check']);
    expect(call.env?.CADDIS_EMAIL_CONFIG).toBe(tomlPath());
    expect(printed).toContain('check ok');
  });

  it('names /caddis:graph-email --check when the script is missing', async () => {
    const { run } = fakeRunner();
    const out = capture();
    const code = await emailCheck({ home, run, env: {}, packageRoot: path.join(home, 'nowhere') });
    const printed = out.output();
    out.restore();
    expect(code).toBe(1);
    expect(printed).toContain('/caddis:graph-email --check');
  });

  it('returns the script exit code when the check fails', async () => {
    plantScript();
    const { run } = fakeRunner(2, 'provider: graph\nmissing: env_file');
    const out = capture();
    expect(await emailCheck({ home, run, env: {} })).toBe(2);
    out.restore();
  });
});

describe('emailSetup non-interactive', () => {
  const base = { yes: true, noCheck: true } as const;

  it('writes email.toml and email.env for graph, with the secret from the environment only', async () => {
    const out = capture();
    const code = await emailSetup(
      { ...base, provider: 'graph', sender: 'ba-bot@example.com', tenantId: TENANT, clientId: CLIENT },
      { home, env: { CADDIS_EMAIL_CLIENT_SECRET: SECRET } },
    );
    const printed = out.output();
    out.restore();
    expect(code).toBe(0);
    const toml = readFileSync(tomlPath(), 'utf8');
    expect(toml).toContain(`env_file = '${envPath()}'`);
    expect(toml).not.toContain(SECRET);
    expect(toml).not.toContain(TENANT);
    const env = readFileSync(envPath(), 'utf8');
    expect(env).toContain(`ALERT_GRAPH_TENANT_ID=${TENANT}`);
    expect(env).toContain(`ALERT_GRAPH_CLIENT_ID=${CLIENT}`);
    expect(env).toContain(`ALERT_GRAPH_CLIENT_SECRET=${SECRET}`);
    expect(printed).not.toContain(SECRET);
    if (process.platform !== 'win32') expect(statSync(envPath()).mode & 0o777).toBe(0o600);
  });

  it('uses an existing env file without copying it, after checking the key names', async () => {
    const file = path.join(home, 'mine.env');
    writeFileSync(
      file,
      `ALERT_GRAPH_TENANT_ID=${TENANT}\nALERT_GRAPH_CLIENT_ID=${CLIENT}\nALERT_GRAPH_CLIENT_SECRET=${SECRET}\n`,
    );
    const out = capture();
    const code = await emailSetup({ ...base, provider: 'graph', sender: 'a@b.co', envFile: file }, { home, env: {} });
    const printed = out.output();
    out.restore();
    expect(code).toBe(0);
    expect(readFileSync(tomlPath(), 'utf8')).toContain(`env_file = '${file}'`);
    expect(existsSync(envPath())).toBe(false);
    expect(printed).not.toContain(SECRET);
  });

  it('refuses an env file that is missing a key, naming the key but not any value', async () => {
    const file = path.join(home, 'bad.env');
    writeFileSync(file, `ALERT_GRAPH_TENANT_ID=${TENANT}\nALERT_GRAPH_CLIENT_ID=${CLIENT}\n`);
    const out = capture();
    const code = await emailSetup({ ...base, provider: 'graph', sender: 'a@b.co', envFile: file }, { home, env: {} });
    const printed = out.output();
    out.restore();
    expect(code).toBe(2);
    expect(printed).toContain('ALERT_GRAPH_CLIENT_SECRET');
    expect(printed).not.toContain(TENANT);
    expect(existsSync(tomlPath())).toBe(false);
  });

  it('refuses an env file path that does not exist', async () => {
    const out = capture();
    const code = await emailSetup(
      { ...base, provider: 'graph', sender: 'a@b.co', envFile: path.join(home, 'nope.env') },
      { home, env: {} },
    );
    out.restore();
    expect(code).toBe(2);
    expect(existsSync(tomlPath())).toBe(false);
  });

  it('rejects a bad tenant GUID and a missing secret without writing anything', async () => {
    const out = capture();
    const bad = await emailSetup(
      { ...base, provider: 'graph', sender: 'a@b.co', tenantId: 'nope', clientId: CLIENT },
      { home, env: { CADDIS_EMAIL_CLIENT_SECRET: SECRET } },
    );
    const noSecret = await emailSetup(
      { ...base, provider: 'graph', sender: 'a@b.co', tenantId: TENANT, clientId: CLIENT },
      { home, env: {} },
    );
    out.restore();
    expect([bad, noSecret]).toEqual([2, 2]);
    expect(existsSync(tomlPath())).toBe(false);
    expect(existsSync(envPath())).toBe(false);
  });

  it('writes smtp settings and the password from CADDIS_EMAIL_SMTP_PASSWORD', async () => {
    const out = capture();
    const code = await emailSetup(
      { ...base, provider: 'smtp', sender: 'bot@example.com', smtpHost: 'smtp.example.com', smtpSecurity: 'ssl', smtpUsername: 'bot' },
      { home, env: { CADDIS_EMAIL_SMTP_PASSWORD: SMTP_PASS } },
    );
    const printed = out.output();
    out.restore();
    expect(code).toBe(0);
    const toml = readFileSync(tomlPath(), 'utf8');
    expect(toml).toContain('port = 465');
    expect(toml).not.toContain(SMTP_PASS);
    expect(readFileSync(envPath(), 'utf8')).toContain(`EMAIL_SMTP_PASSWORD=${SMTP_PASS}`);
    expect(printed).not.toContain(SMTP_PASS);
  });

  it('refuses smtp security none with a login', async () => {
    const out = capture();
    const code = await emailSetup(
      { ...base, provider: 'smtp', sender: 'bot@example.com', smtpHost: 'h.example.com', smtpSecurity: 'none', smtpUsername: 'bot' },
      { home, env: { CADDIS_EMAIL_SMTP_PASSWORD: SMTP_PASS } },
    );
    out.restore();
    expect(code).toBe(2);
    expect(existsSync(tomlPath())).toBe(false);
  });

  it('refuses a secret that starts or ends with a quote (the reader would strip it)', async () => {
    const out = capture();
    const code = await emailSetup(
      { ...base, provider: 'graph', sender: 'a@b.co', tenantId: TENANT, clientId: CLIENT },
      { home, env: { CADDIS_EMAIL_CLIENT_SECRET: '"quoted"' } },
    );
    out.restore();
    expect(code).toBe(2);
  });

  it('does not overwrite an existing email.toml without --force, and shows only non-secret settings', async () => {
    mkdirSync(path.dirname(tomlPath()), { recursive: true });
    writeFileSync(tomlPath(), 'provider = "graph"\nsender = "old@example.com"\n');
    const out = capture();
    const code = await emailSetup(
      { ...base, provider: 'graph', sender: 'new@example.com', tenantId: TENANT, clientId: CLIENT },
      { home, env: { CADDIS_EMAIL_CLIENT_SECRET: SECRET } },
    );
    const printed = out.output();
    out.restore();
    expect(code).toBe(1);
    expect(readFileSync(tomlPath(), 'utf8')).toContain('old@example.com');
    expect(printed).toContain('old@example.com');
    expect(existsSync(envPath())).toBe(false);
  });

  it('overwrites with --force', async () => {
    mkdirSync(path.dirname(tomlPath()), { recursive: true });
    writeFileSync(tomlPath(), 'provider = "graph"\nsender = "old@example.com"\n');
    const out = capture();
    const code = await emailSetup(
      { ...base, force: true, provider: 'graph', sender: 'new@example.com', tenantId: TENANT, clientId: CLIENT },
      { home, env: { CADDIS_EMAIL_CLIENT_SECRET: SECRET } },
    );
    out.restore();
    expect(code).toBe(0);
    expect(readFileSync(tomlPath(), 'utf8')).toContain('new@example.com');
  });

  it('refuses to replace an existing email.env without --force', async () => {
    mkdirSync(path.dirname(envPath()), { recursive: true });
    writeFileSync(envPath(), 'KEEP=me\n');
    const out = capture();
    const code = await emailSetup(
      { ...base, provider: 'graph', sender: 'a@b.co', tenantId: TENANT, clientId: CLIENT },
      { home, env: { CADDIS_EMAIL_CLIENT_SECRET: SECRET } },
    );
    out.restore();
    expect(code).toBe(1);
    expect(readFileSync(envPath(), 'utf8')).toBe('KEEP=me\n');
    expect(existsSync(tomlPath())).toBe(false);
  });

  it('writes nothing on --dry-run', async () => {
    const out = capture();
    const code = await emailSetup(
      { ...base, dryRun: true, provider: 'graph', sender: 'a@b.co', tenantId: TENANT, clientId: CLIENT },
      { home, env: { CADDIS_EMAIL_CLIENT_SECRET: SECRET } },
    );
    const printed = out.output();
    out.restore();
    expect(code).toBe(0);
    expect(existsSync(tomlPath())).toBe(false);
    expect(printed).not.toContain(SECRET);
  });

  it('runs the check after writing and returns its exit code', async () => {
    plantScript();
    const { run } = fakeRunner(2, 'provider: graph\nmissing: env_file');
    const out = capture();
    const code = await emailSetup(
      { yes: true, provider: 'graph', sender: 'a@b.co', tenantId: TENANT, clientId: CLIENT },
      { home, env: { CADDIS_EMAIL_CLIENT_SECRET: SECRET }, run },
    );
    out.restore();
    expect(existsSync(tomlPath())).toBe(true);
    expect(code).toBe(2);
  });
});

describe('emailSetup interactive', () => {
  /** Answers by prompt message prefix. A prompt with no answer fails the test. */
  function prompter(answers: Record<string, string | boolean | null>, asked: string[] = []): Prompter {
    const answer = (message: string) => {
      asked.push(message);
      const key = Object.keys(answers).find((k) => message.startsWith(k));
      if (key === undefined) throw new Error(`unexpected prompt: ${message}`);
      return answers[key]!;
    };
    return {
      select: async (o) => answer(o.message) as never,
      text: async (o) => answer(o.message) as never,
      password: async (o) => answer(o.message) as never,
      confirm: async (o) => answer(o.message) as never,
    };
  }

  it('asks for the values, masks the secret, and never prints it', async () => {
    const asked: string[] = [];
    const prompts = prompter(
      {
        Provider: 'graph',
        'Sender mailbox': 'ba-bot@example.com',
        'Where are the secrets': 'values',
        'Tenant ID': TENANT,
        'Client ID': CLIENT,
        'Client secret': SECRET,
      },
      asked,
    );
    const out = capture();
    const code = await emailSetup({ noCheck: true }, { home, env: {}, prompts });
    const printed = out.output();
    out.restore();
    expect(code).toBe(0);
    expect(readFileSync(envPath(), 'utf8')).toContain(`ALERT_GRAPH_CLIENT_SECRET=${SECRET}`);
    expect(readFileSync(tomlPath(), 'utf8')).not.toContain(SECRET);
    expect(printed).not.toContain(SECRET);
    expect(asked).toContain('Client secret');
  });

  it('asks the env file path when the owner has one', async () => {
    const file = path.join(home, 'mine.env');
    writeFileSync(file, `ALERT_GRAPH_TENANT_ID=${TENANT}\nALERT_GRAPH_CLIENT_ID=${CLIENT}\nALERT_GRAPH_CLIENT_SECRET=${SECRET}\n`);
    const prompts = prompter({
      Provider: 'graph',
      'Sender mailbox': 'a@b.co',
      'Where are the secrets': 'file',
      'Path to the env file': file,
    });
    const out = capture();
    const code = await emailSetup({ noCheck: true }, { home, env: {}, prompts });
    out.restore();
    expect(code).toBe(0);
    expect(readFileSync(tomlPath(), 'utf8')).toContain(`env_file = '${file}'`);
  });

  it('asks the smtp questions and a masked password', async () => {
    const prompts = prompter({
      Provider: 'smtp',
      'Sender mailbox': 'bot@example.com',
      'SMTP host': 'smtp.example.com',
      'SMTP security': 'starttls',
      'SMTP port': '587',
      'SMTP username': 'bot',
      'Where are the secrets': 'values',
      'SMTP password': SMTP_PASS,
    });
    const out = capture();
    const code = await emailSetup({ noCheck: true }, { home, env: {}, prompts });
    const printed = out.output();
    out.restore();
    expect(code).toBe(0);
    expect(readFileSync(envPath(), 'utf8')).toContain(`EMAIL_SMTP_PASSWORD=${SMTP_PASS}`);
    expect(printed).not.toContain(SMTP_PASS);
  });

  it('keeps the old file when the owner answers no to the overwrite question', async () => {
    mkdirSync(path.dirname(tomlPath()), { recursive: true });
    writeFileSync(tomlPath(), 'provider = "graph"\nsender = "old@example.com"\n');
    const asked: string[] = [];
    const prompts = prompter({ Overwrite: false }, asked);
    const out = capture();
    const code = await emailSetup({ noCheck: true }, { home, env: {}, prompts });
    out.restore();
    expect(code).toBe(1);
    expect(asked).toEqual([expect.stringMatching(/^Overwrite/)]);
    expect(readFileSync(tomlPath(), 'utf8')).toContain('old@example.com');
  });

  it('writes nothing when the owner cancels', async () => {
    const prompts = prompter({ Provider: 'graph', 'Sender mailbox': null });
    const out = capture();
    const code = await emailSetup({ noCheck: true }, { home, env: {}, prompts });
    out.restore();
    expect(code).toBe(1);
    expect(existsSync(tomlPath())).toBe(false);
  });
});

describe('env file round trip', () => {
  // A value with every character a naive writer could mangle: # = backslash, double quote, inner space.
  const TRICKY = 'p#a=b\\c"d e~f'; // caddis: not-secret

  /** The parse rules of read_env in send_email.py, ported line for line. */
  function readEnvLikePython(textIn: string): Record<string, string> {
    const out: Record<string, string> = {};
    for (const raw of textIn.split(/\r?\n/)) {
      const line = raw.trim();
      if (!line || line.startsWith('#') || !line.includes('=')) continue;
      const at = line.indexOf('=');
      out[line.slice(0, at).trim()] = line
        .slice(at + 1)
        .trim()
        .replace(/^"+|"+$/g, '')
        .replace(/^'+|'+$/g, '');
    }
    return out;
  }

  it('writes a hard secret that the skill reader returns exactly', async () => {
    const out = capture();
    const code = await emailSetup(
      { yes: true, noCheck: true, provider: 'graph', sender: 'a@b.co', tenantId: TENANT, clientId: CLIENT },
      { home, env: { CADDIS_EMAIL_CLIENT_SECRET: TRICKY } }, // caddis: not-secret
    );
    const printed = out.output();
    out.restore();
    expect(code).toBe(0);
    const values = readEnvLikePython(readFileSync(envPath(), 'utf8'));
    expect(values.ALERT_GRAPH_CLIENT_SECRET).toBe(TRICKY); // caddis: not-secret
    expect(values.ALERT_GRAPH_TENANT_ID).toBe(TENANT); // caddis: not-secret
    expect(printed).not.toContain(TRICKY);
  });

  it('is read back exactly by the real send_email.py read_env (skipped without python 3.11+)', () => {
    const scriptDir = fileURLToPath(new URL('../../.github/skills/devops/send-email/scripts', import.meta.url));
    if (!existsSync(path.join(scriptDir, 'send_email.py'))) return; // the mirror has no skill folder
    const file = path.join(home, 'roundtrip.env');
    writeFileSync(file, buildEnvText({ A_KEY: TRICKY, B_KEY: 'plain' }));
    const code =
      'import json,sys; sys.path.insert(0, sys.argv[1]); import send_email; from pathlib import Path; ' +
      'print(json.dumps(send_email.read_env(Path(sys.argv[2]))))';
    for (const py of ['python', 'python3']) {
      const res = spawnSync(py, ['-c', code, scriptDir, file], { encoding: 'utf8' });
      if (res.status !== 0) continue; // no python, or older than 3.11 (no tomllib)
      expect(JSON.parse(res.stdout)).toEqual({ A_KEY: TRICKY, B_KEY: 'plain' });
      return;
    }
  });

  it('rejects a secret the reader would change, with a clear message', async () => {
    for (const bad of ['"starts', 'ends"', "'x'", 'two\nlines']) {
      const out = capture();
      const code = await emailSetup(
        { yes: true, noCheck: true, provider: 'graph', sender: 'a@b.co', tenantId: TENANT, clientId: CLIENT },
        { home, env: { CADDIS_EMAIL_CLIENT_SECRET: bad } }, // caddis: not-secret
      );
      const printed = out.output();
      out.restore();
      expect(code, bad).toBe(2);
      expect(printed, bad).toMatch(/client secret/);
      expect(existsSync(envPath())).toBe(false);
    }
  });
});
