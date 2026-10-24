import { readFileSync } from 'node:fs';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import Activity from '../../ui/src/activity/Activity';
import { deriveActivity, filterActivity, KINDS, noFilter, ownerText, type Kind } from '../../ui/src/activity/derive';
import { localTime } from '../../ui/src/shell/time';
import type { HubState } from '../../ui/src/types';

const load = (name: string): HubState =>
  JSON.parse(readFileSync(new URL(`../fixtures/hub-state/${name}.json`, import.meta.url), 'utf8')) as HubState;

describe('deriveActivity (R52)', () => {
  it('has all six kinds, newest first', () => {
    const ev = deriveActivity(load('full'));
    expect(new Set(ev.map((e) => e.kind))).toEqual(new Set(KINDS));
    for (let i = 1; i < ev.length; i++) expect(ev[i - 1]!.ms).toBeGreaterThanOrEqual(ev[i]!.ms);
  });
  it('ids are unique and stable between two runs', () => {
    const a = deriveActivity(load('full')).map((e) => e.id);
    expect(new Set(a).size).toBe(a.length);
    expect(deriveActivity(load('full')).map((e) => e.id)).toEqual(a);
  });
  it('a merge links to its PR', () => {
    const m = deriveActivity(load('full')).find((e) => e.kind === 'merge' && e.pr === 209)!;
    expect(m).toMatchObject({ text: 'Merged #209 checkout copy', prUrl: 'https://github.com/acme/shop/pull/209', repoLabel: 'acme/shop' });
  });
  it('a deploy check gives a deploy event with D1-D5 and a health event', () => {
    const s = load('full');
    (s.repos[0]!.coordinator!.deploy_checks[0] as Record<string, unknown>).checks = { D1: 'pass', D2: 'pass', D3: 'pass', D4: 'fail', D5: 'skip' };
    const ev = deriveActivity(s).filter((e) => e.pr === 209 && e.repo === 'acme__shop');
    const deploy = ev.find((e) => e.kind === 'deploy')!;
    expect(deploy.detail).toBe('D1 pass · D2 pass · D3 pass · D4 fail · D5 skip · run 1');
    expect(deploy.tone).toBe('bad');
    expect(ev.find((e) => e.kind === 'health')).toMatchObject({ text: 'Health check ok for #209', tone: 'good' });
    // The merge has a deploy check, so its raw runs are not shown twice.
    expect(ev.filter((e) => e.kind === 'deploy')).toHaveLength(1);
  });
  it('a merge with no deploy check shows its deploy runs', () => {
    const ev = deriveActivity(load('full')).filter((e) => e.kind === 'deploy' && e.repo === 'acme__billing');
    expect(ev).toHaveLength(1);
    expect(ev[0]).toMatchObject({ text: 'Deploy runs for #75', detail: 'deploy success', tone: 'good' });
  });
  it('owner actions come from the audit tail, refusals with their reason', () => {
    const own = deriveActivity(load('full')).filter((e) => e.kind === 'owner');
    expect(own.map((e) => e.text)).toEqual(['Refused: you marked as hotfix #212', 'You held #214', 'You approved: spend over 50 EUR']);
    expect(own[0]).toMatchObject({ tone: 'warn', detail: 'head_moved', prUrl: 'https://github.com/acme/shop/pull/212' });
  });
  it('ownerText covers a plain request', () => {
    expect(ownerText({ at: 'x', request_id: null, repo: null, pr: null, action: null, what: null, result: 'requested', reason: null })).toBe('You sent a request');
  });
  it('coordinator results show done and rejected with the reason', () => {
    const res = deriveActivity(load('full')).filter((e) => e.kind === 'coordinator');
    expect(res.map((e) => [e.text, e.detail, e.tone])).toEqual([
      ['Coordinator rejected: request req-b', 'head moved', 'bad'],
      ['Coordinator done: request req-a', null, 'good'],
    ]);
  });
  it('a result joins the request view for its action and PR', () => {
    const s = load('full');
    s.repos[0]!.coordinator!.requests = [
      { id: 'req-b', action: 'hotfix', pr: 212, head_sha: null, what: null, created_at: '2026-10-24T10:40:00Z', expires_at: null, status: 'rejected', reason: 'head moved', at: '2026-10-24T10:41:00Z' },
    ];
    const e = deriveActivity(s).find((x) => x.id === 'result:acme__shop:req-b')!;
    expect(e).toMatchObject({ text: 'Coordinator rejected: marked as hotfix #212', pr: 212 });
  });
  it('shows a coordinator approval with its reason and does not repeat an owner approval', () => {
    const ap = deriveActivity(load('full')).filter((e) => e.kind === 'approval');
    expect(ap).toHaveLength(1);
    expect(ap[0]).toMatchObject({ text: 'Coordinator approved: start phase 4', detail: 'phase 3 done, its exit gate passed' });
  });
  it('an empty state has no events', () => {
    expect(deriveActivity(load('empty'))).toEqual([]);
  });
  it('audit ids hold when the window moves and a line repeats', () => {
    const s = load('full');
    const line = s.audit[0]!;
    s.audit = [line, { ...line }, ...s.audit.slice(1)];
    const ids = deriveActivity(s).filter((e) => e.kind === 'owner').map((e) => e.id);
    expect(new Set(ids).size).toBe(ids.length);
    s.audit = s.audit.slice(1);
    const next = deriveActivity(s).filter((e) => e.kind === 'owner').map((e) => e.id);
    expect(next.every((id) => ids.includes(id))).toBe(true);
  });
});

describe('filterActivity (R53)', () => {
  const ev = deriveActivity(load('full'));
  it('no filter keeps all', () => {
    expect(filterActivity(ev, noFilter())).toHaveLength(ev.length);
  });
  it('by repo', () => {
    const only = filterActivity(ev, { repo: 'acme__billing', kinds: new Set() });
    expect(only.length).toBeGreaterThan(0);
    expect(only.every((e) => e.repo === 'acme__billing')).toBe(true);
  });
  it('by kind', () => {
    const kinds = new Set<Kind>(['merge', 'health']);
    const only = filterActivity(ev, { repo: null, kinds });
    expect(only.every((e) => kinds.has(e.kind))).toBe(true);
    expect(only.some((e) => e.kind === 'merge')).toBe(true);
  });
  it('by both', () => {
    const only = filterActivity(ev, { repo: 'acme__shop', kinds: new Set<Kind>(['owner']) });
    expect(only).toHaveLength(2);
  });
});

describe('localTime (R53, L22)', () => {
  it('shows the same instant in two zones with the zone name', () => {
    expect(localTime('2026-10-24T10:50:00Z', 'en-GB', 'UTC')).toBe('24 Oct 2026, 10:50 UTC');
    expect(localTime('2026-10-24T10:50:00Z', 'en-GB', 'Europe/Berlin')).toMatch(/^24 Oct 2026, 12:50 (CEST|GMT\+2)$/);
  });
  it('unknown for null and bad dates', () => {
    expect(localTime(null)).toBe('unknown');
    expect(localTime('nope')).toBe('unknown');
  });
});

describe('Activity page markup (R52, R53)', () => {
  const render = (s: HubState): string => renderToStaticMarkup(createElement(Activity, { state: s }));
  it('renders every kind, the filters and the repo list', () => {
    const out = render(load('full'));
    for (const k of KINDS) expect(out).toContain(`data-testid="kind-${k}"`);
    for (const k of KINDS) expect(out).toContain(`data-kind="${k}"`);
    expect(out).toContain('data-testid="activity-repo"');
    expect(out).toContain('<option value="acme__billing">acme/billing</option>');
    expect(out).toContain('href="https://github.com/acme/shop/pull/209"');
  });
  it('shows the empty state with no event', () => {
    expect(render(load('empty'))).toContain('data-testid="activity-empty"');
  });
  it('shows a note when GitHub data is old', () => {
    const s = load('full');
    s.sources.github = { ok: false, last_ok_at: null, last_error: 'x', stale: true };
    expect(render(s)).toContain('data-testid="activity-stale"');
  });
  it('shows the first 100 events and Show more for the rest', () => {
    const s = load('full');
    s.audit = Array.from({ length: 120 }, (_, i) => ({ at: new Date(Date.parse('2026-10-24T08:00:00Z') + i * 1000).toISOString(), request_id: `r${i}`, repo: 'acme__shop', pr: i, action: 'hold', what: null, result: 'requested', reason: null }));
    const out = render(s);
    expect(out.match(/data-testid="activity-item"/g)!.length).toBe(100);
    expect(out).toContain('data-testid="activity-more"');
  });
});
