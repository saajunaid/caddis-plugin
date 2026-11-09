import { readFileSync } from 'node:fs';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import Activity from '../../ui/src/activity/Activity';
import { deriveInbox } from '../../ui/src/inbox/derive';
import type { InboxApi } from '../../ui/src/inbox/useInbox';
import { Overview } from '../../ui/src/overview/Overview';
import { gateCountText, milestoneMeta } from '../../ui/src/repo/RoadmapTimeline';
import { Footer } from '../../ui/src/shell/Footer';
import { LoadError, LoadingSkeleton } from '../../ui/src/shell/Loading';
import type { HubState } from '../../ui/src/types';

const load = (name: string): HubState =>
  JSON.parse(readFileSync(new URL(`../fixtures/hub-state/${name}.json`, import.meta.url), 'utf8')) as HubState;

describe('UX audit fixes (hub-ux-audit rows 3, 4, 5, 6, 10)', () => {
  it('row 5: milestone and gate wording reads as plain text', () => {
    expect(gateCountText(1)).toBe('1 gate');
    expect(gateCountText(2)).toBe('2 gates');
    expect(milestoneMeta({ owner: 'owner', target: null, depends: [] })).toBe('run by owner');
    expect(milestoneMeta({ owner: 'runner', target: '2026-11-30', depends: ['S1', 'S2'] })).toBe(
      'run by runner · target 2026-11-30 · after S1, S2',
    );
  });

  it('row 10: Activity has an All chip, pressed while no kind is chosen', () => {
    const out = renderToStaticMarkup(createElement(Activity, { state: load('full') }));
    expect(out).toMatch(/aria-pressed="true"[^>]*data-testid="kind-all"/);
  });

  describe('Overview cards (B)', () => {
    const s = load('full');
    const now = Date.parse(s.generated_at);
    const api: InboxApi = {
      model: deriveInbox(s, now),
      resolved: [],
      read: new Set(),
      markRead: () => undefined,
      notify: { supported: false, enabled: false, enable: () => undefined },
    };
    const out = renderToStaticMarkup(createElement(Overview, { state: s, nowMs: now, api }));

    it('one card per repo, each a link to its Flow tab, with the PR ring', () => {
      expect((out.match(/data-testid="repo-card"/g) ?? []).length).toBe(3);
      expect(out).toContain('href="#/repo/acme__shop"');
      expect(out).toContain('>3/5<');
    });

    it('the Needs you and Live now panels, no lanes', () => {
      expect(out).toContain('data-testid="ov-needs"');
      expect(out).toContain('data-testid="ov-live"');
      expect(out).not.toContain('lane-col');
    });

    it('no queue buttons on the Overview (D4)', () => {
      expect(out).not.toContain('data-testid="act-');
    });
  });

  it('row 6: the footer labels do not break inside an item', () => {
    const s = load('full');
    const out = renderToStaticMarkup(
      createElement(Footer, { state: s, nowMs: Date.parse(s.generated_at), theme: 'dark', onTheme: () => undefined, motion: 'on', onMotion: () => undefined }),
    );
    expect(out).toContain('agy, 24 h');
    expect(out).toContain('Note at €300');
    expect(out).not.toContain('/ 200 EUR');
    expect(out).not.toContain('(24 h)');
    expect(out).toMatch(/class="versions-item">hub /);
  });

  it('first load: a skeleton while loading, then a Retry button', () => {
    expect(renderToStaticMarkup(createElement(LoadError, { onRetry: () => undefined }))).toContain('Retry now');
    expect(renderToStaticMarkup(createElement(LoadingSkeleton))).toContain('aria-busy="true"');
  });
});
