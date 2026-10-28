import { readFileSync } from 'node:fs';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it } from 'vitest';
import { Details } from '../../ui/src/guide/Details';
import { Guide, MISSING_TEXT, UPDATE_HINT } from '../../ui/src/guide/Guide';
import { Poster } from '../../ui/src/guide/Poster.jsx';
import { anchorId, type Guide as GuideData } from '../../ui/src/guide/model';
import { mindMap, posterModel } from '../../ui/src/guide/poster';

const fixture = JSON.parse(
  readFileSync(new URL('../fixtures/hub-state/guide.json', import.meta.url), 'utf8')
).guide as GuideData;
const versions = { hub: '0.0.1', pool: null, plugin: null };

describe('guide page and Details tab', () => {
  it('tab bar has 2 tabs and the active one has aria-selected="true"', () => {
    const posterHtml = renderToStaticMarkup(
      createElement(Guide, { guide: fixture, versions, tab: 'poster', item: null })
    );
    const tabs = posterHtml.match(/role="tab"/g) ?? [];
    expect(tabs).toHaveLength(2);
    expect(posterHtml).toMatch(/href="#\/guide"[^>]*aria-selected="true"/);
    expect(posterHtml).toMatch(/href="#\/guide\/details"[^>]*aria-selected="false"/);

    const detailsHtml = renderToStaticMarkup(
      createElement(Guide, { guide: fixture, versions, tab: 'details', item: null })
    );
    expect(detailsHtml).toMatch(/href="#\/guide"[^>]*aria-selected="false"/);
    expect(detailsHtml).toMatch(/href="#\/guide\/details"[^>]*aria-selected="true"/);
  });

  it('tab "poster" renders data-testid="guide-poster"', () => {
    const html = renderToStaticMarkup(
      createElement(Guide, { guide: fixture, versions, tab: 'poster', item: null })
    );
    expect(html).toContain('data-testid="guide-poster"');
    expect(html).not.toContain('data-testid="guide-poster-slot"');
    expect(html).not.toContain('id="guide-commands"');
  });

  it('poster renders command, agent, skill category links and counts line', () => {
    const html = renderToStaticMarkup(
      createElement(Guide, { guide: fixture, versions, tab: 'poster', item: null })
    );
    const workflowHtml = html.split('<div class="gp-map-wrap')[0] ?? '';

    const cmdLinks = workflowHtml.match(/<a\b[^>]*href="#\/guide\/details\/g-command-[^"]*"/g) ?? [];
    expect(cmdLinks).toHaveLength(fixture.commands.length);
    for (const cmd of fixture.commands) {
      expect(workflowHtml).toContain(`href="#/guide/details/${anchorId('command', cmd.name)}"`);
    }

    const agentLinks = workflowHtml.match(/<a\b[^>]*href="#\/guide\/details\/g-agent-[^"]*"/g) ?? [];
    expect(agentLinks).toHaveLength(fixture.agents.length);
    for (const agent of fixture.agents) {
      expect(workflowHtml).toContain(`href="#/guide/details/${anchorId('agent', agent.name)}"`);
    }

    const categories = Array.from(new Set(fixture.skills.map((s) => s.category)));
    const catLinks = workflowHtml.match(/<a\b[^>]*href="#\/guide\/details\/g-skillCategory-[^"]*"/g) ?? [];
    expect(catLinks).toHaveLength(categories.length);
    for (const cat of categories) {
      expect(workflowHtml).toContain(`href="#/guide/details/${anchorId('skillCategory', cat)}"`);
    }

    expect(html).toContain(
      `${fixture.version} · ${fixture.commands.length} commands · ${fixture.agents.length} agents · ${fixture.skills.length} skills · ${fixture.hooks.length} hooks`
    );
  });

  const origWindow = globalThis.window;
  const origDocument = globalThis.document;
  afterEach(() => {
    globalThis.window = origWindow;
    globalThis.document = origDocument;
  });

  function findButton(
    node: unknown,
    label: string
  ): { props: { onClick?: () => void } } | null {
    if (!node || typeof node !== 'object') return null;
    if (Array.isArray(node)) {
      for (const child of node) {
        const found = findButton(child, label);
        if (found) return found;
      }
      return null;
    }
    const el = node as {
      type?: unknown;
      props?: { children?: unknown; onClick?: () => void };
    };
    if (el.type === 'button' && el.props?.children === label) {
      return el as { props: { onClick?: () => void } };
    }
    if (el.props?.children) {
      return findButton(el.props.children, label);
    }
    return null;
  }

  it('switching to Mind map renders an <svg> whose <a> count equals the number of mindMap nodes with a non-null anchor', () => {
    const store = new Map<string, string>();
    globalThis.window = {
      localStorage: {
        getItem: (k: string) => store.get(k) ?? null,
        setItem: (k: string, v: string) => void store.set(k, v),
      },
    } as unknown as Window & typeof globalThis;

    const initialHtml = renderToStaticMarkup(createElement(Poster, { guide: fixture }));
    expect(initialHtml).toContain('class="gp-workflow"');
    expect(initialHtml).toContain('class="gp-map-wrap gp-hidden"');

    let clicked = false;
    function ClickMindMap(): JSX.Element {
      const tree = Poster({ guide: fixture });
      if (!clicked) {
        clicked = true;
        const btn = findButton(tree, 'Mind map');
        expect(btn).not.toBeNull();
        btn?.props.onClick?.();
      }
      return tree;
    }

    const clickedHtml = renderToStaticMarkup(createElement(ClickMindMap));
    expect(store.get('caddis.hub.posterMode')).toBe('mind');
    expect(clickedHtml).toContain('class="gp-map-wrap"');
    expect(clickedHtml).toContain('class="gp-workflow gp-hidden"');
    const svgMatch = clickedHtml.match(/<svg class="gp-map"[\s\S]*?<\/svg>/);
    expect(svgMatch).not.toBeNull();
    const svgLinks = svgMatch![0].match(/<a\b/g) ?? [];
    const expectedLinks = mindMap(posterModel(fixture), 1000).filter(
      (n) => n.anchor !== null
    ).length;
    expect(svgLinks).toHaveLength(expectedLinks);
    expect(svgMatch![0]).toContain('class="gp-pulse"');

    globalThis.document = {
      documentElement: { dataset: { motion: 'off' } },
    } as unknown as Document;
    const motionOffHtml = renderToStaticMarkup(createElement(Poster, { guide: fixture }));
    expect(motionOffHtml).toContain('<svg class="gp-map"');
    expect(motionOffHtml).not.toContain('gp-pulse');
  });

  it('a stored mind value starts on Mind map', () => {
    globalThis.window = {
      localStorage: {
        getItem: (k: string) => (k === 'caddis.hub.posterMode' ? 'mind' : null),
        setItem: () => undefined,
      },
    } as unknown as Window & typeof globalThis;

    const html = renderToStaticMarkup(createElement(Poster, { guide: fixture }));
    expect(html).toContain('class="gp-map-wrap"');
    expect(html).toContain('class="gp-workflow gp-hidden"');
  });

  it('branch labels use text-anchor end on the left, start on the right, and middle near the vertical axis', () => {
    globalThis.window = {
      localStorage: {
        getItem: (k: string) => (k === 'caddis.hub.posterMode' ? 'mind' : null),
        setItem: () => undefined,
      },
    } as unknown as Window & typeof globalThis;

    const html = renderToStaticMarkup(createElement(Poster, { guide: fixture }));
    expect(html).toMatch(/<text[^>]*text-anchor="middle"[^>]*>Setup<\/text>/);
    expect(html).toMatch(/<text[^>]*text-anchor="start"[^>]*>Build<\/text>/);
    expect(html).toMatch(/<text[^>]*text-anchor="start"[^>]*>Review<\/text>/);
    expect(html).toMatch(/<text[^>]*text-anchor="end"[^>]*>Agents<\/text>/);
    expect(html).toMatch(/<text[^>]*text-anchor="end"[^>]*>Skills<\/text>/);
  });

  it('a storage whose getItem throws starts on Workflow', () => {
    let called = false;
    globalThis.window = {
      localStorage: {
        getItem: (): string | null => {
          called = true;
          throw new Error('blocked');
        },
        setItem: () => undefined,
      },
    } as unknown as Window & typeof globalThis;

    const html = renderToStaticMarkup(createElement(Poster, { guide: fixture }));
    expect(called).toBe(true);
    expect(html).toContain('class="gp-workflow"');
    expect(html).toContain('class="gp-map-wrap gp-hidden"');
  });

  it('a setItem that throws does not break the click', () => {
    globalThis.window = {
      localStorage: {
        getItem: () => null,
        setItem: (): void => {
          throw new Error('blocked');
        },
      },
    } as unknown as Window & typeof globalThis;

    let clicked = false;
    function ClickMindMap(): JSX.Element {
      const tree = Poster({ guide: fixture });
      if (!clicked) {
        clicked = true;
        const btn = findButton(tree, 'Mind map');
        expect(btn).not.toBeNull();
        btn?.props.onClick?.();
      }
      return tree;
    }

    const clickedHtml = renderToStaticMarkup(createElement(ClickMindMap));
    expect(clickedHtml).toContain('class="gp-map-wrap"');
    expect(clickedHtml).toContain('class="gp-workflow gp-hidden"');
  });

  it('clicking Print calls window.print()', () => {
    let printed = false;
    globalThis.window = {
      localStorage: {
        getItem: () => null,
        setItem: () => undefined,
      },
      print: () => {
        printed = true;
      },
    } as unknown as Window & typeof globalThis;

    function ClickPrint(): JSX.Element {
      const tree = Poster({ guide: fixture });
      const btn = findButton(tree, 'Print');
      expect(btn).not.toBeNull();
      btn?.props.onClick?.();
      return tree;
    }

    const html = renderToStaticMarkup(createElement(ClickPrint));
    expect(html).toContain('class="gp-print"');
    expect(printed).toBe(true);
  });

  it('tab "details" + item "g-command-handoff" renders an open <details> with that id', () => {
    const html = renderToStaticMarkup(
      createElement(Guide, {
        guide: fixture,
        versions,
        tab: 'details',
        item: 'g-command-handoff',
      })
    );
    expect(html).toMatch(/<details[^>]*id="g-command-handoff"[^>]*open/);
    const closedMatch = html.match(/<details[^>]*id="g-command-feature-plan"[^>]*>/);
    expect(closedMatch).not.toBeNull();
    expect(closedMatch?.[0]).not.toContain('open');
  });

  it('filter "fleet" shows "fleet-open" and "fleet-close" items and hides "tdd"', () => {
    const guideWithFleet: GuideData = {
      ...fixture,
      commands: [
        ...fixture.commands,
        {
          name: 'fleet-open',
          description: 'Restore one role from the fleet restart sheet.',
          hint: '',
          steps: [],
          scripts: [],
          noArgs: false,
          stage: 'continuity',
          daily: false,
        },
        {
          name: 'fleet-close',
          description: 'Close a fleet of sessions and print restart sheet.',
          hint: '',
          steps: [],
          scripts: [],
          noArgs: true,
          stage: 'continuity',
          daily: false,
        },
      ],
    };
    const html = renderToStaticMarkup(
      createElement(Details, {
        guide: guideWithFleet,
        item: null,
        initialFilter: 'fleet',
      })
    );
    expect(html).toContain('fleet-open');
    expect(html).toContain('fleet-close');
    expect(html).not.toContain('g-skill-tdd');
  });

  it('renders guide-count, guide-shown, guide-entry and guide-nomatch markers on Details', () => {
    const filteredHtml = renderToStaticMarkup(
      createElement(Details, {
        guide: fixture,
        item: null,
        initialFilter: 'handoff',
      })
    );
    expect(filteredHtml).toContain('data-testid="guide-count-commands">9<');
    expect(filteredHtml).toContain('data-testid="guide-shown-commands">1 of 9<');
    expect(filteredHtml.match(/data-testid="guide-entry"/g)).toHaveLength(1);

    const nomatchHtml = renderToStaticMarkup(
      createElement(Details, {
        guide: fixture,
        item: null,
        initialFilter: 'zzz-no-such-entry',
      })
    );
    expect(nomatchHtml).toContain('data-testid="guide-nomatch"');
    expect(nomatchHtml).toContain('Nothing matches <code class="cmd">zzz-no-such-entry</code>.');
  });

  it('a <details> with id g-skillCategory-<category> exists for every category in the fixture', () => {
    const html = renderToStaticMarkup(
      createElement(Guide, { guide: fixture, versions, tab: 'details', item: null })
    );
    const categories = Array.from(new Set(fixture.skills.map((s) => s.category)));
    expect(categories.length).toBeGreaterThan(0);
    for (const cat of categories) {
      expect(html).toMatch(new RegExp(`<details[^>]*id="g-skillCategory-${cat}"`));
    }
  });

  it('shows the missing state', () => {
    const html = renderToStaticMarkup(
      createElement(Guide, { guide: null, versions, tab: 'details', item: null })
    );
    expect(html).toContain(MISSING_TEXT);
    expect(html).not.toContain('guide-filter');
  });

  it('shows the error state with the message', () => {
    const html = renderToStaticMarkup(
      createElement(Guide, {
        guide: { error: 'relay read failed' },
        versions,
        tab: 'details',
        item: null,
      })
    );
    expect(html).toContain('relay read failed');
    expect(html).toContain('caddis doctor');
  });

  it('shows the newer-schema state and no entries', () => {
    const html = renderToStaticMarkup(
      createElement(Guide, {
        guide: { ...fixture, schema: 2 },
        versions,
        tab: 'details',
        item: null,
      })
    );
    expect(html).toContain(UPDATE_HINT);
    expect(html).not.toContain('guide-entry');
  });
});
