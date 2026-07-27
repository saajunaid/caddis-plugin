import { describe, expect, it } from 'vitest';

import { selectAdapters, AGENT_IDS } from '../src/agents/index.js';
import { formatCommand, run } from '../src/util/exec.js';
import { renderTable, visibleWidth } from '../src/util/table.js';

describe('selectAdapters (--agent)', () => {
  it('returns every adapter when unfiltered', () => {
    expect(selectAdapters().map((a) => a.id)).toEqual(AGENT_IDS);
    expect(selectAdapters([]).map((a) => a.id)).toEqual(AGENT_IDS);
  });

  it('filters to the requested agents, preserving registration order', () => {
    expect(selectAdapters(['agy', 'claude']).map((a) => a.id)).toEqual(['claude', 'agy']);
  });

  it('accepts a comma-separated list and is case-insensitive', () => {
    expect(selectAdapters(['Claude,AGY']).map((a) => a.id)).toEqual(['claude', 'agy']);
  });

  it('throws on a typo rather than silently doing nothing', () => {
    expect(() => selectAdapters(['clade'])).toThrow(/unknown agent: clade/);
  });

  it('lists the valid ids in the error, so the fix is in the message', () => {
    expect(() => selectAdapters(['nope'])).toThrow(/claude, agy, codex, copilot/);
  });
});

describe('run()', () => {
  it('never throws when the binary does not exist', async () => {
    const result = await run('caddis-definitely-not-a-real-binary-xyz', ['--version']);
    expect(result.ok).toBe(false);
    expect(result.failure ?? result.stderr).toBeTruthy();
  });

  it('captures a real process\'s stdout and exit code', async () => {
    const result = await run(process.execPath, ['-e', 'process.stdout.write("hello")']);
    expect(result).toMatchObject({ ok: true, code: 0, stdout: 'hello' });
  });

  it('reports a non-zero exit as not-ok without throwing', async () => {
    const result = await run(process.execPath, ['-e', 'process.exit(3)']);
    expect(result).toMatchObject({ ok: false, code: 3 });
  });
});

describe('formatCommand', () => {
  it('renders a command the way a user would retype it', () => {
    expect(formatCommand('claude', ['plugin', 'update', 'caddis@caddis'])).toBe('claude plugin update caddis@caddis');
  });

  it('quotes arguments containing spaces (Windows install paths)', () => {
    expect(formatCommand('agy', ['plugin', 'install', 'C:\\Program Files\\x'])).toBe(
      'agy plugin install "C:\\Program Files\\x"',
    );
  });
});

describe('renderTable', () => {
  it('aligns columns using VISIBLE width, ignoring colour codes', () => {
    const green = '\u001B[32myes\u001B[39m';
    expect(visibleWidth(green)).toBe(3);
    const rendered = renderTable(['A', 'B'], [[green, 'x'], ['no', 'y']]);
    const [, , row1, row2] = rendered.split('\n');
    // Both data rows must place column B at the same offset.
    // eslint-disable-next-line no-control-regex
    const strip = (s: string) => s.replace(/\u001B\[[0-9;]*m/g, '');
    expect(strip(row1 ?? '').indexOf('x')).toBe(strip(row2 ?? '').indexOf('y'));
  });

  it('widens a column to its longest cell', () => {
    const rendered = renderTable(['AGENT'], [['GitHub Copilot']]);
    expect(rendered).toContain('GitHub Copilot');
  });
});
