import { anchorId, STAGE_ORDER, type Guide, type GuideCommand, type GuideKind } from './model';

export interface PosterItem {
  kind: GuideKind;
  name: string;
  blurb: string;
  daily: boolean;
  anchor: string;
}

export interface PosterStage {
  id: string;
  label: string;
  flow: boolean;
  commands: PosterItem[];
}

export interface PosterModel {
  version: string;
  flow: PosterStage[];
  bands: PosterStage[];
  agentsReadOnly: PosterItem[];
  agentsWrite: PosterItem[];
  skillCategories: (PosterItem & { count: number })[];
  hooks: { event: string; count: number }[];
  counts: { commands: number; agents: number; skills: number; hooks: number };
}

const FLOW_IDS = ['setup', 'plan', 'build', 'review', 'ship'] as const;
const BAND_IDS = ['continuity', 'knowledge'] as const;

const STAGE_LABELS: Record<string, string> = {
  setup: 'Setup',
  plan: 'Plan',
  build: 'Build',
  review: 'Review',
  ship: 'Ship',
  continuity: 'Continuity',
  knowledge: 'Knowledge',
  other: 'Other',
};

export function blurb(description: string): string {
  const dotIdx = description.indexOf('. ');
  const first = (dotIdx >= 0 ? description.slice(0, dotIdx + 1) : description).trim();
  return first.length > 90 ? `${first.slice(0, 89)}…` : first;
}

function toCommandItem(c: GuideCommand): PosterItem {
  return {
    kind: 'command',
    name: c.name,
    blurb: blurb(c.description),
    daily: c.daily,
    anchor: anchorId('command', c.name),
  };
}

function sortStageCommands(cmds: GuideCommand[]): PosterItem[] {
  return [...cmds]
    .sort((a, b) => Number(b.daily) - Number(a.daily) || a.name.localeCompare(b.name))
    .map(toCommandItem);
}

export function posterModel(g: Guide): PosterModel {
  const knownStages = new Set<string>(STAGE_ORDER);

  const flow: PosterStage[] = FLOW_IDS.map((id) => ({
    id,
    label: STAGE_LABELS[id]!,
    flow: true,
    commands: sortStageCommands(g.commands.filter((c) => c.stage === id)),
  }));

  const bands: PosterStage[] = BAND_IDS.map((id) => ({
    id,
    label: STAGE_LABELS[id]!,
    flow: false,
    commands: sortStageCommands(g.commands.filter((c) => c.stage === id)),
  }));

  const otherCommands = sortStageCommands(g.commands.filter((c) => !knownStages.has(c.stage)));
  if (otherCommands.length > 0) {
    bands.push({
      id: 'other',
      label: STAGE_LABELS.other!,
      flow: false,
      commands: otherCommands,
    });
  }

  const toAgentItem = (a: Guide['agents'][number]): PosterItem => ({
    kind: 'agent',
    name: a.name,
    blurb: blurb(a.description),
    daily: false,
    anchor: anchorId('agent', a.name),
  });

  const agentsReadOnly = g.agents
    .filter((a) => !a.writes)
    .sort((a, b) => a.name.localeCompare(b.name))
    .map(toAgentItem);

  const agentsWrite = g.agents
    .filter((a) => a.writes)
    .sort((a, b) => a.name.localeCompare(b.name))
    .map(toAgentItem);

  const catCounts = new Map<string, number>();
  for (const s of g.skills) {
    catCounts.set(s.category, (catCounts.get(s.category) ?? 0) + 1);
  }
  const skillCategories = [...catCounts.entries()]
    .sort(([nameA, countA], [nameB, countB]) => countB - countA || nameA.localeCompare(nameB))
    .map(([name, count]) => ({
      kind: 'skillCategory' as const,
      name,
      blurb: '',
      daily: false,
      anchor: anchorId('skillCategory', name),
      count,
    }));

  const hookCounts = new Map<string, number>();
  for (const h of g.hooks) {
    hookCounts.set(h.event, (hookCounts.get(h.event) ?? 0) + 1);
  }
  const hooks = [...hookCounts.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([event, count]) => ({ event, count }));

  return {
    version: g.version,
    flow,
    bands,
    agentsReadOnly,
    agentsWrite,
    skillCategories,
    hooks,
    counts: {
      commands: g.commands.length,
      agents: g.agents.length,
      skills: g.skills.length,
      hooks: g.hooks.length,
    },
  };
}

export interface MapNode {
  id: string;
  label: string;
  kind: GuideKind | 'stage' | 'group' | 'root';
  anchor: string | null;
  x: number;
  y: number;
  r: number;
  parent: string | null;
}

function round1(v: number): number {
  const r = Math.round(v * 10) / 10;
  return Object.is(r, -0) ? 0 : r;
}

export function mindMap(p: PosterModel, size: number): MapNode[] {
  const half = size / 2;
  const nodes: MapNode[] = [
    {
      id: 'root',
      label: 'caddis',
      kind: 'root',
      anchor: null,
      x: round1(half),
      y: round1(half),
      r: round1(0.06 * size),
      parent: null,
    },
  ];

  interface LeafSpec {
    kind: GuideKind;
    name: string;
    anchor: string;
  }

  interface BranchSpec {
    id: string;
    label: string;
    kind: 'stage' | 'group';
    leaves: LeafSpec[];
  }

  const branches: BranchSpec[] = [
    ...p.flow.map((s) => ({
      id: `stage-${s.id}`,
      label: s.label,
      kind: 'stage' as const,
      leaves: s.commands.map((c) => ({ kind: 'command' as const, name: c.name, anchor: anchorId('command', c.name) })),
    })),
    ...p.bands.map((s) => ({
      id: `stage-${s.id}`,
      label: s.label,
      kind: 'stage' as const,
      leaves: s.commands.map((c) => ({ kind: 'command' as const, name: c.name, anchor: anchorId('command', c.name) })),
    })),
    {
      id: 'agents',
      label: 'Agents',
      kind: 'group',
      leaves: [...p.agentsReadOnly, ...p.agentsWrite].map((a) => ({
        kind: 'agent' as const,
        name: a.name,
        anchor: anchorId('agent', a.name),
      })),
    },
    {
      id: 'skills',
      label: 'Skills',
      kind: 'group',
      leaves: p.skillCategories.map((c) => ({
        kind: 'skillCategory' as const,
        name: c.name,
        anchor: anchorId('skillCategory', c.name),
      })),
    },
    {
      id: 'hooks',
      label: 'Hooks',
      kind: 'group',
      leaves: p.hooks.map((h) => ({
        kind: 'hook' as const,
        name: h.event,
        anchor: anchorId('hook', h.event),
      })),
    },
  ];

  const n = branches.length;
  const branchRadius = 0.24 * size;
  const branchR = round1(0.035 * size);
  const leafR = round1(0.012 * size);

  branches.forEach((b, i) => {
    const a = -90 + (i * 360) / n;
    const rad = (a * Math.PI) / 180;
    nodes.push({
      id: b.id,
      label: b.label,
      kind: b.kind,
      anchor: null,
      x: round1(half + branchRadius * Math.cos(rad)),
      y: round1(half + branchRadius * Math.sin(rad)),
      r: branchR,
      parent: 'root',
    });

    const k = b.leaves.length;
    b.leaves.forEach((leaf, j) => {
      const leafAngle = a + (k === 1 ? 0 : (j / (k - 1) - 0.5) * (300 / n));
      const leafRad = (leafAngle * Math.PI) / 180;
      const leafRadius = (j % 2 === 0 ? 0.40 : 0.45) * size;
      nodes.push({
        id: `${leaf.kind}-${leaf.name}`,
        label: leaf.name,
        kind: leaf.kind,
        anchor: leaf.anchor,
        x: round1(half + leafRadius * Math.cos(leafRad)),
        y: round1(half + leafRadius * Math.sin(leafRad)),
        r: leafR,
        parent: b.id,
      });
    });
  });

  return nodes;
}
