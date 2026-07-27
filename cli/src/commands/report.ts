/**
 * The shared fact-gathering layer behind `doctor` and `status`.
 *
 * Both commands answer the same question — "what caddis does each agent have,
 * and does it match what this CLI ships?" — at different verbosity. Gathering
 * it once, here, means they can never disagree.
 */
import type { AgentAdapter, AgentStatus, Detection } from '../agents/types.js';
import { bundleManifest, packageInfo } from '../util/pkg.js';

export type DriftState =
  | 'current' // agent has exactly the shipped pool version
  | 'stale' // agent has caddis, at a different version
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

export interface Report {
  cliVersion: string;
  poolVersion: string;
  /** Version of the shipped `caddis-extras` bundle, if this package ships one. */
  extrasVersion?: string;
  agents: AgentReport[];
}

function classify(adapter: AgentAdapter, detection: Detection, status: AgentStatus, poolVersion: string): DriftState {
  if (!detection.present) return 'absent';
  if (!adapter.supported) return 'unsupported';
  if (!status.installed) return 'missing';
  if (!status.version) return 'unknown';
  if (poolVersion === 'unknown') return 'unknown';
  return status.version === poolVersion ? 'current' : 'stale';
}

export async function gather(adapters: AgentAdapter[]): Promise<Report> {
  const manifest = bundleManifest();
  const poolVersion = manifest.poolVersion;
  const extrasVersion = manifest.bundles['antigravity-plugin-extras'];

  // Detection and status both shell out; run the agents concurrently so doctor
  // costs one agent's latency, not the sum of them.
  const agents = await Promise.all(
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
  );

  return { cliVersion: packageInfo().version, poolVersion, extrasVersion, agents };
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
    return entry.drift !== 'current' || entry.extrasDrift === 'stale' || entry.extrasDrift === 'unknown';
  });
}
