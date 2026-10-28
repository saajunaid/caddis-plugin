import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
  deriveInbox,
  emptyHistory,
  reconcile,
  RESOLVED_TTL_MS,
  sanitizeHistory,
  withFrozen,
  type InboxItem,
} from '../../ui/src/inbox/derive';
import { HISTORY_KEY, loadHistory, loadIdSet, saveHistory, saveIdSet } from '../../ui/src/inbox/store';
import type { HubState } from '../../ui/src/types';

const load = (name: string): HubState =>
  JSON.parse(readFileSync(new URL(`../fixtures/hub-state/${name}.json`, import.meta.url), 'utf8')) as HubState;
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;
const at = (s: HubState): number => Date.parse(s.generated_at);

const kinds = (s: HubState) => deriveInbox(s, at(s)).items.map((i) => i.kind).sort();
const ids = (s: HubState) => deriveInbox(s, at(s)).items.map((i) => i.id);

describe('deriveInbox: the six kinds', () => {
  const full = load('full');

  it('derives every kind from its source in the full fixture', () => {
    const items = deriveInbox(full, at(full)).items;
    const byKind = (k: string) => items.filter((i) => i.kind === k);
    expect(byKind('waiting').map((i) => i.title)).toEqual([
      'demo-session-api waits on permission prompt',
      'demo-session-export waits on question',
    ]);
    expect(byKind('owner-gate')).toHaveLength(1);
    expect(byKind('owner-gate')[0]!.title).toContain('P2-OG1');
    expect(byKind('blocked')).toHaveLength(1);
    expect(byKind('blocked')[0]!.repo).toBe('acme/billing');
    // PR 212 is both a failed-check PR and a blocked queue entry: one item. PR 88 has no coordinator.
    expect(byKind('blocked-merge').map((i) => i.id).sort()).toEqual(['merge:/srv/demo/docs:88', 'merge:/srv/demo/shop:212']);
    expect(byKind('coordinator')).toHaveLength(1);
    expect(byKind('coordinator')[0]!.title).toMatch(/^Coordinator not responding since /);
    expect(byKind('hub')).toHaveLength(0);
  });

  it('skips a peer wait and an unconfirmed (not debounced) wait', () => {
    const titles = deriveInbox(full, at(full)).items.map((i) => i.title).join('|');
    expect(titles).not.toContain('demo-session-peer');
    expect(titles).not.toContain('demo-session-new');
  });

  it('a waiting session appears only after the server debounce flag', () => {
    const s = clone(full);
    const api = s.sessions.find((x) => x.name === 'demo-session-api')!;
    api.waiting_class = null;
    expect(ids(s)).not.toContain(`waiting:${api.session_id}`);
    api.waiting_class = 'owner';
    expect(ids(s)).toContain(`waiting:${api.session_id}`);
  });

  it('the same session twice gives one item', () => {
    const s = clone(full);
    s.sessions.push({ ...s.sessions[0]!, key: '9:dup' });
    const waiting = deriveInbox(s, at(s)).items.filter((i) => i.id === `waiting:${s.sessions[0]!.session_id}`);
    expect(waiting).toHaveLength(1);
  });

  it('resolves each kind when its source clears', () => {
    const s = clone(full);
    for (const x of s.sessions) x.waiting_class = null;
    for (const r of s.repos) {
      r.relays = { schema: 1, relays: [] };
      for (const p of r.github?.prs ?? []) p.required_state = 'pass';
      if (r.coordinator) {
        r.coordinator.responding = true;
        r.coordinator.queue = r.coordinator.queue.filter((q) => (q as { state: string }).state !== 'blocked');
      }
    }
    expect(deriveInbox(s, at(s)).items).toEqual([]);
  });

  it('a hub problem appears for a source that is failing and stale, and clears when it is back', () => {
    const d = load('degraded');
    const hub = deriveInbox(d, at(d)).items.filter((i) => i.kind === 'hub');
    expect(hub.map((i) => i.id)).toEqual(['hub:agents']);
    expect(hub[0]!.why).toContain('timed out');
    d.sources.agents = { ok: true, last_ok_at: d.generated_at, last_error: null, stale: false };
    expect(deriveInbox(d, at(d)).items.filter((i) => i.kind === 'hub')).toEqual([]);
  });

  it('a stale but ok source is not a hub problem', () => {
    const d = load('degraded');
    expect(ids(d)).not.toContain('hub:github');
  });

  it('a repo with no coordinator still yields waiting, owner-gate, blocked and blocked-merge', () => {
    const s = clone(load('no-coordinator'));
    const repo = s.repos[0]!;
    s.sessions[0]!.waiting_class = 'owner';
    s.sessions[0]!.waiting_for = 'question';
    repo.relays = {
      schema: 1,
      relays: [
        { name: 'docs-a', status: 'OWNER-GATE', status_arg: 'P1-OG1', updated_at: s.generated_at },
        { name: 'docs-b', status: 'BLOCKED', status_arg: 'owner', updated_at: s.generated_at },
      ],
    };
    expect(kinds(s)).toEqual(['blocked', 'blocked-merge', 'owner-gate', 'waiting']);
    // A coordinator problem needs a coordinator.
    expect(ids(s).some((i) => i.startsWith('coordinator:'))).toBe(false);
  });

  it('BLOCKED for someone other than the owner is not an item', () => {
    const s = clone(full);
    s.repos[1]!.relays = { schema: 1, relays: [{ name: 'x', status: 'BLOCKED', status_arg: 'peer', updated_at: s.generated_at }] };
    expect(deriveInbox(s, at(s)).items.some((i) => i.kind === 'blocked')).toBe(false);
  });

  it('a draft PR with failed checks is not a blocked merge', () => {
    const s = clone(load('no-coordinator'));
    s.repos[0]!.github!.prs![0]!.draft = true;
    expect(deriveInbox(s, at(s)).items).toEqual([]);
  });

  it('the empty fixture shows nothing and zero tiles', () => {
    const e = load('empty');
    const m = deriveInbox(e, at(e));
    expect(m.items).toEqual([]);
    expect(m.tiles).toEqual({ waitingOnYou: 0, blockedMerges: 0, inQueue: 0, workingSessions: 0, lastDeploy: null });
  });
});

describe('ids and tiles', () => {
  const full = load('full');
  it('ids are stable across polls and time', () => {
    const a = ids(full);
    const later = clone(full);
    later.generated_at = '2026-10-24T10:51:00Z';
    expect(deriveInbox(later, at(later)).items.map((i) => i.id)).toEqual(a);
    expect(new Set(a).size).toBe(a.length);
  });

  it('computes the five tiles from the full fixture', () => {
    const t = deriveInbox(full, at(full)).tiles;
    expect(t.waitingOnYou).toBe(4); // 2 sessions + 1 blocked relay + 1 coordinator problem
    expect(t.blockedMerges).toBe(2);
    expect(t.inQueue).toBe(3); // shop: 215, 213, 214 (212 is blocked); billing's coordinator is down, so 77 is not counted
    expect(t.workingSessions).toBe(5);
    expect(t.lastDeploy).toEqual({ label: 'acme/shop #209', sub: '18 min ago · health ok', ok: true });
  });

  it('falls back to a GitHub merge for the last deploy when no coordinator has one', () => {
    const s = load('no-coordinator');
    const t = deriveInbox(s, at(s)).tiles;
    expect(t.lastDeploy?.label).toBe('acme/docs #86');
    expect(t.lastDeploy?.sub).toBe('1 d ago · deploy pass');
  });
});

describe('resolved history', () => {
  const item = (id: string): InboxItem => ({
    id, kind: 'waiting', folder: 'needs', repo: 'acme/shop', title: id, why: '', next: '', cmd: '', since: null,
  });
  const T0 = Date.parse('2026-10-24T10:00:00Z');

  it('moves a vanished item to resolved and keeps the others open', () => {
    const h1 = reconcile(emptyHistory(), [item('a'), item('b')], T0);
    expect(h1.resolved).toEqual([]);
    const h2 = reconcile(h1, [item('b')], T0 + 1000);
    expect(h2.resolved.map((r) => r.item.id)).toEqual(['a']);
    expect(Object.keys(h2.open)).toEqual(['b']);
  });

  it('keeps an item for 24 h and then drops it', () => {
    let h = reconcile(emptyHistory(), [item('a')], T0);
    h = reconcile(h, [], T0 + 1000);
    expect(h.resolved).toHaveLength(1);
    h = reconcile(h, [], T0 + 1000 + RESOLVED_TTL_MS - 1);
    expect(h.resolved).toHaveLength(1);
    h = reconcile(h, [], T0 + 1000 + RESOLVED_TTL_MS);
    expect(h.resolved).toHaveLength(0);
  });

  it('an item that comes back is open again, not resolved', () => {
    let h = reconcile(emptyHistory(), [item('a')], T0);
    h = reconcile(h, [], T0 + 1000);
    h = reconcile(h, [item('a')], T0 + 2000);
    expect(h.resolved).toEqual([]);
    expect(Object.keys(h.open)).toEqual(['a']);
  });

  it('does not add the same item twice when it vanishes on repeated polls', () => {
    let h = reconcile(emptyHistory(), [item('a')], T0);
    h = reconcile(h, [], T0 + 1000);
    h = reconcile(h, [], T0 + 2000);
    expect(h.resolved).toHaveLength(1);
    expect(h.resolved[0]!.resolvedAt).toBe(T0 + 1000);
  });

  it('survives a bad stored value and a blocked store', () => {
    expect(sanitizeHistory({ open: { a: 5 }, resolved: [{ item: 1 }, 'x'] })).toEqual(emptyHistory());
    const mem = new Map<string, string>();
    const store = { getItem: (k: string) => mem.get(k) ?? null, setItem: (k: string, v: string) => void mem.set(k, v) };
    mem.set(HISTORY_KEY, '{not json');
    expect(loadHistory(store)).toEqual(emptyHistory());
    const h = reconcile(emptyHistory(), [item('a')], T0);
    saveHistory(h, store);
    expect(loadHistory(store).open.a?.id).toBe('a');
    const boom = {
      getItem: (): string | null => { throw new Error('blocked'); },
      setItem: (): void => { throw new Error('blocked'); },
    };
    expect(() => saveHistory(h, boom)).not.toThrow();
    expect(loadHistory(boom)).toEqual(emptyHistory());
    expect(() => saveIdSet('k', new Set(['a']), null)).not.toThrow();
    expect([...loadIdSet('k', null)]).toEqual([]);
  });
});

describe('a failing or stale source freezes its items', () => {
  const T0 = Date.parse('2026-10-24T10:00:00Z');
  const openOf = (s: HubState, now: number) => {
    const items = deriveInbox(s, now).items;
    return reconcile(emptyHistory(), items, now);
  };
  /** One poll: freeze first (as the hook does), then reconcile. */
  const poll = (prev: ReturnType<typeof emptyHistory>, s: HubState, now: number) => {
    const live = deriveInbox(s, now).items;
    const kept = withFrozen(prev.open, live, s);
    return { history: reconcile(prev, kept, now), shown: kept };
  };

  it('keeps waiting items, marked stale, when claude agents fails and the session list is empty', () => {
    const full = load('full');
    const h0 = openOf(full, T0);
    const waiting = Object.values(h0.open).filter((i) => i.kind === 'waiting');
    expect(waiting.length).toBeGreaterThan(0);

    const broken = clone(full);
    broken.sessions = [];
    broken.sources.agents = { ok: false, last_ok_at: full.generated_at, last_error: 'timed out', stale: false };
    const { history, shown } = poll(h0, broken, T0 + 10_000);
    expect(history.resolved.filter((r) => r.item.kind === 'waiting')).toEqual([]);
    const kept = shown.filter((i) => i.kind === 'waiting');
    expect(kept.map((i) => i.id).sort()).toEqual(waiting.map((i) => i.id).sort());
    expect(kept.every((i) => i.stale === true)).toBe(true);
    // Items of other sources are untouched.
    expect(shown.filter((i) => i.kind === 'owner-gate').every((i) => !i.stale)).toBe(true);
  });

  it('freezes on a stale source that is still ok', () => {
    const full = load('full');
    const h0 = openOf(full, T0);
    const s = clone(full);
    s.sessions = [];
    s.sources.agents.stale = true;
    expect(poll(h0, s, T0 + 1).history.resolved).toEqual([]);
  });

  it('resolves the item once the source is back and the item is really gone', () => {
    const full = load('full');
    const h0 = openOf(full, T0);
    const broken = clone(full);
    broken.sessions = [];
    broken.sources.agents.ok = false;
    const h1 = poll(h0, broken, T0 + 1).history;
    const back = clone(full);
    back.sessions = [];
    const { history, shown } = poll(h1, back, T0 + 2);
    expect(history.resolved.filter((r) => r.item.kind === 'waiting')).toHaveLength(2);
    expect(shown.filter((i) => i.kind === 'waiting')).toEqual([]);
  });

  it('a live item replaces its frozen copy and loses the stale mark', () => {
    const full = load('full');
    const h0 = openOf(full, T0);
    const broken = clone(full);
    broken.sessions = [];
    broken.sources.agents.ok = false;
    const h1 = poll(h0, broken, T0 + 1).history;
    const { shown } = poll(h1, full, T0 + 2);
    expect(shown.filter((i) => i.kind === 'waiting').every((i) => !i.stale)).toBe(true);
  });

  it('does not freeze a hub item (it has no source) and does not freeze with healthy sources', () => {
    const full = load('full');
    const h0 = openOf(full, T0);
    const s = clone(full);
    s.sessions = [];
    const { shown, history } = poll(h0, s, T0 + 1);
    expect(shown.some((i) => i.stale)).toBe(false);
    expect(history.resolved.length).toBeGreaterThan(0);
  });

  it('every derived item from a repo or session source names its source', () => {
    const full = load('full');
    for (const i of deriveInbox(full, T0).items) if (i.kind !== 'hub') expect(i.source).toBeDefined();
  });
});

describe('a per-repo read failure freezes that repo’s items (review I1)', () => {
  const T0 = Date.parse('2026-10-24T10:00:00Z');
  const poll = (prev: ReturnType<typeof emptyHistory>, s: HubState, now: number) => {
    const kept = withFrozen(prev.open, deriveInbox(s, now).items, s);
    return { history: reconcile(prev, kept, now), shown: kept };
  };
  const docs = '/srv/demo/docs';
  const shop = '/srv/demo/shop';

  it('keeps a blocked merge when gh loses access to its repo (source still ok)', () => {
    const full = load('full');
    const h0 = reconcile(emptyHistory(), deriveInbox(full, T0).items, T0);
    const id = `merge:${docs}:88`;
    expect(h0.open[id]?.repoPath).toBe(docs);

    // github.ts: no account can see the repo -> {path, repo, error}, no prs; sources.github stays ok.
    const s = clone(full);
    const repo = s.repos.find((r) => r.path === docs)!;
    repo.github = { path: docs, repo: repo.github!.repo, error: 'no gh account can see acme/docs' };
    expect(s.sources.github.ok).toBe(true);
    const { history, shown } = poll(h0, s, T0 + 10_000);
    expect(history.resolved.map((r) => r.item.id)).not.toContain(id);
    expect(shown.find((i) => i.id === id)?.stale).toBe(true);
    // Other repos' GitHub items are live, not frozen.
    expect(shown.filter((i) => i.source === 'github' && i.repoPath !== docs).every((i) => !i.stale)).toBe(true);
  });

  it('a repo that keeps its last good prs beside the error is not frozen (items stay live)', () => {
    const full = load('full');
    const h0 = reconcile(emptyHistory(), deriveInbox(full, T0).items, T0);
    const s = clone(full);
    const repo = s.repos.find((r) => r.path === docs)!;
    repo.github = { ...repo.github!, error: 'HTTP 502' };
    const { shown } = poll(h0, s, T0 + 1);
    expect(shown.find((i) => i.id === `merge:${docs}:88`)?.stale).toBeFalsy();
  });

  it('keeps collector items when the collector cannot read that repo', () => {
    const full = load('full');
    const h0 = reconcile(emptyHistory(), deriveInbox(full, T0).items, T0);
    const shopItems = Object.values(h0.open).filter((i) => i.source === 'collector' && i.repoPath === shop);
    expect(shopItems.length).toBeGreaterThan(0);

    const s = clone(full);
    const repo = s.repos.find((r) => r.path === shop)!;
    repo.error = 'permission denied';
    repo.relays = null;
    expect(s.sources.collector.ok).toBe(true);
    const { history, shown } = poll(h0, s, T0 + 1);
    expect(history.resolved.filter((r) => r.item.repoPath === shop && r.item.source === 'collector')).toEqual([]);
    for (const i of shopItems) expect(shown.find((x) => x.id === i.id)?.stale).toBe(true);
  });

  it('resolves the item once the repo reads again and the item is really gone', () => {
    const full = load('full');
    const h0 = reconcile(emptyHistory(), deriveInbox(full, T0).items, T0);
    const broken = clone(full);
    const repo = broken.repos.find((r) => r.path === docs)!;
    repo.github = { path: docs, error: 'no access' };
    const h1 = poll(h0, broken, T0 + 1).history;
    const back = clone(full);
    back.repos.find((r) => r.path === docs)!.github!.prs = [];
    const { history } = poll(h1, back, T0 + 2);
    expect(history.resolved.map((r) => r.item.id)).toContain(`merge:${docs}:88`);
  });
});

describe('roadmap owner gates in the Inbox (P24)', () => {
  const withDone = (): HubState => {
    const s = clone(load('full'));
    const rm = (s.repos.find((r) => r.name === 'shop')!.roadmaps as { roadmaps: { milestones: { status: string; blockers?: unknown[] }[] }[] }).roadmaps[0]!;
    rm.milestones[1]!.status = 'done'; // S3 now has every dependency done
    return s;
  };
  const gateItems = (s: HubState) => deriveInbox(s, at(s)).items.filter((i) => i.id.startsWith('rmgate:'));

  it('a gate behind an open dependency is not an item', () => {
    expect(gateItems(load('full'))).toEqual([]);
  });

  it('a gate whose dependencies are done is an Owner gate item with repo, roadmap, gate id and next step', () => {
    const [g] = gateItems(withDone());
    expect(g).toMatchObject({
      kind: 'owner-gate',
      folder: 'approvals',
      repo: 'acme/shop',
      title: 'Roadmap launch, gate S3: owner signs off the checkout copy',
    });
    expect(g!.next).toContain('/caddis:roadmap');
    expect(g!.id).toBe('rmgate:/srv/demo/shop:launch:S3:0');
  });

  it('the id is stable across polls and the item resolves when the roadmap no longer names the gate', () => {
    const s = withDone();
    expect(gateItems(s).map((i) => i.id)).toEqual(gateItems(clone(s)).map((i) => i.id));
    const prev = reconcile(emptyHistory(), deriveInbox(s, at(s)).items, at(s));
    const rm = (s.repos.find((r) => r.name === 'shop')!.roadmaps as { roadmaps: { milestones: { blockers: unknown[] }[] }[] }).roadmaps[0]!;
    rm.milestones[2]!.blockers = []; // the gate is recorded
    const next = reconcile(prev, deriveInbox(s, at(s)).items, at(s));
    expect(next.resolved.map((r) => r.item.id)).toContain('rmgate:/srv/demo/shop:launch:S3:0');
  });
});

describe('deriveInbox: a waiting agy session', () => {
  it('names the agent in the title', () => {
    const s = clone(load('full'));
    s.sessions.push({
      ...s.sessions[0]!,
      key: 'agy:conv-7',
      session_id: 'conv-7abcdef12',
      name: null,
      agent: 'agy',
      status: 'waiting',
      waiting_for: 'input needed',
      waiting_class: 'owner',
    });
    const item = deriveInbox(s, at(s)).items.find((i) => i.id === 'waiting:conv-7abcdef12')!;
    expect(item.title).toBe('conv-7ab (agy) waits on input needed');
    expect(item.cmd).toBe('conv-7ab');
  });
});
