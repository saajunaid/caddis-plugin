import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
  coordinatorDownText,
  deriveLane,
  deriveLanes,
  NO_COORDINATOR_HINT,
  NO_COORDINATOR_TEXT,
} from '../../ui/src/overview/lanes';
import type { HubState } from '../../ui/src/types';

const load = (name: string): HubState =>
  JSON.parse(readFileSync(new URL(`../fixtures/hub-state/${name}.json`, import.meta.url), 'utf8')) as HubState;
const now = (s: HubState): number => Date.parse(s.generated_at);
const col = (lane: ReturnType<typeof deriveLane>, id: string) => lane.columns.find((c) => c.id === id)!;
const titles = (lane: ReturnType<typeof deriveLane>, id: string) => col(lane, id).cards.map((c) => c.title);

describe('lane bucketing (full fixture)', () => {
  const s = load('full');
  const [shop, billing, docs] = deriveLanes(s, now(s));

  it('makes one lane per repo with the five columns in order', () => {
    expect(deriveLanes(s, now(s)).map((l) => l.name)).toEqual(['acme/shop', 'acme/billing', 'acme/docs']);
    expect(shop!.columns.map((c) => c.title)).toEqual([
      'Sessions', 'Blocked', 'Waiting for its turn', 'Merging now', 'Done and deployed',
    ]);
  });

  it('buckets the shop lane', () => {
    expect(shop!.mode).toBe('coordinator');
    expect(titles(shop!, 'sessions')).toEqual(['demo-session-api', 'demo-session-web', 'demo-session-peer']);
    expect(col(shop!, 'sessions').cards[0]!.sub).toBe('waiting: permission prompt');
    expect(titles(shop!, 'blocked')).toEqual(['#212 retry flaky upload']);
    expect(titles(shop!, 'waiting')).toEqual(['#215 hotfix: cart total', '#213 search filters', '#214 coordinator config']);
    expect(col(shop!, 'waiting').cards[0]!.sub).toContain('hotfix');
    expect(titles(shop!, 'done')).toEqual(['#209 checkout copy']);
    expect(col(shop!, 'done').cards[0]!.sub).toBe('deployed 18 min ago');
    expect(shop!.tone).toBe('attention');
  });

  it('puts the queue entry being merged under Merging now', () => {
    const m = structuredClone(s);
    m.repos[0]!.coordinator!.merging_now = 215;
    const lane = deriveLane(m, m.repos[0]!, now(m));
    expect(titles(lane, 'merging')).toEqual(['#215 hotfix: cart total']);
    expect(titles(lane, 'waiting')).not.toContain('#215 hotfix: cart total');
    m.repos[0]!.coordinator!.merging_now = { pr: 213 };
    expect(titles(deriveLane(m, m.repos[0]!, now(m)), 'merging')).toEqual(['#213 search filters']);
  });

  it('summarises a lane in one line', () => {
    expect(shop!.summary).toBe('3 sessions · 1 blocked · 3 waiting · 1 deployed');
  });

  it('a no-coordinator lane buckets from GitHub only', () => {
    expect(docs!.mode).toBe('none');
    expect(titles(docs!, 'blocked')).toEqual(['#88 new install page']);
    expect(col(docs!, 'blocked').cards[0]!.sub).toBe('lint failed');
    expect(titles(docs!, 'done')).toEqual(['#86 fix links']);
    expect(col(docs!, 'sessions').cards).toEqual([col(docs!, 'sessions').cards[0]]);
    expect(billing!.mode).toBe('down');
  });
});

describe('degraded lane texts', () => {
  it('shows the no-coordinator text and the hint', () => {
    const s = load('no-coordinator');
    const lane = deriveLanes(s, now(s))[0]!;
    expect(lane.mode).toBe('none');
    expect(col(lane, 'waiting').emptyText).toBe('No coordinator: each session merges its own PRs.');
    expect(NO_COORDINATOR_TEXT).toBe('No coordinator: each session merges its own PRs.');
    expect(lane.note).toContain(NO_COORDINATOR_TEXT);
    expect(lane.note).toContain('/caddis:coordinate');
    expect(NO_COORDINATOR_HINT).toBe('/caddis:coordinate');
    expect(lane.summary.startsWith('No coordinator')).toBe(true);
  });

  it('shows "Coordinator not responding since <time>" and greys the last known queue', () => {
    const s = load('full');
    const lane = deriveLanes(s, now(s))[1]!;
    const heartbeat = s.repos[1]!.coordinator!.heartbeat_at;
    expect(lane.mode).toBe('down');
    expect(lane.summary).toBe(coordinatorDownText(heartbeat));
    expect(lane.summary).toMatch(/^Coordinator not responding since \d/);
    expect(lane.note).toContain('last known queue is greyed');
    const waiting = col(lane, 'waiting').cards;
    expect(waiting.map((c) => c.title)).toEqual(['#77 invoice v2']);
    expect(waiting.every((c) => c.grey && c.sub === 'last known queue')).toBe(true);
    expect(lane.tone).toBe('blocked');
  });

  it('a down coordinator with no heartbeat time says unknown', () => {
    expect(coordinatorDownText(null)).toBe('Coordinator not responding since unknown');
  });

  it('a coordinator that is back loses the down text', () => {
    const s = structuredClone(load('full'));
    s.repos[1]!.coordinator!.responding = true;
    const lane = deriveLane(s, s.repos[1]!, now(s));
    expect(lane.mode).toBe('coordinator');
    expect(lane.summary).not.toContain('not responding');
    expect(col(lane, 'waiting').cards[0]!.grey).toBe(false);
  });

  it('shows a GitHub error note on the lane', () => {
    const s = load('degraded');
    const lane = deriveLanes(s, now(s))[0]!;
    expect(lane.github).toEqual({ account: 'demo', error: 'gh auth failed for account demo', command: 'gh auth login -h github.com' });
    expect(lane.tone).toBe('blocked');
  });

  it('shows no lanes for the empty fixture', () => {
    const s = load('empty');
    expect(deriveLanes(s, now(s))).toEqual([]);
  });

  it('a repo with no sessions says so', () => {
    const s = load('no-coordinator');
    s.sessions = [];
    const lane = deriveLanes(s, now(s))[0]!;
    expect(col(lane, 'sessions').emptyText).toBe('No sessions running');
    expect(lane.summary).toContain('no sessions running');
  });
});

describe('sessions unknown when claude agents fails', () => {
  it('says unknown instead of "No sessions running"', () => {
    const s = load('degraded');
    const lane = deriveLanes(s, now(s))[0]!;
    expect(lane.summary).toContain('sessions unknown');
    expect(col(lane, 'sessions').emptyText).toContain('unknown');
  });
  it('a healthy source with no sessions still says "No sessions running"', () => {
    const s = load('no-coordinator');
    s.sessions = [];
    expect(col(deriveLanes(s, now(s))[0]!, 'sessions').emptyText).toBe('No sessions running');
  });
  it('a repo with working gh has no github note', () => {
    const s = load('full');
    expect(deriveLanes(s, now(s)).every((l) => l.github === null)).toBe(true);
  });
});
