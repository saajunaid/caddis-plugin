import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { contrastRatio } from '../../ui/src/brand/palette.js';

// Review I2: TEXT_SAFE checks only the brand palette. This test reads the real theme tokens from the CSS and
// checks every text colour against every surface it can sit on, in both themes (WCAG 1.4.3: 4.5:1).
const css = ['theme.css', 'pages.css'].map((f) => readFileSync(new URL(`../../ui/src/${f}`, import.meta.url), 'utf8'));

type Tokens = Record<string, string>;
function block(src: string, re: RegExp): Tokens {
  const body = re.exec(src)?.[1] ?? '';
  const out: Tokens = {};
  for (const m of body.matchAll(/(--[\w-]+):\s*([^;]+);/g)) out[m[1]!] = m[2]!.trim();
  return out;
}
const DARK_RE = /:root,\s*\[data-theme='dark'\]\s*\{([^}]*)\}/;
const LIGHT_RE = /\[data-theme='light'\]\s*\{([^}]*)\}/;
const THEMES: Record<'dark' | 'light', Tokens> = {
  dark: Object.assign({}, ...css.map((s) => block(s, DARK_RE))),
  light: Object.assign({}, ...css.map((s) => block(s, LIGHT_RE))),
};

/** A #rrggbb colour, or an rgba() colour laid over `base`. */
function solid(value: string, base: string): string {
  if (/^#[0-9a-f]{6}$/i.test(value)) return value;
  const m = /^rgba\(\s*(\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\s*\)$/.exec(value);
  if (!m) throw new Error(`unsupported colour: ${value}`);
  const a = Number(m[4]);
  const b = parseInt(base.slice(1), 16);
  const ch = [(b >> 16) & 255, (b >> 8) & 255, b & 255];
  return `#${[1, 2, 3].map((i, k) => Math.round(Number(m[i]) * a + ch[k]! * (1 - a)).toString(16).padStart(2, '0')).join('')}`;
}

// Surfaces: page canvas, list panel (lane), card, raised/hover (elevated), selected row (mk-sel).
const SURFACES = ['--bg-canvas', '--bg-lane', '--bg-card', '--bg-elevated', '--mk-sel'];
const TEXT = ['--text-main', '--text-sub', '--text-dim', '--mk-bad', '--mk-good', '--mk-warn', '--mk-accent'];
const CHIPS = ['waiting', 'gate', 'bad', 'coord', 'done'];

describe.each(['dark', 'light'] as const)('%s theme text contrast', (theme) => {
  const t = THEMES[theme];
  const get = (name: string): string => {
    const v = t[name];
    if (!v) throw new Error(`${theme}: token ${name} is missing`);
    return v;
  };

  it.each(TEXT)('%s is 4.5:1 or more on every surface', (fg) => {
    for (const s of SURFACES) {
      const ratio = contrastRatio(get(fg), get(s));
      expect(ratio, `${theme} ${fg} on ${s} = ${ratio.toFixed(2)}`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it.each(CHIPS)('chip %s text is 4.5:1 or more on its chip, on every surface', (c) => {
    for (const s of SURFACES) {
      const bg = solid(get(`--chip-${c}-bg`), get(s));
      const ratio = contrastRatio(get(`--chip-${c}-fg`), bg);
      expect(ratio, `${theme} chip ${c} on ${s} = ${ratio.toFixed(2)}`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it('command text and the active nav link pass', () => {
    expect(contrastRatio(get('--yellow'), get('--bg-elevated'))).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio(get('--purple'), solid(get('--tone-purple-bg'), get('--bg-card')))).toBeGreaterThanOrEqual(4.5);
  });
});
