import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
  disabledReason,
  ownerDisabledReason,
  ownerSpecs,
  queueSpecs,
  requestFor,
  requestText,
  statusLine,
} from '../../ui/src/actions/model';
import { deriveInbox } from '../../ui/src/inbox/derive';
import { quotaLow, quotaLowest } from '../../ui/src/shell/format';
import type { HubState, OwnerItem, RepoState, RequestView } from '../../ui/src/types';

const load = (name: string): HubState =>
  JSON.parse(readFileSync(new URL(`../fixtures/hub-state/${name}.json`, import.meta.url), 'utf8')) as HubState;
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
const SHA = 'A'.repeat(40);

function shop(): RepoState {
  const r = clone(load('full').repos[0]!);
  r.actions = { enabled: true, code: 'ok', reason: null };
  return r;
}

const view = (over: Partial<RequestView>): RequestView => ({
  id: 'r1',
  action: 'hold',
  pr: 215,
  head_sha: SHA,
  what: null,
  created_at: '2026-10-24T10:49:00Z',
  expires_at: '2026-10-24T11:19:00Z',
  status: 'requested',
  reason: null,
  at: null,
  ...over,
});

describe('which buttons an item gets', () => {
  it('a queue item gets hotfix or unhotfix, and hold or release', () => {
    const r = shop();
    const plain = queueSpecs(r, { pr: 213, headSha: SHA, hotfix: false, held: false });
    expect(plain.map((s) => s.body.action)).toEqual(['hotfix', 'hold']);
    expect(plain[0]!.body).toEqual({ repo_id: 'acme__shop', action: 'hotfix', pr: 213, head_sha: 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA213' });
    const flagged = queueSpecs(r, { pr: 215, headSha: SHA, hotfix: true, held: true });
    expect(flagged.map((s) => s.label)).toEqual(['Unmark hotfix', 'Release']);
  });

  it('a queue item sends the current GitHub head, not the queue head that lags a push', () => {
    const r = shop();
    const old = 'B'.repeat(40);
    const [hot] = queueSpecs(r, { pr: 213, headSha: old, hotfix: false, held: false });
    expect(hot!.body.head_sha).toBe('AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA213');
    const [gone] = queueSpecs(r, { pr: 999, headSha: old, hotfix: false, held: false });
    expect(gone!.body.head_sha).toBe(old);
  });

  it('an owner item for a PR that is not queued has its buttons off with the reason', () => {
    const r = shop();
    const item: OwnerItem = { id: 'ask:1', what: 'w', pr: 216, head_sha: null, source: 'coordinator', recommendation: null, from: null, since: null };
    expect(ownerDisabledReason(r, item)).toBe('PR #216 is not in the coordinator queue.');
    expect(ownerDisabledReason(r, { ...item, pr: 213 })).toBeNull();
    expect(ownerDisabledReason(r, { ...item, pr: null })).toBeNull();
    r.actions = { enabled: false, code: 'no_coordinator', reason: 'The coordinator stopped.' };
    expect(ownerDisabledReason(r, item)).toBe('The coordinator stopped.');
  });

  it('no repo id or no head gives no buttons', () => {
    const r = shop();
    expect(queueSpecs(r, { pr: 1, headSha: '', hotfix: false, held: false })).toEqual([]);
    delete r.repo_id;
    expect(queueSpecs(r, { pr: 1, headSha: SHA, hotfix: false, held: false })).toEqual([]);
  });

  it('an owner item gets approve and decline with its what; a PR item takes the current head', () => {
    const r = shop();
    const noPr: OwnerItem = { id: 'gate:g:P2-OG1', what: 'owner gate P2-OG1 (g)', pr: null, head_sha: null, source: 'relay', recommendation: null, from: null, since: null };
    expect(ownerSpecs(r, noPr).map((s) => s.body)).toEqual([
      { repo_id: 'acme__shop', action: 'approve', pr: null, head_sha: null, what: 'owner gate P2-OG1 (g)' },
      { repo_id: 'acme__shop', action: 'decline', pr: null, head_sha: null, what: 'owner gate P2-OG1 (g)' },
    ]);
    const withPr: OwnerItem = { ...noPr, id: 'ask:1', what: 'schema change', pr: 214, head_sha: 'x', source: 'coordinator' };
    expect(ownerSpecs(r, withPr)[0]!.body.head_sha).toBe('AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA214');
    // Approve and decline share one key: one status line per item.
    expect(new Set(ownerSpecs(r, withPr).map((s) => s.key)).size).toBe(1);
  });
});

describe('disabled reasons', () => {
  it('give the server sentence for none, stopped and down', () => {
    const r = shop();
    expect(disabledReason(r)).toBeNull();
    for (const reason of ['No coordinator: each session merges its own PRs.', 'The coordinator stopped.', 'The coordinator is not responding.']) {
      r.actions = { enabled: false, code: 'no_coordinator', reason };
      expect(disabledReason(r)).toBe(reason);
    }
    delete (r as Partial<RepoState>).actions;
    expect(disabledReason(r)).toBe('Actions need a live coordinator.');
  });
});

describe('request lifecycle text (R38)', () => {
  it('has one line per step', () => {
    expect(requestText(view({}))).toBe('Hold: requested. Waiting for the coordinator.');
    expect(requestText(view({ status: 'done' }))).toBe('Hold: done.');
    expect(requestText(view({ status: 'rejected', reason: 'head moved' }))).toBe('Hold: rejected: head moved.');
    expect(requestText(view({ status: 'expired' }))).toContain('expired');
    expect(requestText(view({ status: 'not_picked_up' }))).toBe('Hold: not picked up. The coordinator has not read requests for 2 min.');
  });

  it('matches the newest request of the same family and target', () => {
    const r = shop();
    r.coordinator!.requests = [
      view({ id: 'a', action: 'hold', status: 'done' }),
      view({ id: 'b', action: 'release', status: 'rejected', reason: 'not in queue' }),
      view({ id: 'c', action: 'hotfix', status: 'requested' }),
      view({ id: 'd', action: 'hold', pr: 213 }),
    ];
    const [hot, hold] = queueSpecs(r, { pr: 215, headSha: SHA, hotfix: false, held: false });
    expect(requestFor(r, hold!)!.id).toBe('b');
    expect(requestFor(r, hot!)!.id).toBe('c');
  });

  it('the local click shows first, then the server view once it has the request', () => {
    const r = shop();
    const [, hold] = queueSpecs(r, { pr: 215, headSha: SHA, hotfix: false, held: false });
    expect(statusLine(r, hold!, undefined)).toBeNull();
    expect(statusLine(r, hold!, { status: 'sending', reason: null, requestId: null, at: 0 })!.text).toBe('Hold: sending...');
    expect(statusLine(r, hold!, { status: 'refused', reason: 'The head of PR #215 moved.', requestId: null, at: 0 })).toEqual({
      text: 'Hold: refused. The head of PR #215 moved.',
      tone: 'bad',
    });
    const sent = { status: 'sent' as const, reason: null, requestId: 'new', at: 0 };
    expect(statusLine(r, hold!, sent)!.text).toBe('Hold: requested. Waiting for the coordinator.');
    r.coordinator!.requests = [view({ id: 'new', status: 'done' })];
    expect(statusLine(r, hold!, sent)).toEqual({ text: 'Hold: done.', tone: 'good' });
  });
});

describe('inbox approvals (R37)', () => {
  it('takes owner items from owner_items, with the recommendation', () => {
    const s = load('full');
    s.repos[0]!.owner_items = [
      {
        id: 'ask:ask-1',
        what: 'overnight agy run',
        pr: null,
        head_sha: null,
        source: 'coordinator',
        recommendation: { decision: 'hold', reason: 'Over the cap.', evidence: 'EUR 80' },
        from: 'demo-coordinator',
        since: '2026-10-24T10:40:00Z',
      },
    ];
    const items = deriveInbox(s, Date.parse(s.generated_at)).items.filter((i) => i.kind === 'owner-gate');
    expect(items.map((i) => [i.id, i.title, i.folder])).toEqual([['owner:/srv/demo/shop:ask:ask-1', 'overnight agy run', 'approvals']]);
    expect(items[0]!.owner!.recommendation!.decision).toBe('hold');
  });

  it('falls back to relay gates when the state has no owner_items, marked from the relay', () => {
    const s = load('full');
    const items = deriveInbox(s, Date.parse(s.generated_at)).items.filter((i) => i.kind === 'owner-gate');
    expect(items).toHaveLength(1);
    expect(items[0]!.owner).toMatchObject({ what: 'owner gate P2-OG1 (shop-schema)', source: 'relay', from: 'shop-schema' });
  });

  it('a blocked queue entry carries its queue data for Hold', () => {
    const s = load('full');
    const merge = deriveInbox(s, Date.parse(s.generated_at)).items.find((i) => i.id === 'merge:/srv/demo/shop:212')!;
    expect(merge.queue).toEqual({ pr: 212, headSha: 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA212', hotfix: false, held: false });
  });

  it('a clean coordinator stop gives no coordinator-problem item', () => {
    const s = load('full');
    const down = s.repos.find((r) => r.coordinator && !r.coordinator.responding)!;
    const count = () => deriveInbox(s, Date.parse(s.generated_at)).items.filter((i) => i.kind === 'coordinator').length;
    expect(count()).toBe(1);
    down.coordinator!.status = 'stopped';
    expect(count()).toBe(0);
  });
});

describe('footer quota (R40)', () => {
  it('shows the lowest quota always, and the warning only below 500', () => {
    const s = load('full');
    expect(quotaLowest(s)).toBeNull();
    s.github_rate = { a: { remaining: 4000, reset_at: null }, b: { remaining: 2500, reset_at: null } };
    expect(quotaLowest(s)).toEqual({ account: 'b', remaining: 2500, resetAt: null });
    expect(quotaLow(s)).toBeNull();
    s.github_rate.b = { remaining: 120, reset_at: null };
    expect(quotaLow(s)!.remaining).toBe(120);
  });
});
