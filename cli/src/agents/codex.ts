/**
 * OpenAI Codex adapter.
 *
 * Codex has NO plugin-install command for skills — unlike Claude Code (a marketplace)
 * and agy (`agy plugin install <dir>`). Its skills are simply directories under
 * `~/.codex/skills/`, discovered at session start. So this adapter COPIES files rather
 * than shelling out to the vendor CLI, which makes it the only adapter that owns its own
 * install semantics, and therefore the only one that can clobber a user's files.
 *
 *   install/update = copy the shipped `codex` bundle into ~/.codex/skills/caddis/
 *   status         = read ~/.codex/skills/caddis/.caddis-version
 *
 * MEASURED, NOT ASSUMED (2026-08-27, codex-cli 0.150.1). Every layout decision below was
 * verified by placing a probe skill and grepping the session transcript codex persists at
 * `~/.codex/sessions/**\/*.jsonl` — never by asking the model what it could see. Asked
 * directly, codex contradicted itself three times and then invented a marker string.
 *
 *   - Codex indexes skills NESTED, not only flat. A probe at
 *     `~/.codex/skills/caddis/workflow/<name>/SKILL.md` (depth 3) was indexed.
 *   - It indexes PROJECT-level `.codex/skills/` too, at both depths.
 *   - It sends the model an INDEX (names + descriptions) and loads a skill BODY on demand.
 *
 * WHY NAMESPACED UNDER `caddis/`. A flat install would drop ~141 skill directories
 * straight into `~/.codex/skills/`, where this machine already had 134 of the user's own —
 * with real name collisions (`api-design`, `tdd-workflow`). Nesting under one `caddis/`
 * root makes the install collision-proof, removable in one `rm -rf`, and greppable. Since
 * nesting is indexed, it costs nothing.
 *
 * WHAT THIS ADAPTER DELIBERATELY WILL NOT DO. It never writes `~/.codex/config.toml`.
 * The parking-lot item named config merge "the highest-risk item in the npm plan", and the
 * risk is real: that file holds the user's model, sandbox policy and feature flags. The
 * bundle ships `config.toml.example`; this adapter copies it BESIDE the install and tells
 * the user. A merge that silently changes someone's sandbox policy is not worth the
 * convenience of skipping one copy-paste.
 */
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import type {
  AgentAdapter, AgentStatus, Detection, DriveAction, DriveOptions, DriveResult, StepResult,
} from './types.js';
import { run } from '../util/exec.js';
import { findBin } from '../util/which.js';
import { bundleManifest, bundlePath } from '../util/pkg.js';

const BIN = 'codex';
const BUNDLE = 'codex';

/** Everything caddis owns lives under this one directory. Nothing outside it is touched. */
export function caddisSkillsDir(home = os.homedir()): string {
  return path.join(home, '.codex', 'skills', 'caddis');
}

/**
 * Codex keeps no manifest of what installed a skill, so caddis writes its own. Without it
 * `caddis status` cannot answer "which caddis does codex have?", and drift becomes
 * invisible — the failure mode that produced the version-drift work earlier in this CLI.
 */
export function versionFile(home = os.homedir()): string {
  return path.join(caddisSkillsDir(home), '.caddis-version');
}

async function detect(): Promise<Detection> {
  const binPath = await findBin(BIN);
  if (!binPath) {
    // A config directory without a binary still means codex was here. Report it, so
    // `doctor` can say "configured but not installed" rather than "absent".
    const configDir = path.join(os.homedir(), '.codex');
    if (existsSync(configDir)) {
      return { present: false, path: configDir, note: 'no `codex` binary on PATH, but ~/.codex exists' };
    }
    return { present: false, note: 'no `codex` binary on PATH' };
  }
  const version = await run(BIN, ['--version'], { timeout: 20_000 });
  return {
    present: true,
    path: binPath,
    // `codex --version` prints "codex-cli 0.150.1"; take the trailing token.
    agentVersion: version.ok ? (version.stdout.trim().split(/\s+/).pop() || undefined) : undefined,
    note: version.ok ? undefined : 'binary found but `codex --version` failed',
  };
}

function shortenHome(target: string): string {
  const home = os.homedir();
  return target.startsWith(home) ? path.join('~', target.slice(home.length)) : target;
}

/** Split out so tests pass a home directory instead of spying on a node builtin. */
export function statusFromHome(home: string): AgentStatus {
  const marker = versionFile(home);
  const dir = caddisSkillsDir(home);

  if (existsSync(marker)) {
    try {
      const version = readFileSync(marker, 'utf8').trim();
      if (version) return { installed: true, version, source: shortenHome(marker) };
    } catch {
      /* fall through to the unreadable-marker case */
    }
    return { installed: true, source: shortenHome(marker), note: 'version marker present but unreadable' };
  }

  if (existsSync(dir)) {
    return {
      installed: true,
      source: shortenHome(dir),
      note: 'skills present but no version marker — installed by hand, or by a caddis older than this one',
    };
  }
  return { installed: false, source: shortenHome(dir), note: 'caddis skills not installed into codex' };
}

async function status(): Promise<AgentStatus> {
  const detected = await detect();
  if (!detected.present) return { installed: false, note: 'agent not installed' };
  return statusFromHome(os.homedir());
}

async function drive(action: DriveAction, options: DriveOptions): Promise<DriveResult> {
  const detected = await detect();
  if (!detected.present) {
    return { ok: true, skipped: true, steps: [], message: 'codex not installed — skipped' };
  }

  const bundle = bundlePath(BUNDLE, { requireManifest: false });
  if (!bundle) {
    return {
      ok: false, skipped: false, steps: [],
      message: `the ${BUNDLE} bundle is missing from this package — reinstall @caddis/cli`,
    };
  }

  // The export puts the skills under `<bundle>/.codex/skills/`. Take that subtree only;
  // AGENTS.md and config.toml.example are handled separately and deliberately.
  const source = path.join(bundle, '.codex', 'skills');
  if (!existsSync(source)) {
    return {
      ok: false, skipped: false, steps: [],
      message: `the ${BUNDLE} bundle has no .codex/skills directory — the export shape changed`,
    };
  }

  const home = os.homedir();
  const dest = caddisSkillsDir(home);
  const version = bundleManifest().poolVersion || 'unknown';
  const label = `copy ${BUNDLE} skills -> ${shortenHome(dest)}`;
  const steps: StepResult[] = [];

  if (options.dryRun) {
    return {
      ok: true, skipped: true,
      steps: [{ command: label, ok: true, code: 0 }],
      message: `dry run — would ${action} caddis ${version} into ${shortenHome(dest)}`,
    };
  }

  try {
    // Replace rather than merge. A stale skill left from an older caddis is worse than a
    // missing one: it stays in codex's index and the model may act on it. Only the
    // `caddis/` subtree is removed — the user's own skills sit outside it, untouched.
    if (existsSync(dest)) rmSync(dest, { recursive: true, force: true });
    mkdirSync(path.dirname(dest), { recursive: true });
    cpSync(source, dest, { recursive: true });
    writeFileSync(versionFile(home), `${version}\n`, 'utf8');
    steps.push({ command: label, ok: true, code: 0 });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    steps.push({ command: label, ok: false, code: null, output: message });
    return { ok: false, skipped: false, steps, message: `could not install into codex: ${message}` };
  }

  // AGENTS.md and config.toml.example: copied BESIDE the install, never merged into the
  // user's own files. See the header — config merge is the one thing this adapter refuses.
  const notes: string[] = [];
  for (const asset of ['AGENTS.md', path.join('.codex', 'config.toml.example')]) {
    const from = path.join(bundle, asset);
    if (!existsSync(from)) continue;
    const to = path.join(dest, `caddis-${path.basename(asset)}`);
    try {
      cpSync(from, to);
      notes.push(path.basename(to));
    } catch {
      /* a reference copy failing is not worth failing the install over */
    }
  }

  const extrasNote = options.extras
    ? ' (--extras has no codex bundle yet; core only)'
    : '';
  const referenceNote = notes.length
    ? ` Reference copies beside it: ${notes.join(', ')} — config.toml is NEVER merged for you.`
    : '';

  return {
    ok: true, skipped: false, steps,
    message: `caddis ${version} ${action === 'install' ? 'installed' : 'updated'} in ${shortenHome(dest)}.${referenceNote}${extrasNote}`,
  };
}

export const codexAdapter: AgentAdapter = {
  id: 'codex',
  name: 'Codex',
  supported: true,
  summary: 'copy the caddis skill pool into ~/.codex/skills/caddis/ (config.toml never merged)',
  detect,
  drive,
  status,
};
