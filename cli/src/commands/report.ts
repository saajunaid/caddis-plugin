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
}

export interface Report {
  cliVersion: string;
  poolVersion: string;
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
  const { poolVersion } = bundleManifest();

  // Detection and status both shell out; run the agents concurrently so doctor
  // costs one agent's latency, not the sum of them.
  const agents = await Promise.all(
    adapters.map(async (adapter): Promise<AgentReport> => {
      const detection = await adapter.detect();
      const status = detection.present ? await adapter.status() : { installed: false, note: 'agent not installed' };
      return { adapter, detection, status, drift: classify(adapter, detection, status, poolVersion) };
    }),
  );

  return { cliVersion: packageInfo().version, poolVersion, agents };
}

/** Agents this run should actually drive: present, supported, and not already current. */
export function actionable(report: Report, includeCurrent = false): AgentReport[] {
  return report.agents.filter(
    (entry) =>
      entry.detection.present &&
      entry.adapter.supported &&
      (includeCurrent || entry.drift !== 'current'),
  );
}
