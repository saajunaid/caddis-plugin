export type RepoTab = 'flow' | 'roadmap' | 'sessions';
export type GuideTab = 'poster' | 'details' | 'wall' | 'map';

export type Route =
  | { page: 'inbox'; item: string | null }
  | { page: 'overview' }
  | { page: 'repo'; id: string; tab: RepoTab; roadmap: string | null }
  | { page: 'activity' }
  | { page: 'guide'; tab: GuideTab; item: string | null };

/** Hash routes, no router library: `#/inbox[/<item>]`, `#/overview`, `#/repo/<id>[/<tab>[/<slug>]]`. Unknown gives the Inbox. */
export function parseRoute(hash: string): Route {
  const parts = hash.replace(/^#\/?/, '').split('/');
  const head = parts[0];
  if (head === 'inbox') {
    try {
      return { page: 'inbox', item: parts[1] ? decodeURIComponent(parts[1]) : null };
    } catch {
      return { page: 'inbox', item: null };
    }
  }
  if (head === 'overview') return { page: 'overview' };
  if (head === 'activity') return { page: 'activity' };
  if (head === 'guide') {
    try {
      const tab: GuideTab = parts[1] === 'details' || parts[1] === 'wall' || parts[1] === 'map' ? parts[1] : 'poster';
      const item = parts[2] ? decodeURIComponent(parts[2]) : null;
      return { page: 'guide', tab, item };
    } catch {
      return { page: 'inbox', item: null };
    }
  }
  if (head === 'repo' && parts[1]) {
    try {
      const tab: RepoTab = parts[2] === 'roadmap' || parts[2] === 'sessions' ? parts[2] : 'flow';
      const roadmap = tab === 'roadmap' && parts[3] ? decodeURIComponent(parts[3]) : null;
      return { page: 'repo', id: decodeURIComponent(parts[1]), tab, roadmap };
    } catch {
      return { page: 'inbox', item: null };
    }
  }
  return { page: 'inbox', item: null };
}

/** The id the hub uses for a repo: `repo_id`, else its path. One definition for every page. */
export const repoId = (r: { repo_id?: string; path: string }): string => r.repo_id ?? r.path;

/** `#/inbox/<id>`: the Inbox with that item selected. Ids hold `:` and `/`, so the id is escaped. */
export const inboxItemHref = (id: string): string => `#/inbox/${encodeURIComponent(id)}`;

export const repoHref = (id: string): string => `#/repo/${encodeURIComponent(id)}`;

/** `#/repo/<id>/<tab>` and `#/repo/<id>/roadmap/<slug>` (R47). Flow is the plain repo link. */
export function repoTabHref(id: string, tab: RepoTab, roadmap?: string | null): string {
  if (tab === 'flow') return repoHref(id);
  return `${repoHref(id)}/${tab}${tab === 'roadmap' && roadmap ? `/${encodeURIComponent(roadmap)}` : ''}`;
}

export function guideHref(tab: GuideTab, item?: string | null): string {
  if (tab === 'poster') return '#/guide';
  if (tab === 'wall') return '#/guide/wall';
  if (tab === 'map') return '#/guide/map';
  return `#/guide/details${item ? `/${encodeURIComponent(item)}` : ''}`;
}
