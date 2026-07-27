/** Minimal fixed-width table. Colour codes must not count toward width. */
import pc from 'picocolors';

// eslint-disable-next-line no-control-regex
const ANSI = /\[[0-9;]*m/g;

export function visibleWidth(text: string): number {
  return text.replace(ANSI, '').length;
}

function pad(text: string, width: number): string {
  return text + ' '.repeat(Math.max(0, width - visibleWidth(text)));
}

export function renderTable(headers: string[], rows: string[][]): string {
  const widths = headers.map((header, i) =>
    Math.max(visibleWidth(header), ...rows.map((row) => visibleWidth(row[i] ?? ''))),
  );
  const out: string[] = [];
  out.push(`  ${headers.map((h, i) => pad(pc.bold(h), widths[i] ?? 0)).join('  ')}`.trimEnd());
  out.push(`  ${widths.map((w) => pc.dim('─'.repeat(w))).join('  ')}`);
  for (const row of rows) {
    out.push(`  ${row.map((cell, i) => pad(cell ?? '', widths[i] ?? 0)).join('  ')}`.trimEnd());
  }
  return out.join('\n');
}
