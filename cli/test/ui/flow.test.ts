import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import type { QueueEntry } from '../../ui/src/inbox/derive';
import { deriveLane } from '../../ui/src/overview/lanes';
import { deriveFlow, flowMode, orderQueue } from '../../ui/src/repo/flow';
import type { HubState } from '../../ui/src/types';

const load = (name: string): HubState =>
  JSON.parse(readFileSync(new URL(`../fixtures/hub-state/${name}.json`, import.meta.url), 'utf8')) as HubState;

const q = (pr: number, over: Partial<QueueEntry> = {}): QueueEntry => ({
  pr,
  headSha: 'A'.repeat(40),
  title: `t${pr}`,
  state: 'waiting',
  whyWaiting: '',
  waitsOn: [],
  hotfix: false,
  held: false,
  since: null,
  ...over,
});

describe('orderQueue (queue_order of caddis_coordinate.py)', () => {
  it('merging first, then hotfix, then ready by time, then the rest in add order', () => {
    const items = [
      q(1),
      q(2, { state: 'ready', since: '2026-10-24T10:05:00Z' }),
      q(3, { state: 'ready', since: '2026-10-24T10:01:00Z' }),
      q(4, { hotfix: true }),
      q(5, { state: 'merging' }),
      q(6, { state: 'ready', since: '2026-10-24T10:00:00Z', held: true }),
      q(7, { state: 'ready', hotfix: true, since: '2026-10-24T10:09:00Z' }),
      q(8, { state: 'ready' }),
    ];
    expect(orderQueue(items).map((x) => x.pr)).toEqual([5, 7, 4, 3, 2, 8, 1, 6]);
  });
});

describe('deriveFlow', () => {
  it('a live coordinator: ordered queue with flags, merging now, D1-D5, waits_on, unqueued PRs', () => {
    const s = load('full');
    const shop = s.repos[0]!;
    shop.coordinator!.status = 'live';
    shop.coordinator!.merging_now = 215;
    (shop.coordinator!.queue[1] as Record<string, unknown>).waits_on = [{ repo: 'acme__billing', pr: 77 }];
    (shop.coordinator!.deploy_checks[0] as Record<string, unknown>).checks = { D1: 'pass', D2: 'pass', D3: 'skip', D4: 'fail' };
    (shop.coordinator!.deploy_checks[0] as Record<string, unknown>).reason = 'version endpoint sha differs';
    const f = deriveFlow(s, shop);
    expect(f.mode).toBe('live');
    expect(f.grey).toBe(false);
    expect(f.merging).toBe(215);
    expect(f.queue.map((x) => [x.position, x.pr, x.merging])).toEqual([
      [1, 215, true],
      [2, 213, false],
      [3, 214, false],
      [4, 212, false],
    ]);
    expect(f.queue[1]!.waitsOn).toEqual([{ repo: 'acme__billing', pr: 77 }]);
    expect(f.queue[2]!.held).toBe(true);
    expect(f.deploys[0]!.checks).toEqual([
      { name: 'D1', mark: 'pass' },
      { name: 'D2', mark: 'pass' },
      { name: 'D3', mark: 'skip' },
      { name: 'D4', mark: 'fail' },
      { name: 'D5', mark: 'skip' },
    ]);
    expect(f.deploys[0]!.reason).toBe('version endpoint sha differs');
    expect(f.unqueued.map((p) => p.number)).toEqual([]);
    expect(f.statusText).toMatch(/^Coordinator demo-coordinator live, heartbeat /);
  });

  it('an old deploy check without marks shows health only', () => {
    const s = load('full');
    expect(deriveFlow(s, s.repos[0]!).deploys[0]!.checks).toBeNull();
  });

  it('stopped and down coordinators grey the last known queue with their text', () => {
    const s = load('full');
    const shop = s.repos[0]!;
    shop.coordinator!.status = 'stopped';
    shop.coordinator!.responding = false;
    shop.coordinator!.stopped_at = '2026-10-24T10:40:00Z';
    let f = deriveFlow(s, shop);
    expect([f.mode, f.grey, f.merging]).toEqual(['stopped', true, null]);
    expect(f.statusText).toMatch(/^Coordinator stopped at /);
    shop.coordinator!.status = 'down';
    f = deriveFlow(s, shop);
    expect(f.mode).toBe('down');
    expect(f.statusText).toMatch(/^Coordinator not responding since /);
  });

  it('no coordinator: open PRs are listed as not in the queue', () => {
    const s = load('no-coordinator');
    const r = s.repos.find((x) => (x.github?.prs ?? []).length > 0)!;
    const f = deriveFlow(s, r);
    expect(flowMode(r)).toBe('none');
    expect(f.statusText).toContain('No coordinator');
    expect(f.unqueued.length).toBeGreaterThan(0);
  });
});

describe('Overview lanes: a clean stop (R36)', () => {
  it('gives the stopped text, greys the queue and keeps the lane idle, not blocked', () => {
    const s = load('full');
    const shop = s.repos[0]!;
    shop.coordinator!.status = 'stopped';
    shop.coordinator!.responding = false;
    shop.coordinator!.stopped_at = '2026-10-24T10:40:00Z';
    const lane = deriveLane(s, shop, Date.parse(s.generated_at));
    expect(lane.mode).toBe('stopped');
    expect(lane.summary).toMatch(/^Coordinator stopped at /);
    expect(lane.note).toContain('last known queue is greyed');
    const waiting = lane.columns.find((c) => c.id === 'waiting')!.cards;
    expect(waiting.length).toBeGreaterThan(0);
    expect(waiting.every((c) => c.grey && c.queue)).toBe(true);
    expect(lane.tone).not.toBe('blocked');
  });

  it('a live lane gives queue cards their buttons data', () => {
    const s = load('full');
    s.repos[0]!.coordinator!.status = 'live';
    const lane = deriveLane(s, s.repos[0]!, Date.parse(s.generated_at));
    const card = lane.columns.find((c) => c.id === 'waiting')!.cards.find((c) => c.key === 'q213')!;
    expect(card.queue).toEqual({ pr: 213, headSha: 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA213', hotfix: false, held: false });
  });
});
