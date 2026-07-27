/**
 * `caddis status` — the compact answer.
 *
 * doctor explains and prescribes; status is the one table you glance at.
 * Same facts, same source (report.gather), no advice.
 */
import type { AgentAdapter } from '../agents/types.js';
import { color, line } from '../util/log.js';
import { renderTable } from '../util/table.js';
import type { AgentReport, DriftState, Report } from './report.js';
import { gather } from './report.js';

export interface StatusOptions {
  adapters: AgentAdapter[];
  json?: boolean;
}

export async function status(options: StatusOptions): Promise<number> {
  const report = await gather(options.adapters);

  if (options.json) {
    line(JSON.stringify(toJson(report), null, 2));
    return 0;
  }

  line('');
  line(`  ${color.bold('caddis')}  cli ${color.bold(report.cliVersion)}  ·  pool ${color.bold(report.poolVersion)}`);
  line('');
  line(renderTable(['AGENT', 'DETECTED', 'CADDIS', 'STATE'], report.agents.map(toRow)));
  line('');

  const stale = report.agents.filter((entry) => entry.drift === 'stale' || entry.drift === 'missing');
  if (stale.length > 0) {
    line(`  ${color.yellow(`${stale.length} agent(s) behind`)} — run ${color.cyan('caddis update')} (or ${color.cyan('caddis doctor')} for detail)`);
    line('');
  }
  return 0;
}

function toRow(entry: AgentReport): string[] {
  // Only show a caddis version for an agent this CLI actually manages. An
  // absent or not-yet-supported agent has no meaningful version, and printing
  // one there reads as "caddis is installed in Codex" — which is exactly what
  // v0.1 does not do.
  const managed = entry.drift !== 'unsupported' && entry.drift !== 'absent';
  return [
    entry.adapter.name,
    entry.detection.present ? color.green('yes') : color.dim('no'),
    (managed && entry.status.version) || color.dim('—'),
    stateLabel(entry.drift, entry.status.disabled ?? false),
  ];
}

function stateLabel(drift: DriftState, disabled: boolean): string {
  switch (drift) {
    case 'current':
      return disabled ? color.yellow('current, disabled') : color.green('current');
    case 'stale':
      return color.yellow('update available');
    case 'unknown':
      return color.yellow('version unknown');
    case 'missing':
      return color.yellow('not installed');
    case 'unsupported':
      return color.dim('v0.2');
    case 'absent':
      return color.dim('—');
  }
}

function toJson(report: Report) {
  return {
    cliVersion: report.cliVersion,
    poolVersion: report.poolVersion,
    agents: report.agents.map((entry) => ({
      id: entry.adapter.id,
      present: entry.detection.present,
      caddisVersion: entry.status.version ?? null,
      drift: entry.drift,
    })),
  };
}
