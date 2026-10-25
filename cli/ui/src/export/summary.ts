import type { ExportData } from '../../../src/hub/export/data';
import { deriveRoadmaps, type Blocker, type RepoRoadmaps } from '../repo/roadmap';
import type { RepoState } from '../types';

/**
 * The model of the export page (R60, R63). Pure, so vitest checks every row of the parity list S1-S17.
 * The data is the allow-list output of `exportData`. Nothing here reads anything else.
 */

/** The link id of the one repo. No org or folder name goes into a URL (R63). */
export const EXPORT_REPO_ID = 'repo';

/** A repo of the shape the Roadmap view wants, built from the export data. */
export function exportRepo(data: ExportData): RepoState {
  const name = data.github ? (data.github.split('/')[1] ?? data.github) : 'repo';
  return {
    path: '',
    name,
    repo_id: EXPORT_REPO_ID,
    pinned: false,
    roadmaps: { schema: 1, roadmaps: data.roadmaps },
    plans: { schema: 1, plans: data.plans },
    relays: null,
    // The slot only makes PR links. It names the public repo and holds no PR state.
    github: data.github ? ({ repo: data.github, prs: [], merges: [] } as unknown as RepoState['github']) : null,
    coordinator: null,
    owner_items: [],
    actions: {} as RepoState['actions'],
  };
}

export interface NeedRow {
  roadmap: string;
  milestone: string;
  reason: string;
  check: string;
}
export interface GateRow extends NeedRow {
  type: string;
}
export interface ExportSummary {
  roadmaps: number;
  needsYou: number;
  phasesDone: number;
  phasesTotal: number;
  /** 0 to 100 */
  pct: number;
  blockedPhases: number;
  needs: NeedRow[];
  gates: GateRow[];
  slugs: string[];
}

const FINISHED = new Set(['done', 'not-needed']);

export function exportSummary(data: ExportData): ExportSummary {
  const m: RepoRoadmaps = deriveRoadmaps(exportRepo(data));
  const needs: NeedRow[] = [];
  const owner: GateRow[] = [];
  const other: GateRow[] = [];
  let phasesDone = 0;
  let phasesTotal = 0;
  let blockedPhases = 0;
  for (const r of m.roadmaps) {
    phasesDone += r.kpis.phasesDone;
    phasesTotal += r.kpis.phasesTotal;
    blockedPhases += r.milestones.flatMap((x) => x.phases).filter((p) => p.tile === 'blocked').length;
    const row = (b: Blocker): NeedRow => ({ roadmap: r.slug, milestone: b.milestone, reason: b.reason, check: b.check });
    for (const g of r.gates) {
      needs.push(row(g));
      owner.push({ ...row(g), type: 'owner-gate' });
    }
    // Every other open blocker: an unfinished milestone, and not an owner gate already listed.
    for (const ms of r.milestones.filter((x) => !FINISHED.has(x.status))) {
      for (const b of ms.blockers.filter((x) => x.type !== 'owner-gate')) other.push({ ...row(b), type: b.type });
    }
  }
  return {
    roadmaps: m.roadmaps.length,
    needsYou: needs.length,
    phasesDone,
    phasesTotal,
    pct: phasesTotal ? Math.round((100 * phasesDone) / phasesTotal) : 0,
    blockedPhases,
    needs,
    gates: [...owner, ...other],
    slugs: m.roadmaps.map((r) => r.slug),
  };
}

export type ExportRoute = { page: 'home' } | { page: 'gates' } | { page: 'roadmap'; slug: string };

/**
 * `#/` is home, `#/gates` the gates, `#/roadmap/<slug>` one roadmap. An old `#rm-<6hex>-<slug>` link maps to its
 * roadmap (S17, R63). Anything else is home.
 */
export function routeExport(hash: string): ExportRoute {
  const old = /^#rm-[0-9a-fA-F]{6}-(.+)$/.exec(hash);
  if (old) return { page: 'roadmap', slug: safeDecode(old[1]!) };
  const parts = hash.replace(/^#\/?/, '').split('/');
  if (parts[0] === 'gates') return { page: 'gates' };
  if (parts[0] === 'roadmap' && parts[1]) return { page: 'roadmap', slug: safeDecode(parts[1]) };
  return { page: 'home' };
}

function safeDecode(s: string): string {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
}

/** `2026-10-24T10:05:00Z` -> `2026-10-24 10:05 UTC`. Any other text is shown as it is. */
export const utcText = (iso: string): string => {
  const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(iso);
  return m ? `${m[1]} ${m[2]} UTC` : iso;
};

export const BANNER_TAIL = "Live sessions and runners show only on the owner's machine.";
export const NEEDS_EMPTY = 'Nothing is waiting for you.';
export const NOTE_TEXT = 'Built from roadmap.md and the plan Trackers and headers on origin.';

export function bannerText(data: ExportData): string {
  const from = data.github ?? 'the repo';
  const at = data.commit ? ` at ${data.commit}` : '';
  const label = data.label ? ` ${data.label}.` : '';
  return `Shared copy: built from ${from}${at}, ${utcText(data.generated_at)}.${label} ${BANNER_TAIL}`;
}
