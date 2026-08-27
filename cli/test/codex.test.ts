/**
 * The Codex adapter is the only one that owns its own install semantics.
 *
 * Claude Code has a marketplace and agy has `agy plugin install <dir>`; both adapters just
 * drive a vendor command and let the vendor decide what lands where. Codex has no such
 * command — skills are directories under `~/.codex/skills/`, so this adapter copies files
 * itself. That makes it the only adapter capable of destroying a user's data, and these
 * tests exist mostly to pin the boundaries of what it is allowed to touch.
 *
 * Layout facts asserted here were MEASURED against codex-cli 0.150.1 on 2026-08-27 by
 * planting probe skills and grepping codex's own session transcript — not by asking the
 * model, which contradicted itself three times and then invented a marker string.
 */
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Mock binary discovery. Without this the suite shells out to the REAL `codex --version`
// with a 20s timeout: it passed alone in 426ms and failed at 24s under parallel load.
// A test that depends on the developer's PATH — and on how loaded their machine is — is
// not a test. Mocked, it asserts the adapter's logic and nothing else.
vi.mock('../src/util/which.js', () => ({ findBin: vi.fn() }));

import { caddisSkillsDir, codexAdapter, statusFromHome, versionFile } from '../src/agents/codex.js';
import { findBin } from '../src/util/which.js';

const mockWhich = vi.mocked(findBin);
beforeEach(() => {
  mockWhich.mockReset();
  mockWhich.mockResolvedValue(null); // default: codex absent
});

const scratches: string[] = [];
function tmpHome(): string {
  const dir = mkdtempSync(path.join(tmpdir(), 'caddis-codex-'));
  scratches.push(dir);
  return dir;
}
afterEach(() => {
  while (scratches.length) rmSync(scratches.pop()!, { recursive: true, force: true });
});

// ── where it installs ───────────────────────────────────────────────────────────────

describe('install location', () => {
  it('namespaces everything under a single caddis/ directory', () => {
    const home = tmpHome();
    expect(caddisSkillsDir(home)).toBe(path.join(home, '.codex', 'skills', 'caddis'));
  });

  it('never installs flat into the user skills root', () => {
    // A flat install would drop ~141 directories beside the user's own skills, which on the
    // machine this was written for already held 134 — with real collisions (api-design,
    // tdd-workflow). Codex indexes nested skills, so namespacing costs nothing and makes
    // the install collision-proof and removable in one rm -rf.
    const home = tmpHome();
    const dir = caddisSkillsDir(home);
    expect(dir).not.toBe(path.join(home, '.codex', 'skills'));
    expect(dir.startsWith(path.join(home, '.codex', 'skills'))).toBe(true);
  });
});

// ── what status can and cannot claim ────────────────────────────────────────────────

describe('status', () => {
  it('reports not-installed on a clean machine', () => {
    const status = statusFromHome(tmpHome());
    expect(status.installed).toBe(false);
    expect(status.version).toBeUndefined();
  });

  it('reads the version caddis wrote, because codex keeps no manifest of its own', () => {
    const home = tmpHome();
    mkdirSync(caddisSkillsDir(home), { recursive: true });
    writeFileSync(versionFile(home), '1.3.82\n', 'utf8');
    expect(statusFromHome(home)).toMatchObject({ installed: true, version: '1.3.82' });
  });

  it('admits it does not know the version of a hand-installed tree', () => {
    // Installed-but-unknown must never be reported as a version, or `caddis status` would
    // compare a guess against the shipped pool and call the result drift.
    const home = tmpHome();
    mkdirSync(path.join(caddisSkillsDir(home), 'workflow'), { recursive: true });
    const status = statusFromHome(home);
    expect(status.installed).toBe(true);
    expect(status.version).toBeUndefined();
    expect(status.note).toMatch(/no version marker/i);
  });

  it('survives an unreadable marker without throwing', () => {
    const home = tmpHome();
    mkdirSync(versionFile(home), { recursive: true }); // a DIRECTORY where a file belongs
    const status = statusFromHome(home);
    expect(status.installed).toBe(true);
    expect(status.version).toBeUndefined();
  });
});

// ── the boundaries that matter ──────────────────────────────────────────────────────

describe('what it refuses to touch', () => {
  it('does not write the user config — the highest-risk thing it could do', () => {
    const source = readFileSync(new URL('../src/agents/codex.ts', import.meta.url), 'utf8');
    const code = source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
    // ~/.codex/config.toml holds the user's model, sandbox policy and feature flags.
    // Merging into it silently would be the one mistake worth failing a build over.
    expect(code).not.toMatch(/config\.toml['"`]/);
    expect(code).toContain('config.toml.example');
  });

  it('removes only its own subtree, never the user skills root', () => {
    const source = readFileSync(new URL('../src/agents/codex.ts', import.meta.url), 'utf8');
    const code = source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
    const removals = [...code.matchAll(/rmSync\(([^,]+),/g)].map((m) => m[1]!.trim());
    expect(removals.length).toBeGreaterThan(0);
    for (const target of removals) {
      // `dest` is caddisSkillsDir(). Anything else being recursively removed is a bug.
      expect(target).toBe('dest');
    }
  });
});

// ── drive() behaviour that does not need a real codex ───────────────────────────────

describe('drive', () => {
  it('skips cleanly when codex is absent', async () => {
    const result = await codexAdapter.drive('install', { dryRun: false });
    expect(result).toMatchObject({ ok: true, skipped: true, steps: [] });
    expect(result.message).toMatch(/not installed/i);
  });

  it('a dry run writes nothing even when codex IS present', async () => {
    mockWhich.mockResolvedValue('/usr/bin/codex');
    const home = tmpHome();
    const before = existsSync(caddisSkillsDir(home));
    const result = await codexAdapter.drive('install', { dryRun: true });

    expect(result.skipped).toBe(true);
    expect(existsSync(caddisSkillsDir(home))).toBe(before);
    if (result.ok) expect(result.message).toMatch(/dry run/i);
    else expect(result.message).toMatch(/bundle/i); // only legitimate failure: unbuilt bundle
  });

  it('is registered as supported, and says config is never merged', () => {
    expect(codexAdapter.supported).toBe(true);
    expect(codexAdapter.summary).toMatch(/never merged/i);
  });
});

// ── a real copy, exercised without codex present ────────────────────────────────────

describe('the copy itself', () => {
  it('replaces the caddis subtree and leaves neighbours alone', () => {
    const home = tmpHome();
    const skillsRoot = path.join(home, '.codex', 'skills');
    const mine = path.join(skillsRoot, 'users-own-skill');
    mkdirSync(mine, { recursive: true });
    writeFileSync(path.join(mine, 'SKILL.md'), 'do not touch me', 'utf8');

    // a stale caddis install with a skill that no longer ships
    const stale = path.join(caddisSkillsDir(home), 'workflow', 'retired-skill');
    mkdirSync(stale, { recursive: true });
    writeFileSync(path.join(stale, 'SKILL.md'), 'stale', 'utf8');

    // what drive() does, in the same order
    const fresh = mkdtempSync(path.join(tmpdir(), 'caddis-src-'));
    scratches.push(fresh);
    mkdirSync(path.join(fresh, 'workflow', 'current-skill'), { recursive: true });
    writeFileSync(path.join(fresh, 'workflow', 'current-skill', 'SKILL.md'), 'fresh', 'utf8');

    rmSync(caddisSkillsDir(home), { recursive: true, force: true });
    cpSync(fresh, caddisSkillsDir(home), { recursive: true });

    // the stale skill is GONE — leaving it would keep it in codex's index, and the model
    // may act on a skill that no longer ships
    expect(existsSync(stale)).toBe(false);
    expect(existsSync(path.join(caddisSkillsDir(home), 'workflow', 'current-skill'))).toBe(true);
    // and the user's own skill is untouched
    expect(readFileSync(path.join(mine, 'SKILL.md'), 'utf8')).toBe('do not touch me');
  });
});
