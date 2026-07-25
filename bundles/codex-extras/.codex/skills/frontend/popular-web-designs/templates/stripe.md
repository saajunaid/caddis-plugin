# Design System: Stripe

> **Font substitution for self-contained HTML:**
> - Primary: `Source Sans 3` | Mono: `Source Code Pro`
> ```html
> <link href="https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@300;400;500;600&family=Source+Code+Pro:wght@400;500;700&display=swap" rel="stylesheet">
> ```
> CSS stacks:
> - `font-family: 'Source Sans 3', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;`
> - `font-family: 'Source Code Pro', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Courier New', monospace;`

## Visual Theme & Atmosphere

The gold standard of fintech design — simultaneously technical and luxurious. White canvas (`#ffffff`) with deep navy headings (`#061b31`) and a signature purple (`#533afd`) that reads as confident and premium. Custom `sohne-var` variable font with OpenType `"ss01"` everywhere. Headlines use weight 300 — an extraordinarily light weight that creates ethereal authority. This is the opposite of "bold hero headline" convention.

The defining technical signature: multi-layer blue-tinted shadows (`rgba(50,50,93,0.25)` + `rgba(0,0,0,0.1)`) that feel atmospheric — like elements floating in a twilight sky.

## Color Palette

### Primary
| Name | Hex | Use |
|------|-----|-----|
| Stripe Purple | `#533afd` | Primary CTA, links, interactive |
| Deep Navy | `#061b31` | All headings (never pure black) |
| Pure White | `#ffffff` | Page background, cards |

### Brand & Dark
| Name | Hex | Use |
|------|-----|-----|
| Brand Dark | `#1c1e54` | Dark sections, footer |
| Dark Navy | `#0d253d` | Near-black surfaces |

### Accents (decorative only — not for buttons/links)
| Name | Hex | Use |
|------|-----|-----|
| Ruby | `#ea2261` | Icons, gradient decoration |
| Magenta | `#f96bee` | Gradients, highlights |
| Magenta Light | `#ffd7ef` | Tinted surfaces |

### Interactive
| Name | Hex | Use |
|------|-----|-----|
| Purple Hover | `#4434d4` | Hover on primary elements |
| Purple Light | `#b9b9f9` | Ghost button border |
| Body Text | `#64748d` | Secondary, descriptions |
| Label Text | `#273951` | Form labels, sub-headings |

### Surfaces & Borders
| Name | Hex | Use |
|------|-----|-----|
| Border | `#e5edf5` | Cards, dividers, inputs |
| Success Green | `#15be53` | Status (bg at 0.2 alpha) |
| Success Text | `#108c3d` | Success badge text |

### Shadows
- Primary (blue-tinted): `rgba(50,50,93,0.25)`
- Secondary: `rgba(0,0,0,0.1)`
- Ambient: `rgba(23,23,23,0.08)`
- Soft: `rgba(23,23,23,0.06)`

## Typography

Font: sohne-var → Source Sans 3 with `font-feature-settings: "ss01"` on ALL text. `"tnum"` for financial/tabular numbers.

| Role | Size | Weight | Line Height | Letter Spacing |
|------|------|--------|-------------|----------------|
| Display Hero | 56px | 300 | 1.03 | −1.4px |
| Display Large | 48px | 300 | 1.15 | −0.96px |
| Section Heading | 32px | 300 | 1.10 | −0.64px |
| Sub-heading Large | 26px | 300 | 1.12 | −0.26px |
| Sub-heading | 22px | 300 | 1.10 | −0.22px |
| Body Large | 18px | 300 | 1.40 | normal |
| Body | 16px | 300–400 | 1.40 | normal |
| Button | 16px | 400 | 1.00 | normal |
| Caption | 13px | 400 | normal | normal |
| Caption Tabular | 12px | 300–400 | 1.33 | −0.36px + "tnum" |
| Code Body | 12px SourceCodePro | 500 | 2.00 | normal |
| Code Bold | 12px SourceCodePro | 700 | 2.00 | normal |

**Key principle**: Weight 300 is the default for headings AND body. Weight 400 only for buttons/navigation. No 600–700 in sohne-var.

## Component Styles

### Buttons
```css
/* Primary Purple */
.btn-primary {
  background: #533afd;
  color: #ffffff;
  padding: 8px 16px;
  border-radius: 4px;
  font-size: 16px;
  font-weight: 400;
  font-feature-settings: "ss01";
}
.btn-primary:hover { background: #4434d4; }

/* Ghost / Outlined */
.btn-ghost {
  background: transparent;
  color: #533afd;
  border: 1px solid #b9b9f9;
  border-radius: 4px;
  padding: 8px 16px;
}
.btn-ghost:hover { background: rgba(83,58,253,0.05); }
```

### Cards
```css
.card {
  background: #ffffff;
  border: 1px solid #e5edf5;
  border-radius: 6px;
  box-shadow: rgba(50,50,93,0.25) 0px 30px 45px -30px,
              rgba(0,0,0,0.1) 0px 18px 36px -18px;
}
```

### Success Badge
```css
.badge-success {
  background: rgba(21,190,83,0.2);
  color: #108c3d;
  border: 1px solid rgba(21,190,83,0.4);
  border-radius: 4px;
  padding: 1px 6px;
  font-size: 10px;
  font-weight: 300;
}
```

### Navigation
```css
.nav {
  background: #ffffff;
  backdrop-filter: blur(12px);
  border-bottom: 1px solid #e5edf5;
}
.nav-link {
  color: #061b31;
  font-size: 14px;
  font-weight: 400;
  font-feature-settings: "ss01";
}
```

### Dark Brand Section
```css
.section-dark {
  background: #1c1e54;
  color: #ffffff;
}
/* Heading inside dark section */
.section-dark h2 {
  color: #ffffff;
  font-weight: 300;
  letter-spacing: -0.64px;
}
/* Body inside dark section */
.section-dark p {
  color: rgba(255,255,255,0.7);
  font-weight: 300;
}
```

## Elevation System

| Level | Shadow | Use |
|-------|--------|-----|
| Flat | None | Page, inline |
| Ambient | `rgba(23,23,23,0.06) 0px 3px 6px` | Subtle card lift |
| Standard | `rgba(23,23,23,0.08) 0px 15px 35px` | Cards |
| Elevated | `rgba(50,50,93,0.25) 0px 30px 45px -30px, rgba(0,0,0,0.1) 0px 18px 36px -18px` | Featured, dropdowns |
| Deep | `rgba(3,3,39,0.25) 0px 14px 21px -14px, rgba(0,0,0,0.1) 0px 8px 17px -8px` | Modals |

## Border Radius Scale
- Standard (4px): buttons, inputs, badges, cards — the workhorse
- Comfortable (6px): nav, larger interactive elements
- Large (8px): featured cards, hero elements

## Layout
- Max content width: ~1080px
- Base spacing unit: 8px (dense at small end)
- Section rhythm: white sections alternate with `#1c1e54` dark sections

## Do's and Don'ts

### Do
- `font-feature-settings: "ss01"` on every sohne-var/Source Sans 3 text
- Weight 300 for headings and body — lightness is the signature
- Blue-tinted shadows (`rgba(50,50,93,0.25)`) on all elevated elements
- `#061b31` deep navy for headings, never `#000000`
- Border-radius 4–8px only — conservative
- `"tnum"` for financial/tabular numbers

### Don't
- No weight 600–700 on headings
- No large border-radius (12px+, pill shapes) on cards or buttons
- No neutral gray shadows — always blue-tinted
- No warm accent colors for interactive elements
- No pure black headings — always `#061b31`
- No magenta/ruby for buttons/links — decorative only

## Agent Prompt Guide

**Hero section**:
"White background. Headline 48px Source Sans 3 weight 300, line-height 1.15, letter-spacing −0.96px, color `#061b31`, `font-feature-settings: 'ss01'`. Subtitle 18px weight 300, line-height 1.40, color `#64748d`. Purple CTA (`#533afd`, 4px radius, 8px 16px padding, white text) + ghost button (transparent, `1px solid #b9b9f9`, `#533afd` text, 4px radius)."

**Card**:
"White bg, `1px solid #e5edf5` border, 6px radius. Shadow: `rgba(50,50,93,0.25) 0px 30px 45px -30px, rgba(0,0,0,0.1) 0px 18px 36px -18px`. Title 22px Source Sans 3 weight 300, −0.22px tracking, `#061b31`, `'ss01'`. Body 16px weight 300, `#64748d`."

**Dark brand section**:
"`#1c1e54` background, white text. Headline 32px weight 300, −0.64px tracking, `'ss01'`. Body 16px weight 300, `rgba(255,255,255,0.7)`. Internal cards: `rgba(255,255,255,0.1)` border, 6px radius."
