import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { PhasePanel } from '../../ui/src/repo/PhasePanel';
import type { PhaseView } from '../../ui/src/repo/roadmap';

const basePhase: PhaseView = {
  ref: 'p-docs#2',
  plan: 'p-docs',
  num: 2,
  name: 'Fonts',
  model: '',
  lane: '',
  risk: '',
  highRisk: false,
  tracker: 'not started',
  tile: 'todo',
  prs: [],
  stage: 'to do',
};

describe('PhasePanel', () => {
  it('renders nothing when detail is null', () => {
    const html = renderToStaticMarkup(createElement(PhasePanel, { detail: null, variant: 'hub', onClose: () => {} }));
    expect(html).toBe('');
  });

  it('renders panel with section text in hub variant and omits empty meta', () => {
    const html = renderToStaticMarkup(
      createElement(PhasePanel, {
        detail: { title: 'Fonts', text: 'Step one\nStep two', phase: basePhase },
        variant: 'hub',
        onClose: () => {},
      }),
    );
    expect(html).toContain('data-testid="rm-panel"');
    expect(html).toContain('p-docs#2 Fonts');
    expect(html).toContain('Step one');
    expect(html).toContain('data-testid="rm-panel-text"');
    expect(html).toContain('not started');
    expect(html).not.toContain('rm-panel-meta');
  });

  it('renders fallback text when text is null in hub variant', () => {
    const html = renderToStaticMarkup(
      createElement(PhasePanel, {
        detail: { title: 'Fonts', text: null, phase: basePhase },
        variant: 'hub',
        onClose: () => {},
      }),
    );
    expect(html).toContain('The plan has no section for this phase.');
  });

  it('hides section text and fallback in site variant', () => {
    const html = renderToStaticMarkup(
      createElement(PhasePanel, {
        detail: { title: 'Fonts', text: 'Secret', phase: basePhase },
        variant: 'site',
        onClose: () => {},
      }),
    );
    expect(html).not.toContain('rm-panel-text');
    expect(html).not.toContain('Secret');
    expect(html).not.toContain('The plan has no section');
  });

  it('escapes HTML in section text', () => {
    const html = renderToStaticMarkup(
      createElement(PhasePanel, {
        detail: { title: 'Fonts', text: '<b>x</b>', phase: basePhase },
        variant: 'hub',
        onClose: () => {},
      }),
    );
    expect(html).toContain('&lt;b&gt;x&lt;/b&gt;');
    expect(html).not.toContain('<b>x</b>');
  });

  it('renders model, lane and risk when present', () => {
    const phase: PhaseView = { ...basePhase, model: 'sonnet', lane: 'agy foo', risk: 'high' };
    const html = renderToStaticMarkup(
      createElement(PhasePanel, {
        detail: { title: 'Fonts', text: null, phase },
        variant: 'hub',
        onClose: () => {},
      }),
    );
    expect(html).toContain('model sonnet · lane agy · risk high');
  });

  it('renders PR links', () => {
    const phase: PhaseView = {
      ...basePhase,
      prs: [{ number: 171, url: 'https://example.com/pull/171', stage: 'merged', detail: null }],
    };
    const html = renderToStaticMarkup(
      createElement(PhasePanel, {
        detail: { title: 'Fonts', text: null, phase },
        variant: 'hub',
        onClose: () => {},
      }),
    );
    expect(html).toContain('href="https://example.com/pull/171"');
  });

  it('renders loading note when text is null and note is loading', () => {
    const html = renderToStaticMarkup(
      createElement(PhasePanel, {
        detail: { title: 'Fonts', text: null, phase: basePhase },
        note: 'loading',
        variant: 'hub',
        onClose: () => {},
      }),
    );
    expect(html).toContain('data-testid="rm-panel-note"');
    expect(html).toContain('Loading the plan section…');
    expect(html).not.toContain('The plan has no section');
  });

  it('renders error note when text is null and note is error', () => {
    const html = renderToStaticMarkup(
      createElement(PhasePanel, {
        detail: { title: 'Fonts', text: null, phase: basePhase },
        note: 'error',
        variant: 'hub',
        onClose: () => {},
      }),
    );
    expect(html).toContain('data-testid="rm-panel-note"');
    expect(html).toContain('Could not load the plan section.');
    expect(html).not.toContain('The plan has no section');
  });

  it('prefers text over loading note when text is present', () => {
    const html = renderToStaticMarkup(
      createElement(PhasePanel, {
        detail: { title: 'Fonts', text: 'Body', phase: basePhase },
        note: 'loading',
        variant: 'hub',
        onClose: () => {},
      }),
    );
    expect(html).toContain('Body');
    expect(html).not.toContain('rm-panel-note');
  });

  it('hides note in site variant', () => {
    const html = renderToStaticMarkup(
      createElement(PhasePanel, {
        detail: { title: 'Fonts', text: null, phase: basePhase },
        note: 'loading',
        variant: 'site',
        onClose: () => {},
      }),
    );
    expect(html).not.toContain('rm-panel-note');
  });
});
