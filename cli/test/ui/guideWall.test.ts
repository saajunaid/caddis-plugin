import { readFileSync } from 'node:fs';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { Guide } from '../../ui/src/guide/Guide';
import { anchorId, type Guide as GuideData } from '../../ui/src/guide/model';
import { wallBlurb, wallModel } from '../../ui/src/guide/wall';

const base = JSON.parse(
  readFileSync(new URL('../fixtures/hub-state/guide.json', import.meta.url), 'utf8')
).guide as GuideData;
const versions = { hub: '0.0.1', pool: null, plugin: null };

const cmd = (name: string, stage: string, daily = false, hint = '', noArgs = true, description = `Does ${name}. More text.`) => ({
  name,
  description,
  hint,
  steps: [],
  scripts: [],
  noArgs,
  stage,
  daily,
});

const fixture: GuideData = {
  ...base,
  version: '1.3.176',
  commands: [
    cmd('setup-project-ai', 'setup'),
    cmd('prd', 'plan'),
    cmd('feature-plan', 'plan', true, '<feature>', false),
    cmd('implement', 'build', true, '<plan>', false),
    cmd('cross-review', 'review'),
    cmd('ship-pr', 'ship', true),
    cmd('ship-merge', 'ship', true),
    cmd('handoff', 'continuity', true),
    cmd('decide', 'knowledge'),
    cmd('version', 'ungrouped'),
  ],
  agents: [
    { name: 'tester', description: 'Runs tests. Extra.', tools: ['Bash'], model: 'sonnet', writes: true },
    { name: 'debug', description: 'Finds root cause.', tools: ['Read'], model: 'sonnet', writes: false },
  ],
};

describe('wallBlurb', () => {
  it('stops at the first clause: dash, full stop, semicolon or bracket', () => {
    expect(wallBlurb('Headless plan executor — implement an approved plan')).toBe('Headless plan executor');
    expect(wallBlurb('Park the task. Switch to another.')).toBe('Park the task');
    expect(wallBlurb('Record a decision; then link it')).toBe('Record a decision');
    expect(wallBlurb('Install the harness (once per repo)')).toBe('Install the harness');
  });

  it('drops the "Use this agent to" lead-in and capitalises what is left', () => {
    expect(wallBlurb('Use this agent to review a diff or set of changes for correctness')).toBe('Review a diff or set of changes for…');
    expect(wallBlurb('Use this agent after a completed implementation')).toBe('A completed implementation');
    expect(wallBlurb('Use this agent when a test fails')).toBe('A test fails');
    expect(wallBlurb('Use this agent periodically (every few weeks, or when it is long) to prune the rules')).toBe('Prune the rules');
  });

  it('keeps a hyphenated word whole', () => {
    expect(wallBlurb('Create a TDD-structured plan')).toBe('Create a TDD-structured plan');
  });

  it('cuts a long clause at a word boundary, at most 44 characters plus an ellipsis', () => {
    const out = wallBlurb('Create a phased TDD-structured implementation plan that acts as the durable spine');
    expect(out.endsWith('…')).toBe(true);
    expect(out.length).toBeLessThanOrEqual(45);
    expect(out).toBe('Create a phased TDD-structured…');
  });

  it('returns an empty string for an empty description', () => {
    expect(wallBlurb('')).toBe('');
  });
});

describe('wallModel', () => {
  it('orders cards plan, build, review, ship, continuity, knowledge, setup, other, agents', () => {
    const m = wallModel(fixture);
    expect(m.cards.map((c) => c.id)).toEqual([
      'plan', 'build', 'review', 'ship', 'continuity', 'knowledge', 'setup', 'other', 'agents',
    ]);
    expect(m.cards.find((c) => c.id === 'other')!.rows.map((r) => r.name)).toEqual(['version']);
  });

  it('omits a card that has no rows', () => {
    const m = wallModel({ ...fixture, commands: fixture.commands.filter((c) => c.stage !== 'review'), agents: [] });
    expect(m.cards.map((c) => c.id)).toEqual(['plan', 'build', 'ship', 'continuity', 'knowledge', 'setup', 'other']);
  });

  it('sorts rows daily first, then by name', () => {
    const plan = wallModel(fixture).cards.find((c) => c.id === 'plan')!;
    expect(plan.rows.map((r) => r.name)).toEqual(['feature-plan', 'prd']);
    expect(plan.rows.map((r) => r.daily)).toEqual([true, false]);
  });

  it('builds the loop strip from daily commands in plan, build, review, ship order', () => {
    expect(wallModel(fixture).loop.map((r) => r.name)).toEqual(['feature-plan', 'implement', 'ship-merge', 'ship-pr']);
  });

  it('gives a short blurb and the details anchor', () => {
    const row = wallModel(fixture).cards.find((c) => c.id === 'plan')!.rows[0]!;
    expect(row.blurb).toBe('Does feature-plan');
    expect(row.anchor).toBe(anchorId('command', 'feature-plan'));
  });

  it('lists every agent, sorted by name, with kind agent', () => {
    const agents = wallModel(fixture).cards.find((c) => c.id === 'agents')!;
    expect(agents.rows.map((r) => r.name)).toEqual(['debug', 'tester']);
    expect(agents.rows[0]!.anchor).toBe(anchorId('agent', 'debug'));
  });

  it('counts and version come from the data, so a new command shows up with no code change', () => {
    const grown: GuideData = { ...fixture, commands: [...fixture.commands, cmd('brand-new', 'build')] };
    const m = wallModel(grown);
    expect(m.counts.commands).toBe(fixture.commands.length + 1);
    expect(m.version).toBe('1.3.176');
    expect(m.cards.find((c) => c.id === 'build')!.rows.map((r) => r.name)).toContain('brand-new');
  });
});

describe('Wall poster tab', () => {
  const render = (guide: unknown): string =>
    renderToStaticMarkup(createElement(Guide, { guide, versions, tab: 'wall', item: null }));

  it('renders the sheet with a command per row and the stats from the data', () => {
    const html = render(fixture);
    expect(html).toContain('data-testid="guide-wall"');
    for (const c of fixture.commands) expect(html).toContain(`/${c.name}`);
    for (const a of fixture.agents) expect(html).toContain(a.name);
    expect(html).toContain('1.3.176');
    expect(html).toMatch(new RegExp(`<b>${fixture.commands.length}</b>\\s*commands`));
  });

  it('marks the wall tab selected and links it at #/guide/wall', () => {
    const html = render(fixture);
    expect(html).toMatch(/href="#\/guide\/wall"[^>]*aria-selected="true"/);
    expect(html).toMatch(/href="#\/guide"[^>]*aria-selected="false"/);
  });

  it('shows the missing state, not a crash, when the guide has no data', () => {
    const html = render(null);
    expect(html).toContain('data-testid="guide-state"');
    expect(html).not.toContain('data-testid="guide-wall"');
  });
});
