/**
 * `caddis keys` — the one command between a fresh machine and a working model lane.
 *
 * Before this, setting up GLM or DeepSeek on a new machine meant copying scripts, editing
 * PATH, and hand-writing `~/.caddis/keys.env` from a doc. The keys were always the only
 * thing the user actually had to supply; everything else was ceremony.
 *
 * Rules this command holds to:
 *  * A key value is NEVER printed, logged, or echoed back — not even partially, except the
 *    last 4 characters in the status table, which is what lets you tell two keys apart.
 *  * The file is MERGED, never rewritten. Other keys, comments and ordering survive.
 *  * A key that cannot be validated is still SAVED, with a warning. A provider outage must
 *    not stop you configuring a machine.
 */
import { chmodSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { isCancel, cancel, intro, outro, password, confirm } from '@clack/prompts';
import { color } from '../util/log.js';
import {
  PROVIDERS,
  keysFilePath,
  maskKey,
  parseKeysFile,
} from '../providers/resolve.js';

export interface KeysOptions {
  /** Validate what is configured and exit non-zero on any failure. No prompts. */
  check?: boolean;
  dryRun?: boolean;
  yes?: boolean;
}

interface ProbeResult {
  ok: boolean;
  /** true when the key was definitively rejected, as opposed to unreachable. */
  rejected: boolean;
  detail: string;
}

/**
 * One minimal Anthropic-protocol request. 200 means the key works. 401/403 means it is
 * definitively wrong. Anything else — a 500, a timeout, no network — leaves the key alone,
 * because "I could not reach the provider" is not "your key is bad".
 */
export async function probeKey(baseUrl: string, model: string, apiKey: string): Promise<ProbeResult> {
  if (!baseUrl) return { ok: false, rejected: false, detail: 'no endpoint for this provider' };
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15_000);
  try {
    const res = await fetch(`${baseUrl.replace(/\/$/, '')}/v1/messages`, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'anthropic-version': '2023-06-01',
        authorization: `Bearer ${apiKey}`,
        'x-api-key': apiKey,
      },
      body: JSON.stringify({ model, max_tokens: 1, messages: [{ role: 'user', content: 'ping' }] }),
      signal: controller.signal,
    });
    if (res.ok) return { ok: true, rejected: false, detail: 'ok' };
    if (res.status === 401 || res.status === 403) {
      return { ok: false, rejected: true, detail: `rejected (HTTP ${res.status})` };
    }
    return { ok: false, rejected: false, detail: `could not validate (HTTP ${res.status})` };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return { ok: false, rejected: false, detail: `could not validate (${message})` };
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Set `key=value` in a `KEY=VALUE` file, preserving every other line verbatim.
 *
 * Rewriting the file from a parsed dict would silently drop comments and any key this
 * version does not know about — including one a NEWER caddis wrote.
 */
export function upsertKeyLines(existing: string, updates: Record<string, string>): string {
  const lines = existing ? existing.split(/\r?\n/) : [];
  const remaining = { ...updates };

  const out = lines.map((line) => {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#') || !trimmed.includes('=')) return line;
    const name = trimmed.slice(0, trimmed.indexOf('=')).trim();
    if (name in remaining) {
      const value = remaining[name]!;
      delete remaining[name];
      return `${name}=${value}`;
    }
    return line;
  });

  const added = Object.entries(remaining).map(([k, v]) => `${k}=${v}`);
  if (added.length) {
    if (out.length && out[out.length - 1]!.trim() !== '') out.push('');
    out.push('# added by `caddis keys`');
    out.push(...added);
  }
  let text = out.join('\n');
  if (!text.endsWith('\n')) text += '\n';
  return text;
}

/** 0600 on POSIX. On Windows the file inherits the user profile's ACL, which is already private. */
function restrictPermissions(path: string): string | null {
  if (process.platform === 'win32') return null;
  try {
    chmodSync(path, 0o600);
    return null;
  } catch (error) {
    return error instanceof Error ? error.message : String(error);
  }
}

export async function keys(options: KeysOptions = {}): Promise<number> {
  const path = keysFilePath(process.env as Record<string, string | undefined>);
  const fileKeys = parseKeysFile(path);
  const names = Object.keys(PROVIDERS).sort();

  const current = names.map((name) => {
    const preset = PROVIDERS[name]!;
    const fromEnv = (process.env[preset.keyEnv] || '').trim();
    const fromFile = (fileKeys[preset.keyEnv] || '').trim();
    return {
      name,
      preset,
      value: fromEnv || fromFile,
      source: fromEnv ? 'env' : fromFile ? 'file' : null,
    };
  });

  // ── --check: validate what exists, prompt for nothing, exit non-zero on failure ──
  if (options.check) {
    const configured = current.filter((entry) => entry.value);
    if (!configured.length) {
      process.stdout.write(`no provider keys configured (looked in $ENV and ${path})\n`);
      return 1;
    }
    let bad = 0;
    for (const entry of configured) {
      const probe = await probeKey(entry.preset.baseUrl, entry.preset.model, entry.value);
      const label = probe.ok ? color.green('ok') : probe.rejected ? color.red('REJECTED') : color.yellow('unverified');
      process.stdout.write(`  ${entry.name.padEnd(12)} ${label}  ${probe.detail}\n`);
      if (probe.rejected) bad += 1;
    }
    return bad ? 1 : 0;
  }

  // ── interactive ──
  intro('caddis keys');
  process.stdout.write(`  keys file: ${path}\n\n`);
  for (const entry of current) {
    const state = entry.source
      ? `${color.green('present')} (${entry.source}) ${color.dim(maskKey(entry.value))}`
      : color.dim('missing');
    process.stdout.write(`  ${entry.name.padEnd(12)} ${state}\n`);
  }
  process.stdout.write('\n');

  const collected: Record<string, string> = {};
  for (const entry of current) {
    if (entry.source === 'env') {
      process.stdout.write(
        color.dim(`  ${entry.name}: set via $${entry.preset.keyEnv}; the environment wins, skipping\n`),
      );
      continue;
    }
    if (entry.value && !options.yes) {
      const replace = await confirm({
        message: `${entry.name}: a key is already saved. Replace it?`,
        initialValue: false,
      });
      if (isCancel(replace)) {
        cancel('cancelled — nothing written');
        return 1;
      }
      if (!replace) continue;
    } else if (entry.value) {
      continue; // -y: never silently replace a working key
    }

    const entered = await password({
      message: `${entry.name} key (${entry.preset.keyEnv}) — Enter to skip`,
    });
    if (isCancel(entered)) {
      cancel('cancelled — nothing written');
      return 1;
    }
    const value = String(entered || '').trim();
    if (!value) continue;

    const probe = await probeKey(entry.preset.baseUrl, entry.preset.model, value);
    if (probe.rejected) {
      process.stdout.write(color.red(`  ${entry.name}: ${probe.detail} — not saved\n`));
      continue;
    }
    if (!probe.ok) {
      // Saved anyway. A provider outage must not block configuring a machine.
      process.stdout.write(color.yellow(`  ${entry.name}: ${probe.detail} — saving anyway\n`));
    } else {
      process.stdout.write(color.green(`  ${entry.name}: validated\n`));
    }
    collected[entry.preset.keyEnv] = value;
  }

  if (!Object.keys(collected).length) {
    outro('nothing to write');
    return 0;
  }

  if (options.dryRun) {
    outro(`dry run — would write ${Object.keys(collected).join(', ')} to ${path}`);
    return 0;
  }

  let existing = '';
  try {
    existing = readFileSync(path, 'utf8');
  } catch {
    existing = '';
  }
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, upsertKeyLines(existing, collected), { encoding: 'utf8' });
  const permWarning = restrictPermissions(path);

  process.stdout.write(`\n  wrote ${Object.keys(collected).join(', ')} to ${path}\n`);
  if (permWarning) process.stdout.write(color.yellow(`  could not set 0600 on the keys file: ${permWarning}\n`));
  outro('lanes ready — try `claude-glm --print-config`');
  return 0;
}
