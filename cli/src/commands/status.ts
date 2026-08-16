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
  line(
    // The pool is named as the YARDSTICK, in the header, because that is what every verdict below
    // is measured against and status cannot see the marketplace — it is deliberately network-free.
    // A tool that cannot know something must not print a verdict that implies it does.
    //
    // Deliberately NOT a footer line. The first attempt added one, and it broke the existing
    // "stays quiet when everything is current" test — correctly: a qualifier phrased like a warning
    // fires on every healthy run, and a warning that always fires is the one nobody reads. doctor
    // carries the strong version, because doctor is where the network check actually happens.
    `  ${color.bold('caddis')}  cli ${color.bold(report.cliVersion)}  ·  pool ${color.bold(report.poolVersion)} ` +
      `${color.dim('(what "current" is measured against)')}` +
      (report.extrasVersion ? `  ·  extras ${color.bold(report.extrasVersion)}` : ''),
  );
  line('');
  line(renderTable(['AGENT', 'DETECTED', 'CADDIS', 'EXTRAS', 'STATE'], report.agents.map(toRow)));
  line('');

  // 'ahead' is deliberately excluded — it is not "behind", and counting it produced the exact
  // inversion this fixes: the newest agent on the machine reported as needing an update.
  const stale = report.agents.filter(
    (entry) => entry.drift === 'stale' || entry.drift === 'missing' || entry.extrasDrift === 'stale',
  );
  const ahead = report.agents.filter((entry) => entry.drift === 'ahead');
  if (stale.length > 0) {
    line(`  ${color.yellow(`${stale.length} agent(s) behind`)} — run ${color.cyan('caddis update')} (or ${color.cyan('caddis doctor')} for detail)`);
    line('');
  }
  if (ahead.length > 0) {
    // The CLI's bundled pool only moves when the CLI is republished to npm, so it lags the plugin
    // marketplace by design. Say so, or the reader assumes something is broken.
    line(
      `  ${ahead.length} agent(s) are NEWER than this CLI's bundled pool (${report.poolVersion}) — ` +
        `left alone. Update the CLI itself (${color.cyan('npm i -g @caddis/cli')}) to catch up.`,
    );
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
    // Extras gets its own column rather than being folded into CADDIS: it
    // versions independently, so showing one number for both would be a lie.
    (managed && entry.status.extras?.version) || color.dim('—'),
    stateLabel(entry.drift, entry.status.disabled ?? false),
  ];
}

function stateLabel(drift: DriftState, disabled: boolean): string {
  switch (drift) {
    case 'current':
      return disabled ? color.yellow('current, disabled') : color.green('current');
    case 'stale':
      return color.yellow('update available');
    case 'ahead':
      // Not a problem, and NOT something `caddis update` should act on: this agent is newer than
      // the pool this CLI bundles. Saying "current" would hide a real fact; saying "update
      // available" would invite a downgrade. Say what is true.
      return color.green('newer than CLI pool');
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
