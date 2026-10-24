import { readFileSync } from 'node:fs';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { Guide, MISSING_TEXT, UPDATE_HINT } from '../../ui/src/guide/Guide';

const fixture = JSON.parse(readFileSync(new URL('../fixtures/hub-state/guide.json', import.meta.url), 'utf8')).guide as Record<string, unknown>;
const versions = { hub: '0.0.1', pool: null, plugin: null };
const render = (guide: unknown): string => renderToStaticMarkup(createElement(Guide, { guide, versions }));
const count = (html: string, id: string): number => Number(new RegExp(`data-testid="guide-count-${id}">(\\d+)<`).exec(html)![1]);

describe('guide page (static render)', () => {
  it('shows each section count and one entry per item', () => {
    const html = render(fixture);
    expect(count(html, 'commands')).toBe(9);
    expect(count(html, 'agents')).toBe(3);
    expect(count(html, 'skills')).toBe(5);
    expect(count(html, 'hooks')).toBe(3);
    expect(count(html, 'runtimes')).toBe(3);
    expect(html.match(/data-testid="guide-entry"/g)).toHaveLength(9 + 3 + 5 + 3 + 3);
    expect(html).toContain('/caddis:feature-plan &lt;feature&gt;');
    expect(html).toContain('caddis 9.9.9 (installed pool)');
  });
  it('shows the missing state', () => {
    const html = render(null);
    expect(html).toContain(MISSING_TEXT);
    expect(html).not.toContain('guide-filter');
  });
  it('shows the error state with the message', () => {
    const html = render({ error: 'relay read failed' });
    expect(html).toContain('relay read failed');
    expect(html).toContain('caddis doctor');
  });
  it('shows the newer-schema state and no entries', () => {
    const html = render({ ...fixture, schema: 2 });
    expect(html).toContain(UPDATE_HINT);
    expect(html).not.toContain('guide-entry');
  });
});
