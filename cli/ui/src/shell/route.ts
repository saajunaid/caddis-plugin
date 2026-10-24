export type RepoTab = 'flow' | 'roadmap' | 'sessions';

export type Route =
  | { page: 'inbox' }
  | { page: 'overview' }
  | { page: 'repo'; id: string; tab: RepoTab; roadmap: string | null }
  | { page: 'activity' }
  | { page: 'guide' };

/** Hash routes, no router library: `#/inbox`, `#/overview`, `#/repo/<id>[/<tab>[/<slug>]]`. Unknown gives the Inbox. */
export function parseRoute(hash: string): Route {
  const parts = hash.replace(/^#\/?/, '').split('/');
  const head = parts[0];
  if (head === 'overview') return { page: 'overview' };
  if (head === 'activity') return { page: 'activity' };
  if (head === 'guide') return { page: 'guide' };
  if (head === 'repo' && parts[1]) {
    try {
      const tab: RepoTab = parts[2] === 'roadmap' || parts[2] === 'sessions' ? parts[2] : 'flow';
      const roadmap = tab === 'roadmap' && parts[3] ? decodeURIComponent(parts[3]) : null;
      return { page: 'repo', id: decodeURIComponent(parts[1]), tab, roadmap };
    } catch {
      return { page: 'inbox' };
    }
  }
  return { page: 'inbox' };
}

/** The id the hub uses for a repo: `repo_id`, else its path. One definition for every page. */
export const repoId = (r: { repo_id?: string; path: string }): string => r.repo_id ?? r.path;

export const repoHref = (id: string): string => `#/repo/${encodeURIComponent(id)}`;

/** `#/repo/<id>/<tab>` and `#/repo/<id>/roadmap/<slug>` (R47). Flow is the plain repo link. */
export function repoTabHref(id: string, tab: RepoTab, roadmap?: string | null): string {
  if (tab === 'flow') return repoHref(id);
  return `${repoHref(id)}/${tab}${tab === 'roadmap' && roadmap ? `/${encodeURIComponent(roadmap)}` : ''}`;
}
