/**
 * Terminal TrueColor theme for Caddis.
 * Features #00FFA6 (Cyber Mint) with high-contrast electric accents.
 */
import pc from 'picocolors';

export function hex(hexStr: string): (text: string) => string {
  const clean = hexStr.replace('#', '');
  const r = parseInt(clean.substring(0, 2), 16);
  const g = parseInt(clean.substring(2, 4), 16);
  const b = parseInt(clean.substring(4, 6), 16);
  return (text: string) => (pc.isColorSupported ? `\x1b[38;2;${r};${g};${b}m${text}\x1b[39m` : text);
}

export const theme = {
  // Primary Brand
  mint: hex('#00FFA6'), // Radiant Cyber Mint (#00FFA6)

  // Contrasting Accents
  violet: hex('#A855F7'), // Electric Violet (high-contrast complement)
  magenta: hex('#FF007F'), // Neon Magenta (warm contrast)
  sky: hex('#00D2FF'), // Electric Sky Cyan (cool highlight)
  amber: hex('#FFB703'), // Neon Amber (warning / drift)
  coral: hex('#FF4A6E'), // Electric Coral (errors)

  // Formatter utilities
  dim: pc.dim,
  bold: pc.bold,
  isColorSupported: pc.isColorSupported,
};
