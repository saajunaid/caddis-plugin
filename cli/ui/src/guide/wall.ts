// The wall poster, pure part: one A4 sheet built only from the guide data, so a new command shows up by itself.
import { anchorId, STAGE_ORDER, type Guide, type GuideCommand, type GuideKind } from './model';

export interface WallRow {
  kind: GuideKind;
  name: string;
  daily: boolean;
  blurb: string;
  anchor: string;
}

export interface WallCard {
  id: string;
  label: string;
  sub: string;
  kind: 'command' | 'agent';
  rows: WallRow[];
}

export interface WallModel {
  version: string;
  generated: string;
  counts: { commands: number; agents: number; skills: number; hooks: number };
  /** The daily commands in plan, build, review, ship order. */
  loop: WallRow[];
  cards: WallCard[];
}

/** Card order on the sheet. A stage not listed here lands in `other`. */
const CARD_STAGES = ['plan', 'build', 'review', 'ship', 'continuity', 'knowledge', 'setup'] as const;
const LOOP_STAGES = ['plan', 'build', 'review', 'ship'] as const;

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

const BLURB_MAX = 44;

/** The first clause of a description, at most 44 characters: a poster line is short, the Details tab has the rest. */
export function wallBlurb(description: string): string {
  const lead = description.replace(/^Use this (agent|skill) (periodically(?: \([^)]*\))? |to |when |after |for )?(to )?/i, '');
  const text = lead === description ? lead : lead.charAt(0).toUpperCase() + lead.slice(1);
  const clause = (text.split(/ [—–-] |\. |; | \(/)[0] ?? '').trim().replace(/[.:,;]+$/, '');
  if (clause.length <= BLURB_MAX) return clause;
  const cut = clause.slice(0, BLURB_MAX);
  const space = cut.lastIndexOf(' ');
  return `${(space > 20 ? cut.slice(0, space) : cut).replace(/[.:,;]+$/, '')}…`;
}

function commandRow(c: GuideCommand): WallRow {
  return {
    kind: 'command',
    name: c.name,
    daily: c.daily,
    blurb: wallBlurb(c.description),
    anchor: anchorId('command', c.name),
  };
}

const byDailyThenName = (a: GuideCommand, b: GuideCommand): number =>
  Number(b.daily) - Number(a.daily) || a.name.localeCompare(b.name);

export function wallModel(g: Guide): WallModel {
  const known = new Set<string>(STAGE_ORDER);
  const inStage = (id: string): GuideCommand[] =>
    g.commands.filter((c) => (id === 'other' ? !known.has(c.stage) : c.stage === id)).sort(byDailyThenName);

  const cards: WallCard[] = [...CARD_STAGES, 'other' as const].map((id) => ({
    id,
    label: LABELS[id]![0],
    sub: LABELS[id]![1],
    kind: 'command' as const,
    rows: inStage(id).map(commandRow),
  }));

  cards.push({
    id: 'agents',
    label: 'Agents',
    sub: 'say "use the … agent"',
    kind: 'agent',
    rows: [...g.agents]
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((a) => ({
        kind: 'agent' as const,
        name: a.name,
        daily: false,
        blurb: wallBlurb(a.description),
        anchor: anchorId('agent', a.name),
      })),
  });

  const loop = LOOP_STAGES.flatMap((id) =>
    inStage(id)
      .filter((c) => c.daily)
      .map(commandRow)
  );

  return {
    version: g.version,
    generated: g.generated,
    counts: { commands: g.commands.length, agents: g.agents.length, skills: g.skills.length, hooks: g.hooks.length },
    loop,
    cards: cards.filter((c) => c.rows.length > 0),
  };
}
