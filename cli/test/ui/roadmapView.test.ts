import { readFileSync } from 'node:fs';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import RoadmapTab from '../../ui/src/repo/RoadmapTab';
import { readView, VIEW_KEY, writeView } from '../../ui/src/repo/roadmap';
import type { HubState } from '../../ui/src/types';

describe('roadmapView storage helpers', () => {
  it("readView(null) === 'timeline'", () => {
    expect(readView(null)).toBe('timeline');
  });

  it("stored 'board' -> 'board'", () => {
    expect(readView({ getItem: (k) => (k === VIEW_KEY ? 'board' : null) })).toBe('board');
  });

  it("stored 'x' -> 'timeline'", () => {
    expect(readView({ getItem: () => 'x' })).toBe('timeline');
  });

  it("a getItem that throws -> 'timeline'", () => {
    expect(
      readView({
        getItem: () => {
          throw new Error('storage disabled');
        },
      }),
    ).toBe('timeline');
  });

  it('writeView with a throwing setItem does not throw', () => {
    expect(() =>
      writeView(
        {
          setItem: () => {
            throw new Error('quota exceeded');
          },
        },
        'board',
      ),
    ).not.toThrow();
    expect(() => writeView(null, 'timeline')).not.toThrow();
  });

  it("writeView(s, 'board') calls setItem('caddis.hub.roadmapView', 'board')", () => {
    const setItem = vi.fn();
    writeView({ setItem }, 'board');
    expect(setItem).toHaveBeenCalledWith('caddis.hub.roadmapView', 'board');
  });

  it('a plan-only repo renders rm-timeline by default, and the Board view shows rm-plan-board', () => {
    const s = JSON.parse(readFileSync(new URL('../fixtures/hub-state/full.json', import.meta.url), 'utf8')) as HubState;
    const docs = s.repos.find((r) => r.name === 'docs')!;
    const timelineHtml = renderToStaticMarkup(createElement(RoadmapTab, { repo: docs, slug: null }));
    expect(timelineHtml).toContain('data-testid="rm-timeline"');
    expect(timelineHtml).toContain('plan only, no runner');
    expect(timelineHtml).not.toContain('data-testid="rm-plan-board"');

    const boardHtml = renderToStaticMarkup(createElement(RoadmapTab, { repo: docs, slug: null, initialView: 'board' }));
    expect(boardHtml).toContain('data-testid="rm-plan-board"');
    expect(boardHtml).not.toContain('data-testid="rm-timeline"');
  });
});
