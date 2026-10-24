// The caddis guide page, pure part: status, counts, grouping, filter, invoke text (G1-G5).

/** The guide schema this UI understands. A higher value means the hub is older than its data. */
export const SUPPORTED_GUIDE_SCHEMA = 1;

export const STAGE_ORDER = ['setup', 'plan', 'build', 'review', 'ship', 'continuity', 'knowledge'] as const;

export interface GuideCommand {
  name: string;
  description: string;
  hint: string;
  noArgs: boolean;
  stage: string;
  daily: boolean;
}
export interface GuideAgent {
  name: string;
  description: string;
  tools: string[];
  model: string;
  writes: boolean;
}
export interface GuideSkill {
  name: string;
  category: string;
  description: string;
  core: boolean;
}
export interface GuideHook {
  event: string;
  matcher: string;
  handler: string;
}
export interface Guide {
  schema: number;
  version: string;
  generated: string;
  commands: GuideCommand[];
  agents: GuideAgent[];
  skills: GuideSkill[];
  hooks: GuideHook[];
  coverage: { commands: string[]; skills: string[]; agents: string[] };
  counts?: Record<string, number>;
}

export type GuideStatus =
  | { kind: 'missing' }
  | { kind: 'error'; message: string }
  | { kind: 'newer'; schema: number }
  | { kind: 'ok'; guide: Guide };

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);

/** Decide what the page shows. Bad data gives `error`, never a crash. */
export function guideStatus(raw: unknown): GuideStatus {
  if (raw === null || raw === undefined) return { kind: 'missing' };
  if (!isObj(raw)) return { kind: 'error', message: 'The guide data has an unexpected shape.' };
  if (typeof raw.error === 'string') return { kind: 'error', message: raw.error };
  if (typeof raw.schema === 'number' && raw.schema > SUPPORTED_GUIDE_SCHEMA) return { kind: 'newer', schema: raw.schema };
  for (const key of ['commands', 'agents', 'skills', 'hooks']) {
    if (!Array.isArray(raw[key])) return { kind: 'error', message: `The guide data has no "${key}" list.` };
  }
  if (!isObj(raw.coverage)) return { kind: 'error', message: 'The guide data has no "coverage" list.' };
  return { kind: 'ok', guide: raw as unknown as Guide };
}

export type SectionId = 'commands' | 'agents' | 'skills' | 'hooks' | 'runtimes';
export const SECTION_IDS: SectionId[] = ['commands', 'agents', 'skills', 'hooks', 'runtimes'];
export const SECTION_TITLES: Record<SectionId, string> = {
  commands: 'Commands',
  agents: 'Agents',
  skills: 'Skills',
  hooks: 'Hooks',
  runtimes: 'Runtimes',
};

export interface Runtime {
  name: string;
  kinds: string[];
}

/** Each runtime named in `coverage`, with the kinds it receives. Sorted by name. */
export function runtimesOf(guide: Guide): Runtime[] {
  const map = new Map<string, string[]>();
  for (const kind of ['commands', 'skills', 'agents'] as const) {
    for (const name of guide.coverage[kind] ?? []) map.set(name, [...(map.get(name) ?? []), kind]);
  }
  return [...map.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([name, kinds]) => ({ name, kinds }));
}

/** The count of each section: the length of its list; runtimes are the distinct names in `coverage`. */
export function guideSections(guide: Guide): Record<SectionId, number> {
  return {
    commands: guide.commands.length,
    agents: guide.agents.length,
    skills: guide.skills.length,
    hooks: guide.hooks.length,
    runtimes: runtimesOf(guide).length,
  };
}

export type InvokeKind = 'command' | 'agent' | 'skill' | 'hook';

/** How to start an entry in Claude Code. Derived, never stored (G4). */
export function invokeText(kind: 'command', e: GuideCommand): string;
export function invokeText(kind: 'agent', e: GuideAgent): string;
export function invokeText(kind: 'skill', e: GuideSkill): string;
export function invokeText(kind: 'hook', e: GuideHook): string;
export function invokeText(kind: InvokeKind, e: GuideCommand | GuideAgent | GuideSkill | GuideHook): string {
  if (kind === 'command') {
    const c = e as GuideCommand;
    return c.noArgs || !c.hint ? `/caddis:${c.name}` : `/caddis:${c.name} ${c.hint}`;
  }
  if (kind === 'agent') return `Agent tool, subagent_type: caddis:${(e as GuideAgent).name}`;
  if (kind === 'skill') return `Skill tool: caddis:${(e as GuideSkill).name}`;
  const h = e as GuideHook;
  return `Runs by itself on ${h.event} for ${h.matcher}`;
}

export interface Group<T> {
  id: string;
  title: string;
  entries: T[];
}
export interface Section<T> {
  total: number;
  shown: number;
  groups: Group<T>[];
}
export interface GuideView {
  commands: Section<GuideCommand>;
  agents: Section<GuideAgent>;
  skills: Section<GuideSkill>;
  hooks: Section<GuideHook>;
  runtimes: Section<Runtime>;
}

const norm = (s: string): string => s.trim().toLowerCase();
const hit = (needle: string, ...fields: string[]): boolean => needle === '' || fields.some((f) => f.toLowerCase().includes(needle));

function section<T>(all: T[], keep: (e: T) => boolean, groupOf: (e: T) => string, order: (a: string, b: string) => number): Section<T> {
  const byGroup = new Map<string, T[]>();
  for (const e of all.filter(keep)) byGroup.set(groupOf(e), [...(byGroup.get(groupOf(e)) ?? []), e]);
  const groups = [...byGroup.keys()].sort(order).map((id) => ({ id, title: id, entries: byGroup.get(id)! }));
  return { total: all.length, shown: groups.reduce((n, g) => n + g.entries.length, 0), groups };
}

function stageRank(stage: string): number {
  const i = (STAGE_ORDER as readonly string[]).indexOf(stage);
  if (i >= 0) return i;
  return stage === 'ungrouped' ? STAGE_ORDER.length + 1 : STAGE_ORDER.length;
}

/** Group and filter every section. `total` ignores the filter; `shown` follows it (G3, G5). */
export function buildGuide(guide: Guide, filter: string): GuideView {
  const q = norm(filter);
  const stageOrder = (a: string, b: string): number => stageRank(a) - stageRank(b) || a.localeCompare(b);
  const runtimes = runtimesOf(guide);
  return {
    commands: section(guide.commands, (c) => hit(q, c.name, c.description, c.hint, c.stage), (c) => c.stage || 'ungrouped', stageOrder),
    agents: section(guide.agents, (a) => hit(q, a.name, a.description, a.model), () => 'agents', () => 0),
    skills: section(
      [...guide.skills].sort((a, b) => Number(b.core) - Number(a.core) || a.name.localeCompare(b.name)),
      (s) => hit(q, s.name, s.description, s.category),
      (s) => s.category || 'uncategorised',
      (a, b) => a.localeCompare(b),
    ),
    hooks: section(guide.hooks, (h) => hit(q, h.event, h.matcher, h.handler), (h) => h.event, (a, b) => a.localeCompare(b)),
    runtimes: section(runtimes, (r) => hit(q, r.name, ...r.kinds), () => 'runtimes', () => 0),
  };
}
