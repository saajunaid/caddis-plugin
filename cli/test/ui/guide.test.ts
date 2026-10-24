import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
  buildGuide,
  guideSections,
  guideStatus,
  invokeText,
  runtimesOf,
  STAGE_ORDER,
  SUPPORTED_GUIDE_SCHEMA,
  type Guide,
} from '../../ui/src/guide/model';

const fixture = JSON.parse(readFileSync(new URL('../fixtures/hub-state/guide.json', import.meta.url), 'utf8')).guide as Guide;

describe('guideStatus', () => {
  it('reads the four states', () => {
    expect(guideStatus(null)).toEqual({ kind: 'missing' });
    expect(guideStatus({ error: 'relay read failed' })).toEqual({ kind: 'error', message: 'relay read failed' });
    expect(guideStatus({ ...fixture, schema: SUPPORTED_GUIDE_SCHEMA + 1 })).toEqual({ kind: 'newer', schema: 2 });
    expect(guideStatus(fixture).kind).toBe('ok');
  });
  it('turns bad data into an error, not a crash', () => {
    expect(guideStatus('text').kind).toBe('error');
    expect(guideStatus([]).kind).toBe('error');
    const { hooks: _hooks, ...noHooks } = fixture;
    expect(guideStatus(noHooks)).toMatchObject({ kind: 'error' });
    expect(guideStatus({ ...fixture, coverage: null }).kind).toBe('error');
  });
});

describe('sections and counts', () => {
  it('the fixture counts equal its own counts field', () => {
    const s = guideSections(fixture);
    expect(s).toMatchObject({
      commands: fixture.counts!.commands,
      agents: fixture.counts!.agents,
      skills: fixture.counts!.skills,
      hooks: fixture.counts!.hooks,
    });
    expect(s.runtimes).toBe(3);
  });
  it('lists each runtime with the kinds it receives', () => {
    expect(runtimesOf(fixture)).toEqual([
      { name: 'antigravity-plugin', kinds: ['skills', 'agents'] },
      { name: 'claude', kinds: ['commands', 'skills', 'agents'] },
      { name: 'codex-plugin', kinds: ['commands', 'skills'] },
    ]);
  });
});

describe('grouping', () => {
  const v = buildGuide(fixture, '');
  it('orders command stages: known first, other next, ungrouped last', () => {
    expect(v.commands.groups.map((g) => g.id)).toEqual([...STAGE_ORDER, 'tracking', 'ungrouped']);
  });
  it('groups skills by category with core skills first', () => {
    const wf = v.skills.groups.find((g) => g.id === 'workflow')!;
    expect(wf.entries.every((s) => s.core)).toBe(true);
    expect(v.skills.groups.map((g) => g.id)).toEqual(['data', 'languages', 'uncategorised', 'workflow']);
  });
  it('groups hooks by event', () => {
    expect(v.hooks.groups.map((g) => g.id)).toEqual(['PreToolUse', 'SessionEnd', 'SessionStart']);
  });
});

describe('invokeText', () => {
  it('derives the Claude Code form of each kind', () => {
    const plan = fixture.commands.find((c) => c.name === 'feature-plan')!;
    const noArgs = fixture.commands.find((c) => c.name === 'ship-pr')!;
    expect(invokeText('command', plan)).toBe('/caddis:feature-plan <feature>');
    expect(invokeText('command', noArgs)).toBe('/caddis:ship-pr');
    expect(invokeText('agent', fixture.agents[0]!)).toBe('Agent tool, subagent_type: caddis:tester');
    expect(invokeText('skill', fixture.skills[0]!)).toBe('Skill tool: caddis:tdd');
    expect(invokeText('hook', fixture.hooks[0]!)).toBe('Runs by itself on PreToolUse for Bash|Edit');
  });
});

describe('filter', () => {
  const names = (q: string) => buildGuide(fixture, q).commands.groups.flatMap((g) => g.entries.map((e) => e.name));
  it('matches name, description, hint and stage, ignoring case', () => {
    expect(names('SHIP-PR')).toEqual(['ship-pr']);
    expect(names('red-green')).toEqual([]);
    expect(names('phased')).toEqual(['feature-plan']);
    expect(names('<plan path>')).toEqual(['implement']);
    expect(names('continuity')).toEqual(['handoff']);
  });
  it('matches a hook handler and a runtime', () => {
    const v = buildGuide(fixture, 'warm_start');
    expect(v.hooks.shown).toBe(1);
    expect(buildGuide(fixture, 'codex').runtimes.shown).toBe(1);
  });
  it('hides empty groups and keeps total fixed', () => {
    const v = buildGuide(fixture, 'handoff');
    expect(v.commands.groups.map((g) => g.id)).toEqual(['continuity']);
    expect(v.commands.shown).toBe(1);
    expect(v.commands.total).toBe(fixture.commands.length);
    expect(v.skills.groups).toEqual([]);
  });
  it('treats blank text as no filter', () => {
    expect(buildGuide(fixture, '   ').commands.shown).toBe(fixture.commands.length);
  });
});
