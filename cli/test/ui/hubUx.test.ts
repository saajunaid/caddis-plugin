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

  describe('Overview (rows 3 and 4)', () => {
    const s = load('full');
    const now = Date.parse(s.generated_at);
    const api: InboxApi = {
      model: deriveInbox(s, now),
      resolved: [],
      read: new Set(),
      markRead: () => undefined,
      notify: { supported: false, enabled: false, enable: () => undefined },
    };
    const out = renderToStaticMarkup(createElement(Overview, { state: s, nowMs: now, api, act: { local: {}, run: () => undefined } }));

    it('row 3: an empty column keeps its heading but not the word None; the lane names the empty columns', () => {
      expect(out).toContain('lane-col empty');
      expect(out).not.toMatch(/class="col-empty">None</);
      expect(out).toMatch(/data-testid="lane-empty-line"[^>]*>Empty: [A-Z]/);
    });

    it('row 3: a column with its own empty text keeps it', () => {
      expect(out).toContain('<span class="col-empty">No coordinator: each session merges its own PRs.</span>');
    });

    it('row 4: each lane head links to the repo page', () => {
      expect(out).toContain('href="#/repo/acme__shop"');
      expect(out).toContain('Open repo');
    });
  });

  it('row 6: the footer labels do not break inside an item', () => {
    const s = load('full');
    const out = renderToStaticMarkup(
      createElement(Footer, { state: s, nowMs: Date.parse(s.generated_at), theme: 'dark', onTheme: () => undefined, motion: 'on', onMotion: () => undefined }),
    );
    expect(out).toContain('agy spend · 24 h');
    expect(out).not.toContain('(24 h)');
    expect(out).toMatch(/class="versions-item">hub /);
  });
});
