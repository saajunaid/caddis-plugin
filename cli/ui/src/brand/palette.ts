/**
 * Caddis brand palette and WCAG 2.x contrast helper.
 * Framework-free: the hub UI and the CLI banner both import this file.
 */
export const PALETTE = {
  blue: '#0D42FC',
  cyan: '#00CAD5',
  green: '#91D202',
  amber: '#FDAD01',
  orange: '#FC4E23',
  violet: '#8730FB',
} as const;

export type PaletteName = keyof typeof PALETTE;

/** Dracula-style dark background and the light theme background. */
export const BG_DARK = '#282a36';
export const BG_LIGHT = '#f8f8f2';

/**
 * Colours that reach 4.5:1 as body text, per theme background.
 * Every other colour is decoration only (marks, borders, fills, large graphics).
 * A test checks this list against the computed ratios.
 */
export const TEXT_SAFE: { dark: readonly PaletteName[]; light: readonly PaletteName[] } = {
  dark: ['cyan', 'green', 'amber'],
  light: ['blue', 'violet'],
};

function channel(v: number): number {
  const s = v / 255;
  return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

/** WCAG relative luminance of a #rrggbb colour. */
export function luminance(hex: string): number {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex);
  if (!m) throw new Error(`Not a #rrggbb colour: ${hex}`);
  const n = parseInt(m[1]!, 16);
  return 0.2126 * channel((n >> 16) & 255) + 0.7152 * channel((n >> 8) & 255) + 0.0722 * channel(n & 255);
}

/** WCAG contrast ratio, from 1 to 21. Order of the arguments does not matter. */
export function contrastRatio(hexA: string, hexB: string): number {
  const a = luminance(hexA);
  const b = luminance(hexB);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}
