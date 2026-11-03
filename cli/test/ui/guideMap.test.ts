import { readFileSync } from 'node:fs';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { Guide } from '../../ui/src/guide/Guide';
import { handlerName, mapMatch, mapMatchCount, mapModel } from '../../ui/src/guide/map';
import { anchorId, type Guide as GuideData } from '../../ui/src/guide/model';

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
const skill = (name: string, category: string, core = false) => ({ name, category, description: `The ${name} skill.`, core });
const hook = (event: string, matcher: string, handler: string) => ({ event, matcher, handler });

const fixture: GuideData = {
  ...base,
  version: '1.3.176',
  generated: '2026-11-03',
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
    { name: 'debug', description: 'Finds root cause.', tools: ['Read'], model: 'opus', writes: false },
  ],
  skills: [
    skill('react-dev', 'frontend'),
    skill('css-architecture', 'frontend'),
    skill('frontend-design', 'frontend', true),
    skill('sql', 'data'),
    skill('python', 'backend'),
    skill('fastapi-dev', 'backend'),
    skill('loose', 'uncategorised'),
  ],
  hooks: [
    hook('SessionEnd', '(every)', 'hooks/session_end.py'),
    hook('Stop', '(every)', 'C:\\plugin\\hooks\\stop.py'),
    hook('PreToolUse', 'Bash|Edit', 'guard.py'),
    hook('PreToolUse', 'Write', 'guard.py'),
    hook('PreToolUse', 'Bash|Edit', 'audit.py'),
    hook('SessionStart', '(every)', 'warm_start.py'),
    hook('BrandNewEvent', '(every)', 'new.py'),
    hook('Another', '(every)', 'warm_start.py'),
  ],
  coverage: { commands: ['claude', 'codex-plugin'], skills: ['claude', 'antigravity-plugin'], agents: ['claude'] },
};

describe('mapModel', () => {
  it('takes version, date and counts from the data, counting distinct hook events and scripts', () => {
    const m = mapModel(fixture);
    expect(m.version).toBe('1.3.176');
    expect(m.generated).toBe('2026-11-03');
    expect(m.counts).toEqual({
      commands: 10,
      agents: 2,
      skills: 7,
      hookEvents: 6,
      hookScripts: 6,
      runtimes: 3,
    });
  });

  it('puts the four loop stages in plan, build, review, ship order, daily commands first then by name', () => {
    const m = mapModel(fixture);
    expect(m.loop.map((s) => s.id)).toEqual(['plan', 'build', 'review', 'ship']);
    expect(m.loop[0]).toMatchObject({ label: 'Plan', count: 2 });
    expect(m.loop[0]!.commands.map((c) => c.name)).toEqual(['feature-plan', 'prd']);
    expect(m.loop[3]!.commands.map((c) => c.name)).toEqual(['ship-merge', 'ship-pr']);
    expect(m.loop[0]!.commands[0]).toMatchObject({ daily: true, blurb: 'Does feature-plan', anchor: anchorId('command', 'feature-plan') });
  });

  it('puts continuity, knowledge, setup in the support lanes and an unknown stage in other', () => {
    const m = mapModel(fixture);
    expect(m.support.map((s) => s.id)).toEqual(['continuity', 'knowledge', 'setup', 'other']);
    expect(m.support[3]!.commands.map((c) => c.name)).toEqual(['version']);
    expect(m.support[3]!.count).toBe(1);
  });

  it('drops empty groups: no other lane, no review column, no empty sections', () => {
    const m = mapModel({
      ...fixture,
      commands: fixture.commands.filter((c) => c.stage !== 'ungrouped' && c.stage !== 'review'),
      agents: [],
      skills: [],
      hooks: [],
      coverage: { commands: [], skills: [], agents: [] },
    });
    expect(m.loop.map((s) => s.id)).toEqual(['plan', 'build', 'ship']);
    expect(m.support.map((s) => s.id)).toEqual(['continuity', 'knowledge', 'setup']);
    expect(m.agents).toEqual([]);
    expect(m.skills).toEqual([]);
    expect(m.hooks).toEqual([]);
    expect(m.runtimes).toEqual([]);
    expect(m.counts).toMatchObject({ agents: 0, skills: 0, hookEvents: 0, hookScripts: 0, runtimes: 0 });
  });

  it('orders hook events as a session runs them, with an unknown event after them, by name', () => {
    expect(mapModel(fixture).hooks.map((h) => h.event)).toEqual([
      'SessionStart',
      'PreToolUse',
      'Stop',
      'SessionEnd',
      'Another',
      'BrandNewEvent',
    ]);
  });

  it('gives each hook event its distinct script names (no folder) and matchers', () => {
    const pre = mapModel(fixture).hooks.find((h) => h.event === 'PreToolUse')!;
    expect(pre.handlers).toEqual(['audit.py', 'guard.py']);
    expect(pre.matchers).toEqual(['Bash|Edit', 'Write']);
    expect(pre.anchor).toBe(anchorId('hook', 'PreToolUse'));
    expect(mapModel(fixture).hooks.find((h) => h.event === 'Stop')!.handlers).toEqual(['stop.py']);
  });

  it('keeps the file name of a handler path with either slash', () => {
    expect(handlerName('hooks/a.py')).toBe('a.py');
    expect(handlerName('C:\\x\\b.py')).toBe('b.py');
    expect(handlerName('plain.py')).toBe('plain.py');
  });

  it('lists agents by name with model, writes flag, blurb and anchor', () => {
    const m = mapModel(fixture);
    expect(m.agents.map((a) => a.name)).toEqual(['debug', 'tester']);
    expect(m.agents[0]).toMatchObject({ model: 'opus', writes: false, blurb: 'Finds root cause', anchor: anchorId('agent', 'debug') });
    expect(m.agents[1]).toMatchObject({ model: 'sonnet', writes: true });
  });

  it('groups skills by family, biggest family first then by name, core skills first inside a family', () => {
    const m = mapModel(fixture);
    expect(m.skills.map((f) => [f.id, f.count])).toEqual([
      ['frontend', 3],
      ['backend', 2],
      ['data', 1],
      ['uncategorised', 1],
    ]);
    expect(m.skills[0]!.skills.map((s) => s.name)).toEqual(['frontend-design', 'css-architecture', 'react-dev']);
    expect(m.skills[0]!.skills[0]!.core).toBe(true);
    expect(m.skills[0]!.anchor).toBe(anchorId('skillCategory', 'frontend'));
    expect(m.skills[0]!.skills[0]!.anchor).toBe(anchorId('skill', 'frontend-design'));
  });

  it('lists the runtimes from the coverage lists, sorted by name, with the kinds each receives', () => {
    expect(mapModel(fixture).runtimes.map((r) => [r.name, r.kinds])).toEqual([
      ['antigravity-plugin', ['skills']],
      ['claude', ['commands', 'skills', 'agents']],
      ['codex-plugin', ['commands']],
    ]);
  });

  it('shows a new command, agent, skill and hook with no code change', () => {
    const grown: GuideData = {
      ...fixture,
      commands: [...fixture.commands, cmd('brand-new', 'build')],
      agents: [...fixture.agents, { name: 'newbie', description: 'New agent.', tools: [], model: 'haiku', writes: false }],
      skills: [...fixture.skills, skill('brand-new-skill', 'security')],
      hooks: [...fixture.hooks, hook('PostToolUse', 'Edit', 'post.py')],
    };
    const m = mapModel(grown);
    expect(m.loop.find((s) => s.id === 'build')!.commands.map((c) => c.name)).toContain('brand-new');
    expect(m.agents.map((a) => a.name)).toContain('newbie');
    expect(m.skills.map((f) => f.id)).toContain('security');
    expect(m.hooks.map((h) => h.event)).toContain('PostToolUse');
    expect(m.counts).toMatchObject({ commands: 11, agents: 3, skills: 8, hookEvents: 7, hookScripts: 7 });
  });
});

describe('mapMatch', () => {
  it('matches everything for an empty or blank query', () => {
    expect(mapMatch('', 'anything')).toBe(true);
    expect(mapMatch('   ', 'anything')).toBe(true);
  });

  it('ignores case and needs every word to appear', () => {
    expect(mapMatch('HAND', '/handoff end of session')).toBe(true);
    expect(mapMatch('end session', '/handoff end of session')).toBe(true);
    expect(mapMatch('end nothing', '/handoff end of session')).toBe(false);
  });

  it('counts matches over the whole map', () => {
    const m = mapModel(fixture);
    expect(mapMatchCount(m, '')).toBe(10 + 6 + 2 + 7 + 3);
    expect(mapMatchCount(m, 'zzz-nothing')).toBe(0);
    // the command, nothing else: handoff is a command name only
    expect(mapMatchCount(m, 'handoff')).toBe(1);
    // agent model "opus" matches one agent
    expect(mapMatchCount(m, 'opus')).toBe(1);
    // the "frontend" family name matches its three skills
    expect(mapMatchCount(m, 'frontend')).toBe(3);
    // a hook script matches its event
    expect(mapMatchCount(m, 'guard.py')).toBe(1);
  });
});

describe('Map tab', () => {
  const render = (guide: unknown): string =>
    renderToStaticMarkup(createElement(Guide, { guide, versions, tab: 'map', item: null }));

  it('marks the map tab selected and links it at #/guide/map', () => {
    const html = render(fixture);
    expect(html).toMatch(/href="#\/guide\/map"[^>]*aria-selected="true"/);
    expect(html).toMatch(/href="#\/guide"[^>]*aria-selected="false"/);
    expect(html).toMatch(/href="#\/guide\/wall"[^>]*aria-selected="false"/);
  });

  it('renders the root, the sheet, every section and the stats from the data', () => {
    const html = render(fixture);
    expect(html).toContain('data-testid="guide-map"');
    expect(html).toContain('data-testid="guide-map-sheet"');
    for (const label of ['The daily loop', 'Support lanes', 'Hooks across a session', 'Agents', 'Skills', 'Runtimes']) {
      expect(html).toContain(`aria-label="${label}"`);
    }
    expect(html).toMatch(/<dt>commands<\/dt><dd>10<\/dd>/);
    expect(html).toMatch(/<dt>hook scripts<\/dt><dd>6<\/dd>/);
    expect(html).toContain('1.3.176');
  });

  it('links every name to its details anchor', () => {
    const html = render(fixture);
    expect(html).toContain(`href="#/guide/details/${anchorId('command', 'feature-plan')}"`);
    expect(html).toContain(`href="#/guide/details/${anchorId('agent', 'tester')}"`);
    expect(html).toContain(`href="#/guide/details/${anchorId('skill', 'sql')}"`);
    expect(html).toContain(`href="#/guide/details/${anchorId('skillCategory', 'frontend')}"`);
    expect(html).toContain(`href="#/guide/details/${anchorId('hook', 'PreToolUse')}"`);
  });

  it('shows the model badge and the writes marker on an agent', () => {
    const html = render(fixture);
    expect(html).toContain('>opus<');
    expect(html).toContain('>writes files<');
    expect((html.match(/writes files/g) ?? []).length).toBe(1);
  });

  it('shows the missing state, not a crash, when the guide has no data', () => {
    const html = render(null);
    expect(html).toContain('data-testid="guide-state"');
    expect(html).not.toContain('data-testid="guide-map"');
  });
});
