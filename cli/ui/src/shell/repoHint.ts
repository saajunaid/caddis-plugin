import { samePath } from '../inbox/derive';
import { deriveRoadmaps, gateCount } from '../repo/roadmap';
import type { HubState, RepoState } from '../types';

const BUSY = ['busy', 'running', 'working'];

const plural = (n: number, one: string, many: string): string => `${n} ${n === 1 ? one : many}`;

/** True when an agent session in the repo is at work now. */
export function repoBusy(state: HubState, repo: RepoState): boolean {
  return state.sessions.some((s) => samePath(s.repo_path, repo.path) && BUSY.includes(s.status));
}

/** The short hint after a repo in the nav: the first of gates, a wait on the owner, work, open PRs; else ''. */
export function repoHint(state: HubState, repo: RepoState): string {
  const gates = gateCount(deriveRoadmaps(repo));
  if (gates > 0) return plural(gates, 'gate', 'gates');
  if (state.sessions.some((s) => samePath(s.repo_path, repo.path) && s.waiting_class === 'owner')) return 'waiting on you';
  if (repoBusy(state, repo)) return 'working';
  const prs = repo.github?.prs?.length ?? 0;
  return prs > 0 ? plural(prs, 'PR', 'PRs') : '';
}
