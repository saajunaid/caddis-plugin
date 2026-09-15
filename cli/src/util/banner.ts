/**
 * Caddis ASCII art banner and brand header.
 *
 * Renders the Pixel C mark alongside the ANSI Shadow CADDIS wordmark.
 */
import pc from 'picocolors';
import { theme } from './theme.js';

export interface BannerOptions {
  cliVersion?: string;
  poolVersion?: string;
  subtitle?: string;
}

const MARK = [
  '    ▄██████▄     ',
  '  ▄██████████▄   ',
  ' █████▀   ▀████  ',
  ' ████            ',
  ' █████▄   ▄████  ',
  '  ▀██████████▀   ',
  '    ▀██████▀     ',
];

const WORDMARK = [
  ' ██████╗ █████╗ ██████╗ ██████╗ ██╗███████╗',
  '██╔════╝██╔══██╗██╔══██╗██╔══██╗██║██╔════╝',
  '██║     ███████║██║  ██║██║  ██║██║███████╗',
  '██║     ██╔══██║██║  ██║██║  ██║██║╚════██║',
  '╚██████╗██║  ██║██████╔╝██████╔╝██║███████║',
  ' ╚═════╝╚═╝  ╚═╝╚═════╝ ╚═════╝ ╚═╝╚══════╝',
  '                                           ',
];

export function renderBanner(options: BannerOptions = {}): void {
  process.stdout.write('\n');
  for (let i = 0; i < 7; i++) {
    const m = pc.bold(theme.mint(MARK[i]!));
    const w =
      i < 2
        ? pc.bold(theme.mint(WORDMARK[i]!))
        : i < 4
          ? pc.bold(theme.violet(WORDMARK[i]!))
          : pc.bold(theme.magenta(WORDMARK[i]!));
    process.stdout.write(` ${m}  ${w}\n`);
  }

  const sub = options.subtitle ?? 'Agent-Agnostic Developer Harness · Multi-Model Coding Core';
  process.stdout.write(`   ${pc.dim(sub)}\n`);

  if (options.cliVersion || options.poolVersion) {
    const parts: string[] = [];
    if (options.cliVersion) parts.push(`cli ${theme.mint(options.cliVersion)}`);
    if (options.poolVersion) parts.push(`pool ${theme.violet(pc.bold(options.poolVersion))}`);
    process.stdout.write(`   ${pc.dim(parts.join(' · '))}\n`);
  }
  process.stdout.write('\n');
}
