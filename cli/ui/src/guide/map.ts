// The plugin map, pure part: everything caddis ships, laid out from the guide data alone, so a new command, agent, skill or hook shows up by itself.
import { anchorId, runtimesOf, type Guide, type GuideCommand, type Runtime } from './model';
import { wallBlurb } from './wall';

export interface MapCommand {
  name: string;
  daily: boolean;
  blurb: string;
  anchor: string;
  search: string;
}

export interface MapStage {
  id: string;
  label: string;
  sub: string;
  count: number;
  commands: MapCommand[];
}

export interface MapHook {
  event: string;
  anchor: string;
  handlers: string[];
  matchers: string[];
  search: string;
}

export interface MapAgent {
  name: string;
  model: string;
  writes: boolean;
  blurb: string;
  anchor: string;
  search: string;
}

export interface MapSkill {
  name: string;
  core: boolean;
  anchor: string;
  search: string;
}

export interface MapFamily {
  id: string;
  anchor: string;
  count: number;
  skills: MapSkill[];
}

export interface MapRuntime extends Runtime {
  search: string;
}

export interface MapModel {
  version: string;
  generated: string;
  counts: { commands: number; agents: number; skills: number; hookEvents: number; hookScripts: number; runtimes: number };
  loop: MapStage[];
  support: MapStage[];
  hooks: MapHook[];
  agents: MapAgent[];
  skills: MapFamily[];
  runtimes: MapRuntime[];
}

/** The daily loop, left to right. */
const LOOP_STAGES = ['plan', 'build', 'review', 'ship'] as const;
/** The lanes under the loop. A stage in neither list lands in `other`. */
const SUPPORT_STAGES = ['continuity', 'knowledge', 'setup'] as const;

const LABELS: Record<string, [string, string]> = {
  plan: ['Plan', 'decide what to build'],
  build: ['Build', 'write the code'],
  review: ['Review', 'catch bugs first'],
  ship: ['Ship', 'PR · CI · merge'],
  continuity: ['Continuity', 'never lose your place'],
  knowledge: ['Knowledge', 'write it down once'],
  setup: ['Setup', 'once per repo or machine'],
  other: ['Other', 'everything else'],
};

/** Claude Code hook events in the order a session runs them. An event not listed goes after these, by name. */
export const HOOK_EVENT_ORDER = [
  'SessionStart',
  'UserPromptSubmit',
  'PreToolUse',
  'PermissionRequest',
  'PostToolUse',
  'PostToolUseFailure',
  'Notification',
  'SubagentStop',
  'Stop',
  'PreCompact',
  'SessionEnd',
] as const;

const lower = (...parts: string[]): string => parts.join(' ').toLowerCase();

const byDailyThenName = (a: GuideCommand, b: GuideCommand): number =>
  Number(b.daily) - Number(a.daily) || a.name.localeCompare(b.name);

/** The file name of a hook handler, without its folder. */
export function handlerName(handler: string): string {
  const trimmed = handler.trim();
  return trimmed.split(/[\\/]/).pop() || trimmed;
}

function eventRank(event: string): number {
  const i = (HOOK_EVENT_ORDER as readonly string[]).indexOf(event);
  return i >= 0 ? i : HOOK_EVENT_ORDER.length;
}

const distinctSorted = (values: string[]): string[] => [...new Set(values)].sort((a, b) => a.localeCompare(b));

/** True when the query is empty, or every word of it appears in the search text. Case does not matter. */
export function mapMatch(query: string, search: string): boolean {
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const text = search.toLowerCase();
  return words.every((w) => text.includes(w));
}

export function mapModel(g: Guide): MapModel {
  // Only stages the map draws count as known, so a new stage in STAGE_ORDER lands in `other` instead of vanishing.
  const known = new Set<string>([...LOOP_STAGES, ...SUPPORT_STAGES]);
  const inStage = (id: string): GuideCommand[] =>
    g.commands.filter((c) => (id === 'other' ? !known.has(c.stage) : c.stage === id)).sort(byDailyThenName);

  const stage = (id: string): MapStage => {
    const commands = inStage(id).map((c) => ({
      name: c.name,
      daily: c.daily,
      blurb: wallBlurb(c.description),
      anchor: anchorId('command', c.name),
      search: lower(c.name, c.description, c.hint, c.stage),
    }));
    return { id, label: LABELS[id]![0], sub: LABELS[id]![1], count: commands.length, commands };
  };
  const nonEmpty = (s: MapStage): boolean => s.count > 0;

  const hooksByEvent = new Map<string, { handlers: string[]; matchers: string[] }>();
  for (const h of g.hooks) {
    const entry = hooksByEvent.get(h.event) ?? { handlers: [], matchers: [] };
    entry.handlers.push(handlerName(h.handler));
    if (h.matcher.trim()) entry.matchers.push(h.matcher);
    hooksByEvent.set(h.event, entry);
  }
  const hooks: MapHook[] = [...hooksByEvent.keys()]
    .sort((a, b) => eventRank(a) - eventRank(b) || a.localeCompare(b))
    .map((event) => {
      const entry = hooksByEvent.get(event)!;
      const handlers = distinctSorted(entry.handlers);
      const matchers = distinctSorted(entry.matchers);
      return { event, anchor: anchorId('hook', event), handlers, matchers, search: lower(event, ...handlers, ...matchers) };
    });

  const agents: MapAgent[] = [...g.agents]
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((a) => ({
      name: a.name,
      model: a.model,
      writes: a.writes,
      blurb: wallBlurb(a.description),
      anchor: anchorId('agent', a.name),
      search: lower(a.name, a.description, a.model),
    }));

  const byCategory = new Map<string, Guide['skills']>();
  for (const s of g.skills) {
    const id = s.category || 'uncategorised';
    byCategory.set(id, [...(byCategory.get(id) ?? []), s]);
  }
  const skills: MapFamily[] = [...byCategory.entries()]
    .map(([id, list]) => ({
      id,
      anchor: anchorId('skillCategory', id),
      count: list.length,
      skills: [...list]
        .sort((a, b) => Number(b.core) - Number(a.core) || a.name.localeCompare(b.name))
        .map((s) => ({ name: s.name, core: s.core, anchor: anchorId('skill', s.name), search: lower(s.name, s.description, id) })),
    }))
    .sort((a, b) => b.count - a.count || a.id.localeCompare(b.id));

  const runtimes: MapRuntime[] = runtimesOf(g).map((r) => ({ ...r, search: lower(r.name, ...r.kinds) }));

  return {
    version: g.version,
    generated: g.generated,
    counts: {
      commands: g.commands.length,
      agents: g.agents.length,
      skills: g.skills.length,
      hookEvents: hooks.length,
      hookScripts: new Set(g.hooks.map((h) => handlerName(h.handler))).size,
      runtimes: runtimes.length,
    },
    loop: LOOP_STAGES.map(stage).filter(nonEmpty),
    support: [...SUPPORT_STAGES, 'other' as const].map(stage).filter(nonEmpty),
    hooks,
    agents,
    skills,
    runtimes,
  };
}

/** How many items match the query, over everything on the map. Used for the "n matches" note. */
export function mapMatchCount(m: MapModel, query: string): number {
  const has = (s: { search: string }): boolean => mapMatch(query, s.search);
  const stages = [...m.loop, ...m.support].reduce((n, s) => n + s.commands.filter(has).length, 0);
  const skills = m.skills.reduce((n, f) => n + f.skills.filter(has).length, 0);
  return stages + m.hooks.filter(has).length + m.agents.filter(has).length + skills + m.runtimes.filter(has).length;
}
