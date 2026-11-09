import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { repoBusy, repoHint } from '../../ui/src/shell/repoHint';
import type { HubState, RepoState } from '../../ui/src/types';

const full = JSON.parse(readFileSync(new URL('../fixtures/hub-state/full.json', import.meta.url), 'utf8')) as HubState;
const shop = full.repos.find((r) => r.name === 'shop')!;

type Session = HubState['sessions'][number];
const session = (over: Partial<Session>): Session =>
  ({ ...full.sessions[0]!, repo_path: shop.path, status: 'idle', waiting_class: null, ...over }) as Session;

/** A clone of shop with no roadmaps or plans and `prs` open PRs, in a state with the given sessions. */
function world(prs: number, sessions: Session[]): { state: HubState; repo: RepoState } {
  const base = shop.github!.prs!;
  const repo = {
    ...shop,
    roadmaps: null,
    plans: null,
    github: { ...shop.github!, prs: Array.from({ length: prs }, (_, i) => base[i % base.length]!) },
  } as RepoState;
  return { state: { ...full, repos: [repo], sessions }, repo };
}

describe('repoHint', () => {
  it('shows the gate count first', () => {
    expect(repoHint(full, shop)).toBe('1 gate');
  });

  it('falls through to open PRs, a busy session and an owner wait', () => {
    const prs = world(2, []);
    expect(repoHint(prs.state, prs.repo)).toBe('2 PRs');
    const busy = world(2, [session({ status: 'busy' })]);
    expect(repoHint(busy.state, busy.repo)).toBe('working');
    const wait = world(2, [session({ status: 'busy' }), session({ status: 'waiting', waiting_class: 'owner' })]);
    expect(repoHint(wait.state, wait.repo)).toBe('waiting on you');
  });

  it('is empty with no PRs and no sessions', () => {
    const none = world(0, []);
    expect(repoHint(none.state, none.repo)).toBe('');
  });

  it('repoBusy sees a busy session in the repo', () => {
    expect(repoBusy(full, shop)).toBe(true);
  });
});
