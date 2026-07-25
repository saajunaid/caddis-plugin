# Design System: Linear

> **Font substitution for self-contained HTML:**
> - Primary: `Inter` | Mono: `JetBrains Mono`
> ```html
> <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
> ```
> CSS stacks:
> - `font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;`
> - `font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Courier New', monospace;`

## Visual Theme & Atmosphere

Dark-mode-native product design on a near-black canvas (`#08090a`). Content emerges through calibrated luminance hierarchies — darkness is the native medium, not a theme applied over light. Information density is managed through white opacity gradations rather than color variation.

Inter Variable with OpenType `"cv01" "ss03"` globally transforms Inter into Linear's distinctive typeface. The 510 weight (between regular 400 and medium 500) is the signature emphasis weight. Display sizes use aggressive negative letter-spacing (−1.584px at 72px to −1.056px at 48px). The color system is almost entirely achromatic — dark backgrounds, white/gray text — with a single brand accent: indigo-violet (`#5e6ad2` bg / `#7170ff` interactive).

## Color Palette

### Backgrounds
| Name | Hex | Use |
|------|-----|-----|
| Marketing Black | `#08090a` | Page canvas |
| Panel Dark | `#0f1011` | Sidebar, panels |
| Level 3 Surface | `#191a1b` | Cards, dropdowns |
| Secondary Surface | `#28282c` | Hover states |

### Text
| Name | Hex | Use |
|------|-----|-----|
| Primary Text | `#f7f8f8` | Headings, primary |
| Secondary Text | `#d0d6e0` | Body, descriptions |
| Tertiary Text | `#8a8f98` | Placeholders, meta |
| Quaternary Text | `#62666d` | Timestamps, disabled |

### Brand & Accent
| Name | Hex | Use |
|------|-----|-----|
| Brand Indigo | `#5e6ad2` | CTA backgrounds |
| Accent Violet | `#7170ff` | Links, active states |
| Accent Hover | `#828fff` | Hover on accent |

### Borders
| Name | Value | Use |
|------|-------|-----|
| Border Subtle | `rgba(255,255,255,0.05)` | Default |
| Border Standard | `rgba(255,255,255,0.08)` | Cards, inputs |
| Border Solid | `#23252a` | Prominent separations |

### Status
- Success: `#27a644` / `#10b981`

## Typography

Font: Inter Variable with `font-feature-settings: "cv01" "ss03"` on ALL text.

| Role | Size | Weight | Line Height | Letter Spacing |
|------|------|--------|-------------|----------------|
| Display XL | 72px | 510 | 1.00 | −1.584px |
| Display Large | 64px | 510 | 1.00 | −1.408px |
| Display | 48px | 510 | 1.00 | −1.056px |
| Heading 1 | 32px | 400 | 1.13 | −0.704px |
| Heading 2 | 24px | 400 | 1.33 | −0.288px |
| Heading 3 | 20px | 590 | 1.33 | −0.24px |
| Body Large | 18px | 400 | 1.60 | −0.165px |
| Body | 16px | 400 | 1.50 | normal |
| Body Medium | 16px | 510 | 1.50 | normal |
| Small | 15px | 400 | 1.60 | −0.165px |
| Caption | 13px | 400–510 | 1.50 | −0.13px |
| Label | 12px | 400–590 | 1.40 | normal |
| Mono Body | 14px JetBrains | 400 | 1.50 | normal |

**Weight system**: 400 (reading), 510 (emphasis/UI), 590 (announce). No 700.

## Component Styles

### Buttons
```css
/* Ghost (default) */
.btn-ghost {
  background: rgba(255,255,255,0.02);
  color: #e2e4e7;
  border: 1px solid rgb(36,40,44);
  border-radius: 6px;
  padding: 6px 12px;
}
/* Primary (CTA) */
.btn-primary {
  background: #5e6ad2;
  color: #ffffff;
  border-radius: 6px;
  padding: 8px 16px;
}
.btn-primary:hover { background: #828fff; }
/* Pill chip */
.btn-pill {
  border-radius: 9999px;
  border: 1px solid #23252a;
  padding: 0 10px 0 5px;
  color: #d0d6e0;
  font-size: 12px;
  font-weight: 510;
}
```

### Cards
```css
.card {
  background: rgba(255,255,255,0.02);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 8px;
}
.card:hover { background: rgba(255,255,255,0.04); }
```

### Inputs
```css
.input {
  background: rgba(255,255,255,0.02);
  color: #d0d6e0;
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 6px;
  padding: 12px 14px;
}
```

### Navigation
```css
.nav {
  background: #0f1011;
  border-bottom: 1px solid rgba(255,255,255,0.05);
  padding: 0 24px;
}
.nav-link {
  color: #d0d6e0;
  font-size: 13px;
  font-weight: 510;
}
.nav-link:hover { color: #f7f8f8; }
```

## Elevation System

| Level | Treatment |
|-------|-----------|
| Page | `#010102` / `#08090a` |
| Panel | `rgba(255,255,255,0.02)` bg |
| Card | `rgba(255,255,255,0.04)` bg |
| Elevated | `rgba(255,255,255,0.05)` bg |
| Focus | Multi-layer shadow stack |

Elevation uses background opacity stepping, not box-shadows. Borders are always semi-transparent white, never solid on dark backgrounds.

## Border Radius Scale
- Micro (2px): inline badges, toolbar buttons
- Standard (6px): buttons, inputs
- Card (8px): cards, dropdowns
- Panel (12px): featured cards, panels
- Full Pill (9999px): filter chips, status tags
- Circle (50%): icon buttons, avatars

## Layout
- Base unit: 8px
- Max content width: ~1200px
- Section spacing: 80px+ (48px mobile)

## Do's and Don'ts

### Do
- `font-feature-settings: "cv01" "ss03"` on ALL Inter text
- Use weight 510 as default emphasis
- Near-black backgrounds: `#08090a` marketing, `#0f1011` panels, `#191a1b` cards
- Semi-transparent white borders only
- Button backgrounds nearly transparent (`rgba(255,255,255,0.02–0.05)`)
- `#f7f8f8` for primary text — not `#ffffff`
- Brand indigo only for CTA and interactive accents

### Don't
- No pure white `#ffffff` as primary text
- No solid colored button backgrounds
- No positive letter-spacing at display sizes
- No visible/opaque borders on dark backgrounds
- No weight 700 — max is 590
- No warm colors in UI chrome — cool gray + blue-violet only
- No drop shadows for elevation — use background luminance stepping

## Agent Prompt Guide

**Hero section**:
"Hero on `#08090a`. Headline 48px Inter Variable weight 510, line-height 1.00, letter-spacing −1.056px, color `#f7f8f8`, `font-feature-settings: 'cv01' 'ss03'`. Subtitle 18px weight 400, line-height 1.60, `#8a8f98`. CTA button: `#5e6ad2` bg, white text, 6px radius, 8px 16px padding. Ghost: `rgba(255,255,255,0.02)` bg, `1px solid rgba(255,255,255,0.08)` border."

**Card**:
"Card: `rgba(255,255,255,0.02)` bg, `1px solid rgba(255,255,255,0.08)` border, 8px radius. Title 20px Inter 590, `#f7f8f8`, −0.24px tracking, `'cv01' 'ss03'`. Body 15px 400, `#8a8f98`, −0.165px."

**Navigation**:
"Sticky nav on `#0f1011`. Links 13px Inter 510 `#d0d6e0`. Brand indigo CTA. Bottom border `1px solid rgba(255,255,255,0.05)`."
