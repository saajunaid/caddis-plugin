import { describe, expect, it } from 'vitest';
import { anchorId, type Guide } from '../../ui/src/guide/model';
import { blurb, mindMap, posterModel } from '../../ui/src/guide/poster';

const fixture: Guide = {
  schema: 1,
  version: '1.3.172',
  generated: '2026-10-26T00:00:00Z',
  commands: [
    { name: 'setup-project-ai', description: 'Install harness.', hint: '', steps: [], scripts: [], noArgs: true, stage: 'setup', daily: false },
    { name: 'prf', description: 'Validate plan.', hint: '', steps: [], scripts: [], noArgs: false, stage: 'plan', daily: false },
    { name: 'feature-plan', description: 'Create plan.', hint: '<feature>', steps: [], scripts: [], noArgs: false, stage: 'plan', daily: true },
    { name: 'implement', description: 'Run plan.', hint: '<plan>', steps: [], scripts: [], noArgs: false, stage: 'build', daily: true },
    { name: 'handoff', description: 'Capture state.', hint: '', steps: [], scripts: [], noArgs: true, stage: 'continuity', daily: true },
    { name: 'version', description: 'Report version.', hint: '', steps: [], scripts: [], noArgs: true, stage: 'ungrouped', daily: false },
  ],
  agents: [
    { name: 'tester', description: 'Runs tests.', tools: ['Bash'], model: 'sonnet', writes: true },
    { name: 'code-reviewer', description: 'Reviews diffs.', tools: ['Read'], model: 'sonnet', writes: false },
  ],
  skills: [
    { name: 'tdd', category: 'workflow', description: 'Red green refactor.', core: true },
    { name: 'code-review', category: 'workflow', description: 'Review changes.', core: true },
    { name: 'sql', category: 'data', description: 'Write SQL.', core: false },
  ],
  hooks: [
    { event: 'PreToolUse', matcher: 'Bash', handler: 'guard.py' },
    { event: 'PreToolUse', matcher: 'Edit', handler: 'edit_guard.py' },
  ],
  coverage: { commands: ['claude'], skills: ['claude'], agents: ['claude'] },
};

describe('blurb', () => {
  it('takes the first sentence and caps at 90 characters with an ellipsis', () => {
    expect(blurb('Does X. Then Y.')).toBe('Does X.');
    const longSentence = 'A'.repeat(120);
    const out = blurb(longSentence);
    expect(out.length).toBe(90);
    expect(out.endsWith('…')).toBe(true);
  });
});

describe('posterModel', () => {
  it('builds flow stages, bands, agents, skill categories, hooks, and counts', () => {
    const m = posterModel(fixture);
    expect(m.version).toBe('1.3.172');
    expect(m.flow.map((s) => s.id)).toEqual(['setup', 'plan', 'build', 'review', 'ship']);
    expect(m.flow.every((s) => s.flow)).toBe(true);
    expect(m.bands.map((s) => s.label)).toEqual(['Continuity', 'Knowledge', 'Other']);
    expect(m.bands.every((s) => !s.flow)).toBe(true);

    const otherStage = m.bands.find((s) => s.label === 'Other')!;
    expect(otherStage.commands.map((c) => c.name)).toEqual(['version']);

    const planStage = m.flow.find((s) => s.label === 'Plan')!;
    expect(planStage.commands.map((c) => c.name)).toEqual(['feature-plan', 'prf']);

    expect(m.agentsReadOnly.map((a) => a.name)).toEqual(['code-reviewer']);
    expect(m.agentsWrite.map((a) => a.name)).toEqual(['tester']);

    expect(m.skillCategories.map((c) => ({ name: c.name, count: c.count, kind: c.kind, blurb: c.blurb }))).toEqual([
      { name: 'workflow', count: 2, kind: 'skillCategory', blurb: '' },
      { name: 'data', count: 1, kind: 'skillCategory', blurb: '' },
    ]);

    expect(m.counts).toEqual({ commands: 6, agents: 2, skills: 3, hooks: 2 });
    expect(m.hooks).toEqual([{ event: 'PreToolUse', count: 2 }]);
  });

  it('omits Other band when all commands belong to STAGE_ORDER stages', () => {
    const knownOnly: Guide = {
      ...fixture,
      commands: fixture.commands.filter((c) => c.stage !== 'ungrouped'),
    };
    const m = posterModel(knownOnly);
    expect(m.bands.map((s) => s.label)).toEqual(['Continuity', 'Knowledge']);
  });
});

describe('mindMap', () => {
  it('lays out root, branches, and leaves within bounds with expected coordinates and anchors', () => {
    const knownOnly: Guide = {
      ...fixture,
      commands: fixture.commands.filter((c) => c.stage !== 'ungrouped'),
    };
    const m = posterModel(knownOnly);
    const nodes = mindMap(m, 1000);

    const root = nodes.find((n) => n.id === 'root')!;
    expect(root).toEqual({
      id: 'root',
      label: 'caddis',
      kind: 'root',
      anchor: null,
      x: 500,
      y: 500,
      r: 60,
      parent: null,
    });

    const branches = nodes.filter((n) => n.parent === 'root');
    expect(branches.length).toBe(10);
    expect(branches[0]?.x).toBe(500);
    expect(branches[0]?.y).toBe(260);

    const branchIds = new Set(branches.map((b) => b.id));
    const leaves = nodes.filter((n) => n.id !== 'root' && n.parent !== 'root');
    expect(leaves.length).toBeGreaterThan(0);
    for (const leaf of leaves) {
      expect(leaf.parent && branchIds.has(leaf.parent)).toBe(true);
    }

    const commandLeaves = leaves.filter((l) => l.kind === 'command');
    expect(commandLeaves.length).toBe(knownOnly.commands.length);
    for (const cmdLeaf of commandLeaves) {
      expect(cmdLeaf.anchor).toBe(anchorId('command', cmdLeaf.label));
    }

    for (const node of nodes) {
      expect(node.x).toBeGreaterThanOrEqual(0);
      expect(node.x).toBeLessThanOrEqual(1000);
      expect(node.y).toBeGreaterThanOrEqual(0);
      expect(node.y).toBeLessThanOrEqual(1000);
    }
  });
});
