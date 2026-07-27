/**
 * `caddis doctor` — the differentiated value.
 *
 * Everything else in this CLI is a wrapper around a vendor command a user
 * could type themselves. doctor is the thing they cannot do: one view of every
 * agent on the machine, which caddis each one actually has, whether that
 * matches what this CLI ships, and the exact command that fixes each gap.
 */
import os from 'node:os';
import process from 'node:process';
import type { AgentAdapter } from '../agents/types.js';
import { detail, heading, hint, item, line, color } from '../util/log.js';
import { bundleManifest, packageInfo } from '../util/pkg.js';
import type { AgentReport, DriftState, Report } from './report.js';
import { gather } from './report.js';

export interface DoctorOptions {
  adapters: AgentAdapter[];
  /** Exit non-zero when anything needs attention. For CI. */
  strict?: boolean;
  json?: boolean;
}

const REQUIRED_NODE_MAJOR = 20;
const REQUIRED_NODE_MINOR = 19;

interface Problem {
  text: string;
  fix?: string;
  /**
   * `note` items are worth printing but are not defects — a detected Codex is
   * information, not something the user did wrong. Only `problem` items count
   * toward the --strict exit code.
   */
  kind: 'problem' | 'note';
}

export async function doctor(options: DoctorOptions): Promise<number> {
  const report = await gather(options.adapters);
  const findings: Problem[] = [];

  if (options.json) {
    line(JSON.stringify(toJson(report), null, 2));
    return 0;
  }

  renderEnvironment(report, findings);
  renderAgents(report, findings);
  renderSummary(report, findings);

  return options.strict && findings.some((f) => f.kind === 'problem') ? 1 : 0;
}

function renderEnvironment(report: Report, problems: Problem[]): void {
  heading('Environment');

  const [major = 0, minor = 0] = process.versions.node.split('.').map(Number);
  const nodeOk = major > REQUIRED_NODE_MAJOR || (major === REQUIRED_NODE_MAJOR && minor >= REQUIRED_NODE_MINOR);
  item(nodeOk ? 'ok' : 'fail', `node ${process.versions.node}`);
  if (!nodeOk) {
    detail(`caddis requires node >= ${REQUIRED_NODE_MAJOR}.${REQUIRED_NODE_MINOR}`);
    problems.push({ kind: 'problem', text: `node ${process.versions.node} is below the required ${REQUIRED_NODE_MAJOR}.${REQUIRED_NODE_MINOR}`, fix: 'upgrade node' });
  }

  item('info', `platform ${process.platform} ${process.arch} (${os.release()})`);
  item('info', `@caddis/cli ${report.cliVersion}`);

  const manifest = bundleManifest();
  if (report.poolVersion === 'unknown') {
    item('fail', 'shipped pool version unknown');
    detail(`no readable bundles/ in ${packageInfo().root}`);
    problems.push({ kind: 'problem', text: 'this package has no shipped bundles', fix: 'reinstall: npm i -g @caddis/cli' });
  } else {
    item('ok', `shipped pool ${color.bold(report.poolVersion)}`);
    for (const [name, version] of Object.entries(manifest.bundles)) {
      detail(`bundle ${name} @ ${version}`);
    }
    if (report.extrasVersion) {
      detail(`caddis-extras ships at ${report.extrasVersion} (versioned independently of the pool)`);
    }
  }
}

function renderAgents(report: Report, problems: Problem[]): void {
  heading('Agents');

  for (const entry of report.agents) {
    const { adapter, detection, status } = entry;
    item(markFor(entry.drift), `${color.bold(adapter.name)} — ${describe(entry, report.poolVersion)}`);

    if (detection.path) detail(detection.path);
    if (detection.agentVersion) detail(`agent version ${detection.agentVersion}`);
    if (status.source) detail(`read from ${status.source}`);
    if (status.note) detail(status.note);
    if (detection.note && detection.note !== status.note) detail(detection.note);
    if (entry.extrasDrift) detail(describeExtras(entry, report.extrasVersion));

    const problem = problemFor(entry, report.poolVersion);
    if (problem) {
      problems.push(problem);
      if (problem.fix) hint(color.bold(problem.fix));
    }

    const extrasProblem = extrasProblemFor(entry, report.extrasVersion);
    if (extrasProblem) {
      problems.push(extrasProblem);
      if (extrasProblem.fix) hint(color.bold(extrasProblem.fix));
    }
  }
}

function renderSummary(report: Report, findings: Problem[]): void {
  heading('Summary');

  const counts = report.agents.reduce<Record<DriftState, number>>(
    (acc, entry) => ({ ...acc, [entry.drift]: (acc[entry.drift] ?? 0) + 1 }),
    {} as Record<DriftState, number>,
  );
  const present = report.agents.filter((entry) => entry.detection.present).length;
  line(
    `  ${present} of ${report.agents.length} agents detected · ` +
      `${counts.current ?? 0} current · ${counts.stale ?? 0} stale · ${counts.missing ?? 0} not installed`,
  );

  const problems = findings.filter((f) => f.kind === 'problem');
  const notes = findings.filter((f) => f.kind === 'note');

  if (problems.length === 0) {
    line(`\n  ${color.green('Everything caddis manages is current.')}`);
  } else {
    line(`\n  ${color.yellow(`${problems.length} thing${problems.length === 1 ? '' : 's'} to fix:`)}`);
    for (const problem of problems) {
      line(`    ${color.dim('•')} ${problem.text}`);
      if (problem.fix) line(`      ${color.cyan(problem.fix)}`);
    }
  }

  if (notes.length > 0) {
    line(`\n  ${color.dim('For your information:')}`);
    for (const note of notes) line(`    ${color.dim(`• ${note.text}`)}`);
  }
}

function markFor(drift: DriftState): 'ok' | 'warn' | 'fail' | 'skip' | 'info' {
  switch (drift) {
    case 'current':
      return 'ok';
    case 'stale':
    case 'missing':
    case 'unknown':
      return 'warn';
    case 'unsupported':
      return 'info';
    case 'absent':
      return 'skip';
  }
}

function describe(entry: AgentReport, poolVersion: string): string {
  switch (entry.drift) {
    case 'current':
      return `caddis ${entry.status.version} ${color.dim('(current)')}`;
    case 'stale':
      return `caddis ${color.yellow(entry.status.version ?? '?')} ${color.dim('→')} ${color.bold(poolVersion)} available`;
    case 'unknown':
      return 'caddis installed, version not reported';
    case 'missing':
      return color.yellow('caddis not installed');
    case 'unsupported':
      return color.dim('detected — not yet supported (v0.2)');
    case 'absent':
      return color.dim('not installed on this machine');
  }
}

function describeExtras(entry: AgentReport, extrasVersion: string | undefined): string {
  const installed = entry.status.extras?.version;
  switch (entry.extrasDrift) {
    case 'current':
      return `caddis-extras ${installed} (current)`;
    case 'stale':
      return `caddis-extras ${installed} → ${extrasVersion ?? '?'} available`;
    case 'unknown':
      return 'caddis-extras installed, version not reported';
    case 'missing':
      return `caddis-extras not installed (optional — add with --extras)`;
    default:
      return 'caddis-extras n/a';
  }
}

/**
 * Extras problems are reported ONLY when it is installed and behind. Extras is
 * opt-in, so "not installed" is a normal state, not a defect — flagging it
 * would make doctor nag every user who deliberately doesn't want it.
 */
function extrasProblemFor(entry: AgentReport, extrasVersion: string | undefined): Problem | null {
  if (entry.extrasDrift === 'stale') {
    return {
      kind: 'problem',
      text: `${entry.adapter.name} has caddis-extras ${entry.status.extras?.version}, this CLI ships ${extrasVersion}`,
      fix: `caddis update --agent ${entry.adapter.id}`,
    };
  }
  if (entry.extrasDrift === 'unknown') {
    return {
      kind: 'problem',
      text: `${entry.adapter.name} has caddis-extras but will not report a version`,
      fix: `caddis update --agent ${entry.adapter.id} --extras`,
    };
  }
  return null;
}

function problemFor(entry: AgentReport, poolVersion: string): Problem | null {
  const scope = `--agent ${entry.adapter.id}`;
  switch (entry.drift) {
    case 'stale':
      return {
        kind: 'problem',
        text: `${entry.adapter.name} has caddis ${entry.status.version}, this CLI ships ${poolVersion}`,
        fix: `caddis update ${scope}`,
      };
    case 'missing':
      return {
        kind: 'problem',
        text: `${entry.adapter.name} is installed but has no caddis`,
        fix: `caddis init ${scope}`,
      };
    case 'unknown':
      return {
        kind: 'problem',
        text: `${entry.adapter.name} has caddis but will not report a version — drift cannot be checked`,
        fix: `caddis update ${scope}`,
      };
    case 'unsupported':
      return {
        kind: 'note',
        text: `${entry.adapter.name} is on this machine but v0.1 cannot drive it — ${entry.adapter.summary}`,
      };
    default:
      // A disabled-but-current plugin is worth saying out loud: the version
      // matches, so nothing else here would flag it, yet caddis is inert.
      if (entry.status.disabled) {
        return {
          kind: 'problem',
          text: `${entry.adapter.name} has caddis ${entry.status.version} but it is DISABLED`,
          fix: entry.adapter.id === 'claude' ? 'claude plugin enable caddis@caddis' : undefined,
        };
      }
      return null;
  }
}

function toJson(report: Report) {
  return {
    cliVersion: report.cliVersion,
    poolVersion: report.poolVersion,
    extrasVersion: report.extrasVersion ?? null,
    node: process.versions.node,
    platform: `${process.platform}-${process.arch}`,
    agents: report.agents.map((entry) => ({
      id: entry.adapter.id,
      name: entry.adapter.name,
      supported: entry.adapter.supported,
      present: entry.detection.present,
      path: entry.detection.path ?? null,
      agentVersion: entry.detection.agentVersion ?? null,
      caddisVersion: entry.status.version ?? null,
      disabled: entry.status.disabled ?? false,
      drift: entry.drift,
      extrasVersion: entry.status.extras?.version ?? null,
      extrasDrift: entry.extrasDrift ?? null,
      note: entry.status.note ?? entry.detection.note ?? null,
    })),
  };
}
