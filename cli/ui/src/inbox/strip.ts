import { ageText } from '../shell/format';
import { repoId, repoTabHref } from '../shell/route';
import { deriveRoadmaps, listRow } from '../repo/roadmap';
import type { HubState } from '../types';
import { repoLabel } from './derive';

export interface ShipRow {
  key: string;
  repo: string;
  pr: number;
  title: string;
  url: string | null;
  at: string;
  age: string;
}

/** The recent merges of every repo, newest first. */
export function shippedList(state: HubState, nowMs: number, limit = 5): ShipRow[] {
  const rows: ShipRow[] = [];
  for (const repo of state.repos) {
    const gh = repo.github;
    for (const m of gh?.merges ?? []) {
      rows.push({
        key: `${repo.path}:${m.number}`,
        repo: repoLabel(repo),
        pr: m.number,
        title: `#${m.number} ${m.title}`,
        url: gh?.repo ? `https://github.com/${gh.repo}/pull/${m.number}` : null,
        at: m.merged_at,
        age: ageText(m.merged_at, nowMs),
      });
    }
  }
  const time = (iso: string): number => {
    const t = Date.parse(iso);
    return Number.isNaN(t) ? 0 : t;
  };
  return rows.sort((a, b) => time(b.at) - time(a.at)).slice(0, limit);
}

export interface StripRoadmap {
  key: string;
  slug: string;
  repo: string;
  href: string;
  label: string;
  segs: { id: string; tone: 'done' | 'wait' | 'block' | 'prog' | 'todo' }[];
}

/** One row per roadmap over every repo, in repo order: milestone progress and one segment per milestone. */
export function roadmapStrip(state: HubState, limit = 6): StripRoadmap[] {
  const out: StripRoadmap[] = [];
  for (const repo of state.repos) {
    for (const model of deriveRoadmaps(repo).roadmaps) {
      const row = listRow(model);
      const phases = row.phasesTotal > 0 ? ` · ${row.phasesDone}/${row.phasesTotal} phases` : '';
      out.push({
        key: `${repo.path}:${model.slug}`,
        slug: model.slug,
        repo: repoLabel(repo),
        href: repoTabHref(repoId(repo), 'roadmap', model.slug),
        label: `${row.milestonesDone} of ${row.milestonesTotal} milestones${phases}`,
        segs: model.milestones.map((m) => ({ id: m.id, tone: m.tone })),
      });
    }
  }
  return out.slice(0, limit);
}
