import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { Guide } from '../../ui/src/guide/Guide';
import { guideSections, guideStatus, runtimesOf } from '../../ui/src/guide/model';

// H5 gate (G9): the page counts equal the counts of the real pool. This runs the real script, as the hub does.
const script = fileURLToPath(new URL('../../../scripts/build_reference.py', import.meta.url));

// The published mirror has no scripts/ folder: the gate then runs only in the source repo.
const inSource = existsSync(script);

function realGuide(): unknown {
  if (!inSource) return undefined;
  for (const py of ['python3', 'python']) {
    const r = spawnSync(py, [script, '--json'], { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024, timeout: 120_000 });
    if (r.status === 0 && r.stdout) return JSON.parse(r.stdout);
  }
  return undefined;
}

const guide = realGuide();
// In CI a missing guide is a failure, never a skip.
const inCi = Boolean(process.env.CI);

describe.skipIf(!inSource || (guide === undefined && !inCi))('guide counts equal the pool (real build_reference.py --json)', () => {
  it('the guide could be produced', () => {
    expect(guide, 'python build_reference.py --json produced no guide').toBeDefined();
  });

  it('the page sections equal the reported counts and the list lengths', () => {
    const status = guideStatus(guide);
    expect(status.kind).toBe('ok');
    if (status.kind !== 'ok') return;
    const g = status.guide;
    const sections = guideSections(g);
    expect(sections.commands).toBe(g.counts!.commands);
    expect(sections.agents).toBe(g.counts!.agents);
    expect(sections.skills).toBe(g.counts!.skills);
    expect(sections.hooks).toBe(g.counts!.hooks);
    expect(sections.commands).toBeGreaterThan(0);
    expect(g.skills.filter((s) => s.core)).toHaveLength(g.counts!.core!);
    expect(runtimesOf(g).length).toBe(sections.runtimes);
    expect(sections.runtimes).toBeGreaterThan(0);
  });

  it('the rendered page shows each count equal to the pool counts', () => {
    const status = guideStatus(guide);
    if (status.kind !== 'ok') throw new Error('guide not ok');
    const counts = status.guide.counts!;
    const html = renderToStaticMarkup(createElement(Guide, { guide, versions: { hub: '0.0.0', pool: null, plugin: null }, tab: 'details' }));
    const shown = (id: string): number => Number(new RegExp(`data-testid="guide-count-${id}">(\\d+)<`).exec(html)?.[1]);
    expect(shown('commands')).toBe(counts.commands);
    expect(shown('agents')).toBe(counts.agents);
    expect(shown('skills')).toBe(counts.skills);
    expect(shown('hooks')).toBe(counts.hooks);
    expect(shown('runtimes')).toBe(runtimesOf(status.guide).length);
    expect(html.match(/data-testid="guide-entry"/g)).toHaveLength(
      counts.commands! + counts.agents! + counts.skills! + counts.hooks! + runtimesOf(status.guide).length,
    );
  });
});
