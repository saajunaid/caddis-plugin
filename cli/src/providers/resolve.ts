/**
 * Provider + key resolution for the model lanes (`claude-oss` / `claude-glm` /
 * `claude-deepseek`).
 *
 * This is a deliberate PORT of `claude-harness/scripts/oss_model.py`, not a wrapper
 * around it. The npm package ships only `dist` and `bundles` (see `files` in
 * package.json), so the Python resolver is not in the tarball at all — a lane binary
 * installed by `npm i -g @caddis/cli` has nothing to shell out to. Porting also drops
 * the Python dependency from the lane path entirely.
 *
 * The two copies must agree. `test/providers.test.ts` reads the PROVIDERS table straight
 * out of the Python file and asserts they match, so a renamed model id or moved endpoint
 * cannot land in one and not the other.
 *
 * These are the providers' ANTHROPIC-protocol endpoints. They feed ANTHROPIC_BASE_URL for
 * Claude Code, which speaks the Anthropic Messages API — NOT the OpenAI /chat/completions
 * dialect that `oss_review.py` uses. Those two tables differ on purpose; do not unify them.
 */
import { readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { isAbsolute, join } from 'node:path';

export interface ProviderPreset {
  baseUrl: string;
  model: string;
  keyEnv: string;
}

/** The SINGLE place a renamed model id or moved endpoint is edited on this side. */
export const PROVIDERS: Record<string, ProviderPreset> = {
  deepseek: {
    baseUrl: 'https://api.deepseek.com/anthropic',
    model: 'deepseek-v4-flash',
    keyEnv: 'DEEPSEEK_API_KEY',
  },
  glm: {
    baseUrl: 'https://api.z.ai/api/anthropic',
    model: 'glm-5.2',
    keyEnv: 'GLM_API_KEY',
  },
  // OpenRouter has no Anthropic-protocol endpoint. It works only through an
  // Anthropic-compatible gateway (e.g. LiteLLM — see claude-harness/LOCAL-MODELS.md)
  // whose URL you supply via OSS_BASE_URL.
  openrouter: {
    baseUrl: '',
    model: 'deepseek/deepseek-v4-flash',
    keyEnv: 'OPENROUTER_API_KEY',
  },
};

export const DEFAULT_PROVIDER = 'deepseek';
export const DEFAULT_KEYS_FILE = '~/.caddis/keys.env';
export const KEYS_FILE_ENV = 'CADDIS_KEYS_FILE';

export class ConfigError extends Error {}

export type Env = Record<string, string | undefined>;

/** Expand a leading `~` — the keys file is documented as `~/.caddis/keys.env`. */
export function expandHome(p: string): string {
  if (p === '~') return homedir();
  if (p.startsWith('~/') || p.startsWith('~\\')) return join(homedir(), p.slice(2));
  return p;
}

export function keysFilePath(env: Env): string {
  const configured = (env[KEYS_FILE_ENV] || '').trim() || DEFAULT_KEYS_FILE;
  const expanded = expandHome(configured);
  return isAbsolute(expanded) ? expanded : expanded;
}

/**
 * Parse a `KEY=VALUE` keys file. Comments (`#`) and blank lines are ignored, surrounding
 * quotes stripped. A missing file yields `{}` — not an error, because the key may still
 * come from the environment. Identical rules to the Python parser, so one file serves both.
 */
export function parseKeysFile(path: string): Record<string, string> {
  let text: string;
  try {
    text = readFileSync(path, 'utf8');
  } catch {
    return {};
  }
  const out: Record<string, string> = {};
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith('#') || !line.includes('=')) continue;
    const idx = line.indexOf('=');
    const key = line.slice(0, idx).trim();
    let val = line.slice(idx + 1).trim();
    if (val.length >= 2 && ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'")))) {
      val = val.slice(1, -1);
    }
    out[key] = val;
  }
  return out;
}

/** Every preset provider that currently has a usable key. Never returns a key VALUE. */
export function configuredProviders(env: Env): string[] {
  const fileKeys = parseKeysFile(keysFilePath(env));
  const generic = (env.OSS_API_KEY || fileKeys.OSS_API_KEY || '').trim();
  const out: string[] = [];
  for (const name of Object.keys(PROVIDERS).sort()) {
    const keyEnv = PROVIDERS[name]!.keyEnv;
    if (generic || (env[keyEnv] || '').trim() || (fileKeys[keyEnv] || '').trim()) out.push(name);
  }
  return out;
}

/**
 * Provider key: explicit env first, then the keys file. Never logged or echoed.
 *
 * The error names the providers that DO have a key, because when DeepSeek is unset and GLM
 * is configured the fix is "use glm", not "go and find a credential you already have".
 */
export function resolveKey(provider: string, keyEnv: string, env: Env): string {
  for (const name of [keyEnv, 'OSS_API_KEY']) {
    const val = (env[name] || '').trim();
    if (val) return val;
  }
  const keysPath = keysFilePath(env);
  const fileKeys = parseKeysFile(keysPath);
  for (const name of [keyEnv, 'OSS_API_KEY']) {
    const val = (fileKeys[name] || '').trim();
    if (val) return val;
  }
  const others = configuredProviders(env).filter((p) => p !== provider);
  const have = others.length
    ? `\nProviders that DO have a key here: ${others.join(', ')}. To use one now: claude-${others[0]}.`
    : '\nRun `caddis keys` to add one.';
  throw new ConfigError(
    `no API key for provider '${provider}'. Set $${keyEnv} (or $OSS_API_KEY), or add\n` +
      `  ${keyEnv}=<your-key>\n` +
      `to your keys file (${keysPath}). Override the file path with $${KEYS_FILE_ENV}.` +
      have,
  );
}

export interface Resolved {
  provider: string;
  baseUrl: string;
  model: string;
  apiKey: string;
}

/**
 * Resolve `{baseUrl, model, apiKey}` for a provider.
 *
 * Provider defaults to `$OSS_PROVIDER`, then deepseek. An UNKNOWN provider is allowed only
 * when OSS_BASE_URL + OSS_MODEL are both supplied — that is the LiteLLM/self-hosted escape
 * hatch. Endpoint/model precedence: OSS_BASE_URL / OSS_MODEL override the preset.
 */
export function resolve(provider: string | undefined, env: Env): Resolved {
  const name = (provider || env.OSS_PROVIDER || DEFAULT_PROVIDER).trim().toLowerCase();
  const preset = PROVIDERS[name];
  const baseUrl = (env.OSS_BASE_URL || '').trim() || preset?.baseUrl || '';
  const model = (env.OSS_MODEL || '').trim() || preset?.model || '';

  if (!preset && (!baseUrl || !model)) {
    throw new ConfigError(
      `unknown provider '${name}'. Known: ${Object.keys(PROVIDERS).sort().join(', ')}.\n` +
        'For anything else, supply both $OSS_BASE_URL and $OSS_MODEL (an Anthropic-protocol\n' +
        'endpoint — see claude-harness/LOCAL-MODELS.md for the gateway setup).',
    );
  }
  if (!baseUrl || !model) {
    throw new ConfigError(
      `provider '${name}' has no ${!baseUrl ? 'base_url' : 'model'}. ` +
        `Supply $OSS_BASE_URL and $OSS_MODEL, or pick another provider.`,
    );
  }

  const keyEnv = preset?.keyEnv || `${name.toUpperCase().replace(/[^A-Z0-9]/g, '_')}_API_KEY`;
  return { provider: name, baseUrl, model, apiKey: resolveKey(name, keyEnv, env) };
}

/** Last 4 characters only — for `--print-config`, which must never reveal a key. */
export function maskKey(key: string): string {
  if (!key) return '(none)';
  return key.length <= 4 ? '*'.repeat(key.length) : `${'*'.repeat(8)}${key.slice(-4)}`;
}
