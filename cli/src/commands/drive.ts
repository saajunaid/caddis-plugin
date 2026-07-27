/**
 * The shared drive loop behind `init` and `update`.
 *
 * Rule: one agent's failure never fails the run. We report per agent and
 * summarise at the end — a machine with a broken agy install must still get
 * its Claude Code plugin updated (plan: "absence is graceful").
 */
import * as clack from '@clack/prompts';
import type { DriveAction } from '../agents/types.js';
import { color, detail, item, line } from '../util/log.js';
import type { AgentReport } from './report.js';

export interface DriveRunOptions {
  action: DriveAction;
  dryRun: boolean;
  /** Add the optional caddis-extras plugin where the adapter supports one. */
  extras?: boolean;
  /** Suppress spinners (non-TTY, CI, --yes piped output). */
  quiet?: boolean;
}

export interface DriveOutcome {
  failed: number;
  changed: number;
  skipped: number;
}

export async function driveAgents(entries: AgentReport[], options: DriveRunOptions): Promise<DriveOutcome> {
  const outcome: DriveOutcome = { failed: 0, changed: 0, skipped: 0 };
  const useSpinner = !options.quiet && process.stdout.isTTY === true && !options.dryRun;

  for (const entry of entries) {
    const label = `${entry.adapter.name}`;
    const spinner = useSpinner ? clack.spinner() : null;
    spinner?.start(`${label} — ${entry.adapter.summary}`);

    const result = await entry.adapter.drive(options.action, {
      dryRun: options.dryRun,
      extras: options.extras === true,
    });

    if (result.skipped) {
      outcome.skipped += 1;
      spinner?.stop(`${label} — ${result.message ?? 'skipped'}`, 0);
      if (!spinner) item('skip', `${label} — ${result.message ?? 'skipped'}`);
      for (const step of result.steps) detail(`would run: ${step.command}`);
      continue;
    }

    if (result.ok) {
      outcome.changed += 1;
      spinner?.stop(`${label} — ${color.green('done')}`, 0);
      if (!spinner) item('ok', `${label} — done`);
      for (const step of result.steps) detail(step.command);
      continue;
    }

    outcome.failed += 1;
    spinner?.stop(`${label} — ${color.red('failed')}`, 1);
    if (!spinner) item('fail', `${label} — failed`);
    if (result.message) detail(result.message);
    for (const step of result.steps) {
      if (step.ok) continue;
      detail(`${step.command} → exit ${step.code ?? '?'}`);
      if (step.output) {
        for (const outputLine of step.output.split(/\r?\n/)) detail(`  ${outputLine}`);
      }
    }
  }

  return outcome;
}

/** Post-run summary + the process exit code. */
export function reportOutcome(outcome: DriveOutcome, dryRun: boolean): number {
  line('');
  if (dryRun) {
    line(`  ${color.cyan('dry run')} — nothing was changed. Re-run without --dry-run to apply.`);
    return 0;
  }
  if (outcome.failed > 0) {
    line(`  ${color.red(`${outcome.failed} agent(s) failed`)}, ${outcome.changed} updated. Run ${color.cyan('caddis doctor')} for detail.`);
    return 1;
  }
  if (outcome.changed === 0) {
    line(`  ${color.green('Nothing to do')} — everything already current.`);
    return 0;
  }
  line(`  ${color.green(`${outcome.changed} agent(s) updated.`)} Run ${color.cyan('caddis status')} to confirm.`);
  return 0;
}
