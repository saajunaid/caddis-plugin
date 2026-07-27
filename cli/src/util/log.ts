/** Terminal output primitives. picocolors auto-disables on non-TTY / NO_COLOR. */
import pc from 'picocolors';

export const OK = pc.green('OK');
export const WARN = pc.yellow('!!');
export const FAIL = pc.red('XX');
export const SKIP = pc.dim('--');

export type Mark = 'ok' | 'warn' | 'fail' | 'skip' | 'info';

const MARKS: Record<Mark, string> = {
  ok: pc.green('✓'),
  warn: pc.yellow('▲'),
  fail: pc.red('✗'),
  skip: pc.dim('·'),
  info: pc.cyan('•'),
};

export function mark(kind: Mark): string {
  return MARKS[kind];
}

export function heading(text: string): void {
  process.stdout.write(`\n${pc.bold(text)}\n`);
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
  line(`      ${pc.cyan('→')} ${text}`);
}

export function errorLine(text: string): void {
  process.stderr.write(`${pc.red('error')} ${text}\n`);
}

export const color = pc;
