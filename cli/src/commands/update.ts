/**
 * `caddis update` — bring every present, supported agent up to the caddis
 * version shipped in this package, via that agent's own native mechanism.
 */
import type { AgentAdapter } from '../agents/types.js';
import { color, heading, item, line } from '../util/log.js';
import { driveAgents, reportOutcome } from './drive.js';
import { actionable, gather } from './report.js';

export interface UpdateOptions {
  adapters: AgentAdapter[];
  dryRun: boolean;
  yes: boolean;
  /** Drive even agents already reporting the shipped version. */
  force?: boolean;
  /** Add the optional caddis-extras plugin. */
  extras?: boolean;
}

export async function update(options: UpdateOptions): Promise<number> {
  const report = await gather(options.adapters);

  heading(`caddis update → pool ${color.bold(report.poolVersion)}`);

  // Say what is being skipped and why BEFORE doing anything. A silent skip
  // reads as a bug when the user expected four agents and saw two.
  for (const entry of report.agents) {
    if (!entry.detection.present) {
      item('skip', `${entry.adapter.name} — not installed`);
    } else if (!entry.adapter.supported) {
      item('info', `${entry.adapter.name} — detected, not yet supported (v0.2)`);
    }
  }

  const targets = actionable(report, options.force === true);
  if (targets.length === 0) {
    const supportedPresent = report.agents.filter((e) => e.detection.present && e.adapter.supported);
    line('');
    line(
      supportedPresent.length === 0
        ? `  ${color.yellow('No supported agent found.')} caddis v0.1 drives Claude Code and agy.`
        : `  ${color.green('Everything is already current.')} Use --force to re-drive anyway.`,
    );
    return 0;
  }

  line('');
  const outcome = await driveAgents(targets, {
    action: 'update',
    dryRun: options.dryRun,
    extras: options.extras,
    quiet: options.yes,
  });
  return reportOutcome(outcome, options.dryRun);
}
