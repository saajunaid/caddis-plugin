/**
 * `caddis init` — the first-run path: detect what is on the machine, show it,
 * confirm, then drive each agent's native installer.
 *
 * The confirm step is the point. init is the command a stranger runs via
 * `npx @caddis/cli init` having never seen this tool — it must show exactly
 * which agents it is about to touch and what it will run, before it runs it.
 */
import * as clack from '@clack/prompts';
import type { AgentAdapter } from '../agents/types.js';
import { color, heading, item, line, renderBanner } from '../util/log.js';
import { driveAgents, reportOutcome } from './drive.js';
import { actionable, gather } from './report.js';

export interface InitOptions {
  adapters: AgentAdapter[];
  dryRun: boolean;
  yes: boolean;
  /** Add the optional caddis-extras plugin. */
  extras?: boolean;
}

export async function init(options: InitOptions): Promise<number> {
  const report = await gather(options.adapters);
  const interactive = !options.yes && !options.dryRun && process.stdout.isTTY === true;

  renderBanner({ cliVersion: report.cliVersion, poolVersion: report.poolVersion });
  clack.intro(`${color.bold('caddis installer')} ${color.dim(`· pool ${report.poolVersion}`)}`);

  heading('Detected Agents');
  for (const entry of report.agents) {
    if (!entry.detection.present) {
      item('skip', `${entry.adapter.name} — ${color.dim('not found')}`);
      continue;
    }
    if (!entry.adapter.supported) {
      item('info', `${entry.adapter.name} — ${color.dim('detected, not yet supported (v0.2)')}`);
      continue;
    }
    const current = entry.drift === 'current';
    item(
      current ? 'ok' : 'warn',
      `${entry.adapter.name} — ${
        current
          ? `caddis ${entry.status.version} ${color.dim('(current)')}`
          : entry.status.installed
            ? `caddis ${entry.status.version ?? '?'} → ${color.bold(report.poolVersion)}`
            : color.amber('caddis not installed')
      }`,
    );
  }

  // init is the install path, so it drives every present+supported agent —
  // including ones already current. Re-running a native installer over an
  // up-to-date plugin is a no-op in both Claude Code and agy.
  // includeCurrent, but NOT allowDowngrade: init reinstalls every detected agent, and must
  // never roll one back to this package's older bundle.
  const targets = actionable(report, { includeCurrent: true });

  if (targets.length === 0) {
    clack.outro(
      `${color.yellow('No supported agent found.')} caddis v0.1 drives Claude Code and agy — install one, then re-run.`,
    );
    return 0;
  }

  line('');
  heading('Planned Installations');
  for (const entry of targets) {
    line(`    ${color.mint('•')} ${color.bold(entry.adapter.name)}`);
    line(`      ${color.dim('→')} ${entry.adapter.summary}`);
  }
  line('');

  if (interactive) {
    const confirmed = await clack.confirm({
      message: `Install caddis ${report.poolVersion} into ${targets.length} agent(s)?`,
      initialValue: true,
    });
    if (clack.isCancel(confirmed) || !confirmed) {
      clack.cancel('Cancelled — nothing changed.');
      return 0;
    }
  }

  const outcome = await driveAgents(targets, {
    action: 'install',
    dryRun: options.dryRun,
    extras: options.extras,
    quiet: options.yes,
  });
  const code = reportOutcome(outcome, options.dryRun);
  if (code === 0 && !options.dryRun) {
    line('');
    line(`  ${color.mint('✓')} ${color.bold('Caddis dev harness is ready.')} Open any configured agent above to start.`);
    line(`  ${color.dim('Run')} ${color.sky('caddis doctor')} ${color.dim('at any time to verify agent health and updates.')}`);
    line('');
  }
  clack.outro(code === 0 ? color.green('Setup complete.') : color.red('Finished with errors.'));
  return code;
}
