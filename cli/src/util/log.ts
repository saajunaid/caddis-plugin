import pc from 'picocolors';
import { theme } from './theme.js';

export const OK = theme.mint('OK');
export const WARN = theme.amber('!!');
export const FAIL = theme.coral('XX');
export const SKIP = pc.dim('--');

export type Mark = 'ok' | 'warn' | 'fail' | 'skip' | 'info';

const MARKS: Record<Mark, string> = {
  ok: theme.mint('✓'),
  warn: theme.amber('▲'),
  fail: theme.coral('✗'),
  skip: pc.dim('·'),
  info: theme.sky('•'),
};

export function mark(kind: Mark): string {
  return MARKS[kind];
}

export { renderBanner } from './banner.js';
export type { BannerOptions } from './banner.js';
export { theme } from './theme.js';

export function heading(text: string): void {
  process.stdout.write(`\n  ${pc.bold(theme.mint('◆'))} ${pc.bold(text)}\n`);
}

export function line(text = ''): void {
  process.stdout.write(`${text}\n`);
}

export function item(kind: Mark, text: string): void {
  line(`  ${mark(kind)} ${text}`);
}

export function detail(text: string): void {
  line(`      ${pc.dim(text)}`);
}

export function hint(text: string): void {
  line(`      ${theme.sky('→')} ${text}`);
}

export function errorLine(text: string): void {
  process.stderr.write(`${theme.coral('error')} ${text}\n`);
}

export const color = Object.assign(pc, {
  mint: theme.mint,
  violet: theme.violet,
  magenta: theme.magenta,
  sky: theme.sky,
  amber: theme.amber,
  coral: theme.coral,
});
