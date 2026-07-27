/**
 * @caddis/cli — the cross-agent front door for the caddis dev harness.
 *
 * Commands lazy-import their implementation so `caddis --help` and a cold
 * `npx` run pay for the parser only.
 */
import { Command, Option } from 'commander';
import { AGENT_IDS, selectAdapters } from './agents/index.js';
import type { AgentAdapter } from './agents/index.js';
import { color, errorLine } from './util/log.js';
import { packageInfo } from './util/pkg.js';

interface GlobalFlags {
  dryRun?: boolean;
  yes?: boolean;
  agent?: string[];
  updateNotifier?: boolean;
}

const pkg = packageInfo();
const program = new Command();

/**
 * The global flags are registered on the root AND on every subcommand.
 * Commander scopes options to the command they are declared on, so declaring
 * them only on the root makes `caddis update --dry-run` — the order everyone
 * actually types — an "unknown option" error. Declaring them in both places
 * and merging accepts either position.
 */
function withGlobalFlags(command: Command): Command {
  return command
    .option('--dry-run', 'show what would run; change nothing')
    .option('-y, --yes', 'assume yes; never prompt (CI)')
    .addOption(new Option('-a, --agent <name...>', `limit to specific agents (${AGENT_IDS.join(', ')})`))
    .option('--no-update-notifier', 'do not check npm for a newer @caddis/cli');
}

/** Subcommand flags win where set; the root supplies the rest. */
function mergeFlags(local: GlobalFlags): Required<Pick<GlobalFlags, 'dryRun' | 'yes'>> & GlobalFlags {
  const root = program.opts<GlobalFlags>();
  return {
    dryRun: local.dryRun === true || root.dryRun === true,
    yes: local.yes === true || root.yes === true,
    agent: local.agent ?? root.agent,
    updateNotifier: local.updateNotifier !== false && root.updateNotifier !== false,
  };
}

withGlobalFlags(program)
  .name('caddis')
  .description(
    'Install, update and diagnose the caddis dev harness across every coding agent you use.\n' +
      "caddis drives each agent's OWN installer — it never replaces them.",
  )
  .version(pkg.version, '-v, --version', 'print the CLI version')
  .showHelpAfterError();

withGlobalFlags(program.command('init'))
  .description('first run: detect your agents, confirm, install caddis into each')
  .option('--extras', 'also install the optional caddis-extras long-tail skills', false)
  .action(async (options: GlobalFlags & { extras?: boolean }) => {
    const flags = mergeFlags(options);
    const { init } = await import('./commands/init.js');
    finish(
      await init({
        adapters: resolveAdapters(flags),
        dryRun: flags.dryRun,
        yes: flags.yes,
        extras: options.extras === true,
      }),
    );
  });

withGlobalFlags(program.command('update'))
  .description('update every detected agent to the caddis version shipped in this CLI')
  .option('-f, --force', 're-drive agents that already report the shipped version', false)
  .option('--extras', 'also install the optional caddis-extras long-tail skills', false)
  .action(async (options: GlobalFlags & { force?: boolean; extras?: boolean }) => {
    const flags = mergeFlags(options);
    const { update } = await import('./commands/update.js');
    finish(
      await update({
        adapters: resolveAdapters(flags),
        dryRun: flags.dryRun,
        yes: flags.yes,
        force: options.force === true,
        extras: options.extras === true,
      }),
    );
  });

withGlobalFlags(program.command('doctor'))
  .description('full health report: every agent, its caddis version, drift, and the fix')
  .option('--strict', 'exit 1 when anything needs attention (CI)', false)
  .option('--json', 'machine-readable output', false)
  .action(async (options: GlobalFlags & { strict?: boolean; json?: boolean }) => {
    const flags = mergeFlags(options);
    const { doctor } = await import('./commands/doctor.js');
    finish(await doctor({ adapters: resolveAdapters(flags), strict: options.strict, json: options.json }));
  });

withGlobalFlags(program.command('status'))
  .description('compact table: cli version, pool version, per-agent version, drift')
  .option('--json', 'machine-readable output', false)
  .action(async (options: GlobalFlags & { json?: boolean }) => {
    const flags = mergeFlags(options);
    const { status } = await import('./commands/status.js');
    finish(await status({ adapters: resolveAdapters(flags), json: options.json }));
  });

program.addHelpText(
  'after',
  `
${color.bold('Examples')}
  $ npx @caddis/cli init            detect your agents and install caddis into each
  $ caddis doctor                   what is installed where, and what to do about it
  $ caddis update --dry-run         preview the exact vendor commands
  $ caddis update --agent agy       update just one agent
  $ caddis init --extras            add the optional caddis-extras skill library
  $ caddis doctor --strict          exit non-zero on drift (CI)

${color.bold('Supported agents')}
  claude    Claude Code       via its plugin marketplace
  agy       Antigravity       via the caddis bundle shipped in this package
                              (--extras adds caddis-extras; already-installed
                               extras is kept current automatically)
  codex     Codex             detected only — config merge lands in v0.2
  copilot   GitHub Copilot    detected only — config merge lands in v0.2
`,
);

function resolveAdapters(flags: GlobalFlags): AgentAdapter[] {
  try {
    return selectAdapters(flags.agent);
  } catch (error) {
    errorLine(error instanceof Error ? error.message : String(error));
    process.exit(2);
  }
}

function finish(code: number): void {
  process.exitCode = code;
}

/**
 * Nudge when a newer CLI exists. Fails silently and never blocks: a broken
 * registry lookup must not stop `caddis doctor` from working offline.
 */
async function maybeNotify(enabled: boolean): Promise<void> {
  if (!enabled || process.env.NO_UPDATE_NOTIFIER || process.env.CI) return;
  try {
    const { default: updateNotifier } = await import('update-notifier');
    updateNotifier({
      pkg: { name: pkg.name, version: pkg.version },
      updateCheckInterval: 1000 * 60 * 60 * 24,
    }).notify({ isGlobal: true, defer: true });
  } catch {
    /* never block on the notifier */
  }
}

async function main(): Promise<void> {
  // Bare `caddis` is the discovery path — show status, not a usage error.
  if (process.argv.slice(2).length === 0) {
    const { status } = await import('./commands/status.js');
    finish(await status({ adapters: selectAdapters() }));
    await maybeNotify(true);
    return;
  }

  await program.parseAsync(process.argv);
  await maybeNotify(program.opts<GlobalFlags>().updateNotifier !== false);
}

main().catch((error: unknown) => {
  errorLine(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
