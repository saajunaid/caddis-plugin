import { KIND_LABEL, asArray, repoLabel, samePath, type InboxItem } from '../inbox/derive';
import { ageText } from '../shell/format';
import { guideHref, repoId, repoTabHref, type GuideTab, type RepoTab } from '../shell/route';
import type { HubState, RepoState } from '../types';

/** The "Jump to anything" palette (Ctrl K): one flat list of places and actions, built from one state snapshot. */
export type PaletteGroup = 'Pages' | 'Repos' | 'Roadmaps' | 'Pull requests' | 'Sessions' | 'Inbox';
export const GROUP_ORDER: PaletteGroup[] = ['Pages', 'Repos', 'Roadmaps', 'Pull requests', 'Sessions', 'Inbox'];

export type PaletteAction = { kind: 'route'; href: string } | { kind: 'url'; url: string } | { kind: 'copy'; text: string };

export interface PaletteItem {
  /** Unique in one list: the React key and the option id. */
  id: string;
  group: PaletteGroup;
  label: string;
  /** Short context on the right of the row: the repo, a status. */
  hint: string;
  /** More words the query can match (repo names, kind). Never shown. */
  keywords: string[];
  action: PaletteAction;
}

const PAGES: [string, string, string[]][] = [
  ['Inbox', '#/inbox', ['home', 'needs you']],
  ['Overview', '#/overview', ['repos', 'cards']],
  ['Activity', '#/activity', ['merges', 'audit']],
];
const GUIDE: [GuideTab, string][] = [
  ['poster', 'Poster'],
  ['details', 'Details'],
  ['wall', 'Wall poster'],
  ['map', 'Map'],
];
const TABS: [RepoTab, string][] = [
  ['flow', 'Flow'],
  ['roadmap', 'Roadmap'],
  ['sessions', 'Sessions'],
];

const rec = (v: unknown): Record<string, unknown> => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {});
const str = (v: unknown): string | null => (typeof v === 'string' && v ? v : null);

/** The roadmap slugs the collector could read (an entry with `error` is left out, as on the Roadmap tab). */
function roadmapSlugs(repo: RepoState): string[] {
  return asArray(rec(repo.roadmaps).roadmaps)
    .map(rec)
    .filter((e) => !str(e.error))
    .map((e) => str(e.roadmap))
    .filter((s): s is string => s !== null);
}

/** Names a repo is known by, for matching: the folder name and `owner/name`. */
const repoWords = (r: RepoState): string[] => [...new Set([r.name, repoLabel(r)])];

/**
 * Every palette item, in group order: pages, repo tabs, roadmaps, open PRs, sessions, Inbox items. Pure.
 * Plans without a roadmap have no route of their own (the Roadmap tab lists them), so they are not items.
 * The Inbox selects its row in local state only, so an Inbox item opens the Inbox.
 */
export function buildPaletteItems(state: HubState, inbox: InboxItem[], now: number): PaletteItem[] {
  const out: PaletteItem[] = [];
  for (const [label, href, keywords] of PAGES) {
    out.push({ id: `page:${href}`, group: 'Pages', label, hint: 'Page', keywords, action: { kind: 'route', href } });
  }
  for (const [tab, name] of GUIDE) {
    const href = guideHref(tab);
    out.push({ id: `page:${href}`, group: 'Pages', label: `Guide · ${name}`, hint: 'caddis guide', keywords: ['caddis guide', 'help'], action: { kind: 'route', href } });
  }

  for (const r of state.repos) {
    const id = repoId(r);
    for (const [tab, name] of TABS) {
      out.push({
        id: `repo:${id}:${tab}`,
        group: 'Repos',
        label: `${r.name} · ${name}`,
        hint: repoLabel(r),
        keywords: [repoLabel(r)],
        action: { kind: 'route', href: repoTabHref(id, tab) },
      });
    }
  }

  for (const r of state.repos) {
    const id = repoId(r);
    for (const slug of roadmapSlugs(r)) {
      out.push({ id: `roadmap:${id}:${slug}`, group: 'Roadmaps', label: slug, hint: r.name, keywords: [...repoWords(r), 'roadmap'], action: { kind: 'route', href: repoTabHref(id, 'roadmap', slug) } });
    }
  }

  for (const r of state.repos) {
    for (const pr of r.github?.prs ?? []) {
      out.push({
        id: `pr:${repoId(r)}:${pr.number}`,
        group: 'Pull requests',
        label: `#${pr.number} ${pr.title}`,
        hint: pr.draft ? `${r.name} · draft` : r.name,
        keywords: [...repoWords(r), 'pr', 'pull request'],
        action: { kind: 'url', url: pr.url },
      });
    }
  }

  for (const s of state.sessions) {
    const name = s.name ?? s.session_id;
    const repo = state.repos.find((r) => samePath(r.path, s.repo_path));
    const where = repo?.name ?? null;
    out.push({
      id: `session:${s.key}`,
      group: 'Sessions',
      label: name,
      hint: where ? `${where} · ${s.status}` : s.status,
      keywords: [...(repo ? repoWords(repo) : []), 'session', s.session_id],
      action: { kind: 'copy', text: name },
    });
  }

  for (const i of inbox) {
    const age = i.since ? ` · ${ageText(i.since, now)}` : '';
    out.push({
      id: `inbox:${i.id}`,
      group: 'Inbox',
      label: i.title,
      hint: `${KIND_LABEL[i.kind]} · ${i.repo}${age}`,
      keywords: [i.repo, KIND_LABEL[i.kind], 'inbox'],
      action: { kind: 'route', href: '#/inbox' },
    });
  }
  return out;
}
