export type Route =
  | { page: 'inbox' }
  | { page: 'overview' }
  | { page: 'repo'; id: string }
  | { page: 'activity' }
  | { page: 'guide' };

/** Hash routes, no router library: `#/inbox`, `#/overview`, `#/repo/<id>`. Unknown gives the Inbox. */
export function parseRoute(hash: string): Route {
  const parts = hash.replace(/^#\/?/, '').split('/');
  const head = parts[0];
  if (head === 'overview') return { page: 'overview' };
  if (head === 'activity') return { page: 'activity' };
  if (head === 'guide') return { page: 'guide' };
  if (head === 'repo' && parts[1]) {
    try {
      return { page: 'repo', id: decodeURIComponent(parts.slice(1).join('/')) };
    } catch {
      return { page: 'inbox' };
    }
  }
  return { page: 'inbox' };
}

export const repoHref = (id: string): string => `#/repo/${encodeURIComponent(id)}`;
