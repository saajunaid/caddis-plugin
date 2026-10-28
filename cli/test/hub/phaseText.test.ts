import { describe, expect, it } from 'vitest';
import { findPhaseSection, stripPhaseText } from '../../src/hub/phaseText.js';

function makeState() {
  return {
    schema: 1,
    repos: [
      {
        path: 'E:/r/docs',
        name: 'docs',
        plans: {
          schema: 1,
          plans: [
            {
              path: '.caddis/plans/p-docs.md',
              title: 'p-docs',
              phases: {
                c0: { title: 'Design', text: 'Body zero' },
                '2': { title: 'Fonts', text: 'Body two' },
              },
            },
            { path: '.caddis/plans/p-none.md', title: 'p-none' },
          ],
        },
      },
      { path: 'E:/r/shop', name: 'shop', plans: null },
    ],
  };
}

describe('stripPhaseText', () => {
  it('removes phase text, keeps titles, does not mutate input, and reuses unchanged objects', () => {
    const state = makeState();
    const out = stripPhaseText(state) as typeof state;

    const json = JSON.stringify(out);
    expect(json).not.toContain('Body zero');
    expect(json).not.toContain('Body two');
    expect(out.repos[0]!.plans!.plans[0]!.phases).toEqual({
      c0: { title: 'Design' },
      '2': { title: 'Fonts' },
    });
    expect(state.repos[0]!.plans!.plans[0]!.phases!.c0.text).toBe('Body zero');
    expect(out.repos[0]!.plans!.plans[1]).toBe(state.repos[0]!.plans!.plans[1]);
    expect(out.repos[1]).toBe(state.repos[1]);
  });

  it('returns non-state inputs as is', () => {
    expect(stripPhaseText(null)).toBeNull();
    expect(stripPhaseText('x')).toBe('x');
  });
});

describe('findPhaseSection', () => {
  it('finds a phase section by repo, plan, and key', () => {
    const state = makeState();
    expect(findPhaseSection(state, 'E:/r/docs', '.caddis/plans/p-docs.md', '2')).toEqual({
      title: 'Fonts',
      text: 'Body two',
    });
  });

  it('returns null for unknown repo, plan, key, constructor, and __proto__', () => {
    const state = makeState();
    expect(findPhaseSection(state, 'E:/r/unknown', '.caddis/plans/p-docs.md', '2')).toBeNull();
    expect(findPhaseSection(state, 'E:/r/docs', '.caddis/plans/unknown.md', '2')).toBeNull();
    expect(findPhaseSection(state, 'E:/r/docs', '.caddis/plans/p-docs.md', '99')).toBeNull();
    expect(findPhaseSection(state, 'E:/r/docs', '.caddis/plans/p-docs.md', 'constructor')).toBeNull();
    expect(findPhaseSection(state, 'E:/r/docs', '.caddis/plans/p-docs.md', '__proto__')).toBeNull();
  });
});
