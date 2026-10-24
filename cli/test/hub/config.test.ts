import { mkdtempSync, rmSync, writeFileSync, readFileSync, readdirSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { hubDir, configPath, registryPath } from '../../src/hub/paths.js';
import { readConfig, readRegistry, addRepos, writeJsonAtomic, resetHubCache, DEFAULT_PORT } from '../../src/hub/config.js';

let home: string;
const saved = process.env.CADDIS_HOME;

beforeEach(() => {
  home = mkdtempSync(path.join(tmpdir(), 'caddis-hub-'));
  process.env.CADDIS_HOME = home;
  resetHubCache();
});
afterEach(() => {
  if (saved === undefined) delete process.env.CADDIS_HOME;
  else process.env.CADDIS_HOME = saved;
  rmSync(home, { recursive: true, force: true });
});

describe('paths', () => {
  it('puts the hub dir under CADDIS_HOME/.caddis/hub', () => {
    expect(hubDir()).toBe(path.join(home, '.caddis', 'hub'));
    expect(configPath()).toBe(path.join(hubDir(), 'config.json'));
    expect(registryPath()).toBe(path.join(hubDir(), 'repos.json'));
  });
});

describe('config', () => {
  it('returns defaults when the file is missing', () => {
    const r = readConfig();
    expect(r.error).toBeUndefined();
    expect(r.value).toEqual({ schema: 1, port: DEFAULT_PORT, accounts: {}, pinned: [], hidden: [] });
    expect(DEFAULT_PORT).toBe(47821);
  });

  it('fills missing keys with defaults', () => {
    writeJsonAtomic(configPath(), { schema: 1, port: 50000 });
    const r = readConfig();
    expect(r.value.port).toBe(50000);
    expect(r.value.pinned).toEqual([]);
    expect(r.value.accounts).toEqual({});
  });

  it('round trips', () => {
    const cfg = { schema: 1 as const, port: 50001, accounts: { 'acme/shop': 'acme-bot' }, pinned: ['acme/shop'], hidden: ['x'] };
    writeJsonAtomic(configPath(), cfg);
    expect(readConfig().value).toEqual(cfg);
  });

  it('keeps the last good copy on corrupt JSON and reports the error', () => {
    writeJsonAtomic(configPath(), { schema: 1, port: 50002 });
    expect(readConfig().value.port).toBe(50002);
    writeFileSync(configPath(), '{ not json');
    const r = readConfig();
    expect(r.value.port).toBe(50002);
    expect(r.error).toMatch(/config\.json/);
  });

  it('returns defaults plus an error when corrupt and no good copy exists', () => {
    writeJsonAtomic(configPath(), {});
    writeFileSync(configPath(), 'oops');
    resetHubCache();
    const r = readConfig();
    expect(r.value.port).toBe(DEFAULT_PORT);
    expect(r.error).toBeDefined();
  });

  it('keeps a numeric port as written, so start/serve can refuse an out-of-range one', () => {
    writeJsonAtomic(configPath(), { schema: 1, port: 70000 });
    expect(readConfig().value.port).toBe(70000);
  });

  it('readConfig takes an explicit home', () => {
    writeJsonAtomic(configPath(home), { schema: 1, port: 50003 });
    resetHubCache();
    expect(readConfig(home).value.port).toBe(50003);
  });

  it('rejects a wrong-typed port with defaults for that key', () => {
    writeJsonAtomic(configPath(), { schema: 1, port: 'abc' });
    expect(readConfig().value.port).toBe(DEFAULT_PORT);
  });
});

describe('atomic write', () => {
  it('leaves no temp file behind and creates the hub dir', () => {
    writeJsonAtomic(registryPath(), { schema: 1, repos: [] });
    expect(readdirSync(hubDir())).toEqual(['repos.json']);
    expect(existsSync(hubDir())).toBe(true);
  });
  it.skipIf(process.platform === 'win32')('creates files 0600 and the dir 0700 on POSIX', async () => {
    const { statSync } = await import('node:fs');
    writeJsonAtomic(registryPath(), { schema: 1, repos: [] });
    expect(statSync(registryPath()).mode & 0o777).toBe(0o600);
    expect(statSync(hubDir()).mode & 0o777).toBe(0o700);
  });
});

describe('registry', () => {
  it('is empty by default', () => {
    expect(readRegistry().value).toEqual({ schema: 1, repos: [] });
  });

  it('adds repos with a UTC Z timestamp and normalizes paths', () => {
    const a = path.join(home, 'acme', 'shop');
    addRepos([a + path.sep]);
    const repos = readRegistry().value.repos;
    expect(repos).toHaveLength(1);
    expect(repos[0]!.path).toBe(a);
    expect(repos[0]!.added_at).toMatch(/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z$/);
  });

  it('de-duplicates by normalized path and keeps the first added_at', () => {
    const a = path.join(home, 'acme', 'shop');
    addRepos([a]);
    const first = readRegistry().value.repos[0]!.added_at;
    addRepos([a + path.sep, path.join(a, '..', 'shop'), path.join(home, 'other')]);
    const repos = readRegistry().value.repos;
    expect(repos.map((r) => r.path)).toEqual([a, path.join(home, 'other')]);
    expect(repos[0]!.added_at).toBe(first);
  });

  it('treats case as significant only off Windows', () => {
    const a = path.join(home, 'Acme');
    addRepos([a, path.join(home, 'acme')]);
    expect(readRegistry().value.repos).toHaveLength(process.platform === 'win32' ? 1 : 2);
  });

  it('keeps the last good registry on corrupt JSON', () => {
    addRepos([path.join(home, 'one')]);
    readRegistry();
    writeFileSync(registryPath(), '}{');
    const r = readRegistry();
    expect(r.value.repos).toHaveLength(1);
    expect(r.error).toMatch(/repos\.json/);
    expect(readFileSync(registryPath(), 'utf8')).toBe('}{');
  });

  it('does not overwrite a corrupt registry when adding', () => {
    addRepos([path.join(home, 'one')]);
    writeFileSync(registryPath(), '}{');
    const r = addRepos([path.join(home, 'two')]);
    expect(r.error).toBeDefined();
    expect(readFileSync(registryPath(), 'utf8')).toBe('}{');
  });
});
