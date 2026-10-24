/**
 * Caddis ASCII art banner and brand header.
 *
 * Renders the Pixel C mark alongside the ANSI Shadow CADDIS wordmark.
 */
import pc from 'picocolors';
import { hex } from './theme.js';
import { PALETTE } from '../../ui/src/brand/palette.js';

/** Banner colours. Every one comes from the brand palette. */
export const BANNER_COLORS = {
  mark: PALETTE.green,
  wordmarkTop: PALETTE.cyan,
  wordmarkMid: PALETTE.green,
  wordmarkBottom: PALETTE.violet,
  cliVersion: PALETTE.cyan,
  poolVersion: PALETTE.violet,
} as const;

const color = {
  mark: hex(BANNER_COLORS.mark),
  top: hex(BANNER_COLORS.wordmarkTop),
  mid: hex(BANNER_COLORS.wordmarkMid),
  bottom: hex(BANNER_COLORS.wordmarkBottom),
  cli: hex(BANNER_COLORS.cliVersion),
  pool: hex(BANNER_COLORS.poolVersion),
};

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
    const m = pc.bold(color.mark(MARK[i]!));
    const w =
      i < 2
        ? pc.bold(color.top(WORDMARK[i]!))
        : i < 4
          ? pc.bold(color.mid(WORDMARK[i]!))
          : pc.bold(color.bottom(WORDMARK[i]!));
    process.stdout.write(` ${m}  ${w}\n`);
  }

  const sub = options.subtitle ?? 'Agent-Agnostic Developer Harness · Multi-Model Coding Core';
  process.stdout.write(`   ${pc.dim(sub)}\n`);

  if (options.cliVersion || options.poolVersion) {
    const parts: string[] = [];
    if (options.cliVersion) parts.push(`cli ${color.cli(options.cliVersion)}`);
    if (options.poolVersion) parts.push(`pool ${color.pool(pc.bold(options.poolVersion))}`);
    process.stdout.write(`   ${pc.dim(parts.join(' · '))}\n`);
  }
  process.stdout.write('\n');
}
