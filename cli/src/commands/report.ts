/**
 * The shared fact-gathering layer behind `doctor` and `status`.
 *
 * Both commands answer the same question — "what caddis does each agent have,
 * and does it match what this CLI ships?" — at different verbosity. Gathering
 * it once, here, means they can never disagree.
 */
import type { AgentAdapter, AgentStatus, Detection } from '../agents/types.js';
import { run } from '../util/exec.js';
import { bundleManifest, packageInfo } from '../util/pkg.js';
import { compareVersions } from '../util/semver.js';

export type DriftState =
  | 'current' // agent has exactly the shipped pool version
  | 'stale' // agent has caddis, at an OLDER version than the shipped pool
  | 'ahead' // agent has a NEWER version than this CLI bundles — never drive it, that is a downgrade
  | 'unknown' // agent has caddis but will not say which version
  | 'missing' // agent is present, caddis is not installed into it
  | 'absent' // agent is not on this machine
  | 'unsupported'; // agent detected, no v0.1 adapter

export interface AgentReport {
  adapter: AgentAdapter;
  detection: Detection;
  status: AgentStatus;
  drift: DriftState;
  /**
   * Extras drift, tracked SEPARATELY because `caddis-extras` has its own
   * version line (1.3.13 vs core 1.3.39). Undefined when the agent has no
   * extras concept; 'missing' means "supported here, simply not installed" —
   * which is the normal, non-problem state for an opt-in add-on.
   */
  extrasDrift?: DriftState;
}

export interface CliUpdateInfo {
  current: string;
  latest: string;
}

export interface Report {
  cliVersion: string;
  poolVersion: string;
  /** Version of the shipped `caddis-extras` bundle, if this package ships one. */
  extrasVersion?: string;
  agents: AgentReport[];
  /**
   * Set only when a newer `@caddis/cli` is published than this install carries. This is the
   * root of the "doctor can lie" gap: every per-agent drift check compares against
   * `poolVersion`, which is whatever pool THIS locally-installed CLI happened to bundle at ITS
   * OWN publish time -- not the true upstream latest. A doctor run can report "everything
   * current" while being wrong, because the CLI itself (and the pool it carries) is stale.
   * Undefined when up to date, offline, or the registry lookup fails -- never a defect on its
   * own; see checkCliUpdate.
   */
  cliUpdate?: CliUpdateInfo;
}

/**
 * Whether a newer `@caddis/cli` is published on npm than `currentVersion`. Never throws, never
 * blocks doctor from working offline -- an unreachable registry or any other failure is
 * indistinguishable from "already current" (both return null). Short timeout: this runs on
 * every `doctor` invocation and must not make the command feel hung on a slow network.
 */
export async function checkCliUpdate(currentVersion: string): Promise<CliUpdateInfo | null> {
  const result = await run('npm', ['view', '@caddis/cli', 'version'], { timeout: 5_000 });
  if (!result.ok) return null;
  const latest = result.stdout.trim();
  if (!latest || latest === currentVersion) return null;
  return { current: currentVersion, latest };
}

function classify(adapter: AgentAdapter, detection: Detection, status: AgentStatus, poolVersion: string): DriftState {
  if (!detection.present) return 'absent';
  if (!adapter.supported) return 'unsupported';
  if (!status.installed) return 'missing';
  if (!status.version) return 'unknown';
  if (poolVersion === 'unknown') return 'unknown';
  // Order them, do not just compare them. `!==` cannot distinguish "behind" from "ahead", and the
  // difference decides whether `caddis update` helps or harms: driving an agent that is AHEAD
  // installs this package's older bundled pool over a newer one. Measured live on 2026-08-16 —
  // agy was downgraded from 1.3.74 to 1.3.54 and the run reported success.
  const order = compareVersions(status.version, poolVersion);
  if (order === null) return status.version === poolVersion ? 'current' : 'stale'; // unorderable: old behaviour
  if (order === 0) return 'current';
  return order > 0 ? 'ahead' : 'stale';
}

export interface GatherOptions {
  /**
   * Also check npm for a newer `@caddis/cli` (see `cliUpdate` on Report). Opt-in: `status`
   * (the bare `caddis` command) and `init`/`update` stay network-free by default; `doctor` is
   * the deliberate diagnostic command that asks for it explicitly.
   */
  checkCliUpdate?: boolean;
}

export async function gather(adapters: AgentAdapter[], options: GatherOptions = {}): Promise<Report> {
  const manifest = bundleManifest();
  const poolVersion = manifest.poolVersion;
  const extrasVersion = manifest.bundles['antigravity-plugin-extras'];
  const cliVersion = packageInfo().version;

  // Detection and status both shell out; run the agents concurrently so doctor
  // costs one agent's latency, not the sum of them. The (optional) npm lookup
  // runs alongside them, not after, so it never adds its own latency on top.
  const [agents, cliUpdate] = await Promise.all([
    Promise.all(
      adapters.map(async (adapter): Promise<AgentReport> => {
        const detection = await adapter.detect();
        const status = detection.present ? await adapter.status() : { installed: false, note: 'agent not installed' };
        return {
          adapter,
          detection,
          status,
          drift: classify(adapter, detection, status, poolVersion),
          extrasDrift: classifyExtras(adapter, detection, status, extrasVersion),
        };
      }),
    ),
    options.checkCliUpdate ? checkCliUpdate(cliVersion) : Promise.resolve(null),
  ]);

  return { cliVersion, poolVersion, extrasVersion, agents, cliUpdate: cliUpdate ?? undefined };
}

function classifyExtras(
  adapter: AgentAdapter,
  detection: Detection,
  status: AgentStatus,
  extrasVersion: string | undefined,
): DriftState | undefined {
  if (!status.extras) return undefined; // adapter has no extras concept
  if (!detection.present) return 'absent';
  if (!adapter.supported) return 'unsupported';
  if (!status.extras.installed) return 'missing'; // normal: extras is opt-in
  if (!status.extras.version || !extrasVersion) return 'unknown';
  return status.extras.version === extrasVersion ? 'current' : 'stale';
}

/**
 * Agents this run should actually drive: present, supported, and not already
 * current. An installed-but-stale EXTRAS counts as not-current even when core
 * is current — otherwise `update` would silently leave extras behind.
 * A `missing` extras does not, because extras is opt-in (`--extras` handles it).
 */
export function actionable(report: Report, includeCurrent = false): AgentReport[] {
  return report.agents.filter((entry) => {
    if (!entry.detection.present || !entry.adapter.supported) return false;
    if (includeCurrent) return true;
    // NEVER drive an agent that is ahead of this package's bundle. `--force` still can, because a
    // deliberate rollback is a real thing to want; doing it by default is not.
    if (entry.drift === 'ahead') return false;
    return entry.drift !== 'current' || entry.extrasDrift === 'stale' || entry.extrasDrift === 'unknown';
  });
}
