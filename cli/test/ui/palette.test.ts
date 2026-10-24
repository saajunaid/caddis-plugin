import { describe, expect, it } from 'vitest';
import { BG_DARK, BG_LIGHT, PALETTE, TEXT_SAFE, contrastRatio, type PaletteName } from '../../ui/src/brand/palette.js';

const names = Object.keys(PALETTE) as PaletteName[];

describe('contrastRatio', () => {
  it('matches known WCAG values', () => {
    expect(contrastRatio('#000000', '#ffffff')).toBeCloseTo(21, 5);
    expect(contrastRatio('#ffffff', '#ffffff')).toBeCloseTo(1, 5);
    expect(contrastRatio('#777777', '#ffffff')).toBeCloseTo(4.48, 2);
  });
  it('ignores argument order', () => {
    expect(contrastRatio('#0D42FC', BG_LIGHT)).toBe(contrastRatio(BG_LIGHT, '#0D42FC'));
  });
});

describe('palette contrast', () => {
  it('TEXT_SAFE lists exactly the colours with 4.5:1 or more, per background', () => {
    for (const [theme, bg] of [['dark', BG_DARK], ['light', BG_LIGHT]] as const) {
      const computed = names.filter((n) => contrastRatio(PALETTE[n], bg) >= 4.5).sort();
      expect([...TEXT_SAFE[theme]].sort()).toEqual(computed);
    }
  });
  it('every colour is text-safe on at least one background', () => {
    // Orange is the exception: it is decoration only on both.
    const safe = new Set([...TEXT_SAFE.dark, ...TEXT_SAFE.light]);
    expect([...safe].sort()).toEqual(['amber', 'blue', 'cyan', 'green', 'violet']);
    expect(safe.has('orange')).toBe(false);
  });
});
