import type { HubState } from '../types';
import { shippedList } from './strip';

export const BUSY_STATUSES = ['busy', 'running', 'working'];

/** True when a session with this status is at work now. */
export const isBusy = (status: string): boolean => BUSY_STATUSES.includes(status);

export interface Headline {
  title: string;
  sub: string;
}

const plural = (n: number, one: string, many: string): string => `${n} ${n === 1 ? one : many}`;

/** The sentence header of the Inbox and the Overview: what needs the owner, and one line of context. */
export function headline(state: HubState, openCount: number, nowMs: number): Headline {
  const title =
    openCount === 0 ? 'Nothing needs you.' : openCount === 1 ? '1 thing needs you.' : `${openCount} things need you.`;
  const busy = state.sessions.filter((s) => isBusy(s.status)).length;
  const parts = [plural(busy, 'agent working', 'agents working')];
  const ship = shippedList(state, nowMs, 1)[0];
  if (ship) parts.push(`last ship ${ship.age} (${ship.repo} #${ship.pr})`);
  parts.push(plural(state.repos.length, 'repo watched', 'repos watched'));
  return { title, sub: parts.join(' · ') };
}
