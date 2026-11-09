import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { headline } from '../../ui/src/inbox/headline';
import { roadmapStrip, shippedList } from '../../ui/src/inbox/strip';
import { inboxKey, moveIndex } from '../../ui/src/shell/keys';
import type { HubState } from '../../ui/src/types';

const load = (name: string): HubState =>
  JSON.parse(readFileSync(new URL(`../fixtures/hub-state/${name}.json`, import.meta.url), 'utf8')) as HubState;
const full = load('full');
const empty = load('empty');
const now = Date.parse(full.generated_at);
const NOMOD = { ctrl: false, meta: false, alt: false };

describe('headline', () => {
  it('says nothing needs you on an empty state', () => {
    expect(headline(empty, 0, Date.parse(empty.generated_at))).toEqual({
      title: 'Nothing needs you.',
      sub: '0 agents working · 0 repos watched',
    });
  });

  it('counts the open items, the busy agents, the last ship and the repos', () => {
    expect(headline(full, 1, now).title).toBe('1 thing needs you.');
    expect(headline(full, 3, now)).toEqual({
      title: '3 things need you.',
      sub: '1 agent working · last ship 18 min ago (acme/shop #209) · 3 repos watched',
    });
  });
});

describe('strips', () => {
  it('lists the merges, newest first', () => {
    const rows = shippedList(full, now);
    expect(rows.map((r) => r.pr)).toEqual([209, 75, 86]);
    expect(rows[0]!.age).toBe('18 min ago');
    expect(rows[0]!.url).toBe('https://github.com/acme/shop/pull/209');
  });

  it('lists the roadmaps with a link and one segment per milestone', () => {
    const strip = roadmapStrip(full);
    expect(strip.length).toBeGreaterThan(0);
    for (const r of strip) {
      expect(r.href.startsWith('#/repo/')).toBe(true);
      expect(r.href).toContain('/roadmap/');
      for (const s of r.segs) expect(['done', 'wait', 'block', 'prog', 'todo']).toContain(s.tone);
    }
  });
});

describe('Inbox keys', () => {
  it('maps J, K, the arrows, Enter and C', () => {
    for (const k of ['j', 'J', 'ArrowDown']) expect(inboxKey(k, NOMOD, false, false)).toBe('next');
    for (const k of ['k', 'K', 'ArrowUp']) expect(inboxKey(k, NOMOD, false, false)).toBe('prev');
    expect(inboxKey('Enter', NOMOD, false, false)).toBe('open');
    for (const k of ['c', 'C']) expect(inboxKey(k, NOMOD, false, false)).toBe('copy');
    expect(inboxKey('x', NOMOD, false, false)).toBeNull();
  });

  it('modifiers disable every key', () => {
    expect(inboxKey('c', { ...NOMOD, ctrl: true }, false, false)).toBeNull();
    expect(inboxKey('j', { ...NOMOD, meta: true }, false, false)).toBeNull();
    expect(inboxKey('k', { ...NOMOD, alt: true }, false, false)).toBeNull();
  });

  it('does nothing while typing', () => {
    expect(inboxKey('j', NOMOD, true, false)).toBeNull();
    expect(inboxKey('c', NOMOD, true, false)).toBeNull();
  });

  it('Enter on a control is left to the browser', () => {
    expect(inboxKey('Enter', NOMOD, false, true)).toBeNull();
    expect(inboxKey('j', NOMOD, false, true)).toBe('next');
  });

  it('moves the index without a wrap', () => {
    expect(moveIndex('next', 0, 3)).toBe(1);
    expect(moveIndex('next', 2, 3)).toBe(2);
    expect(moveIndex('prev', 0, 3)).toBe(0);
    expect(moveIndex('prev', 2, 3)).toBe(1);
    expect(moveIndex('next', 0, 0)).toBe(-1);
  });
});
