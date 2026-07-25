# Design System: Vercel

> **Font substitution for self-contained HTML:**
> - Primary: `Geist` | Mono: `Geist Mono`
> ```html
> <link href="https://fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600&family=Geist+Mono:wght@400;500&display=swap" rel="stylesheet">
> ```
> CSS stacks:
> - `font-family: 'Geist', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;`
> - `font-family: 'Geist Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Courier New', monospace;`

## Visual Theme & Atmosphere

Developer infrastructure design taken to its extreme — restrained white (`#ffffff`) and near-black (`#171717`) with gallery-like emptiness. Minimalism as engineering principle: every unnecessary token removed until only structure remains.

The defining technical signature: **shadow-as-border**. Instead of `border: 1px solid #ebebeb`, Vercel uses `box-shadow: 0px 0px 0px 1px rgba(0,0,0,0.08)`. The entire elevation system is layered multi-value shadow stacks. Geist Sans with aggressive negative letter-spacing (−2.4px to −2.88px at display) creates headlines that feel "compressed, urgent, engineered — like code minified for production."

## Color Palette

### Primary
| Name | Hex | Use |
|------|-----|-----|
| Vercel Black | `#171717` | Primary text, headings, dark surfaces |
| Pure White | `#ffffff` | Page background, cards |
| True Black | `#000000` | Console/code contexts |

### Workflow Accents (use ONLY in workflow pipeline context)
| Stage | Color | Use |
|-------|-------|-----|
| Develop | `#0a72ef` | Development step |
| Preview | `#de1d8d` | Preview deployment step |
| Ship | `#ff5b4f` | Production step |

### Neutral Scale
| Name | Hex | Use |
|------|-----|-----|
| Gray 900 | `#171717` | Primary text |
| Gray 600 | `#4d4d4d` | Body, descriptions |
| Gray 500 | `#666666` | Tertiary, muted |
| Gray 400 | `#808080` | Placeholders |
| Gray 100 | `#ebebeb` | Borders, dividers |
| Gray 50 | `#fafafa` | Surface tint, inner highlight |

### Interactive
| Name | Value | Use |
|------|-------|-----|
| Link Blue | `#0072f5` | Link color + underline |
| Focus Blue | `hsla(212,100%,48%,1)` | Focus ring on all interactive elements |
| Badge Blue Bg | `#ebf5ff` | Pill badge background |
| Badge Blue Text | `#0068d6` | Pill badge text |

### Shadows
- **Border shadow** (signature): `rgba(0,0,0,0.08) 0px 0px 0px 1px`
- **Light ring**: `rgb(235,235,235) 0px 0px 0px 1px`
- **Subtle lift**: `rgba(0,0,0,0.04) 0px 2px 2px`
- **Depth**: `rgba(0,0,0,0.04) 0px 8px 8px -8px`
- **Inner glow**: `#fafafa 0px 0px 0px 1px` (the glow that makes the system work)
- **Full card stack**: border + subtle + depth + inner glow

## Typography

Font: Geist with `font-feature-settings: "liga"` on ALL text. `"tnum"` for tabular numbers.

| Role | Size | Weight | Line Height | Letter Spacing |
|------|------|--------|-------------|----------------|
| Display Hero | 48px | 600 | 1.00–1.17 | −2.4px to −2.88px |
| Section Heading | 40px | 600 | 1.20 | −2.4px |
| Sub-heading Large | 32px | 600 | 1.25 | −1.28px |
| Card Title | 24px | 600 | 1.33 | −0.96px |
| Body Large | 20px | 400 | 1.80 | normal |
| Body | 18px | 400 | 1.56 | normal |
| Body Small | 16px | 400 | 1.50 | normal |
| Body Medium | 16px | 500 | 1.50 | normal |
| Button / Link | 14px | 500 | 1.43 | normal |
| Caption | 12px | 400–500 | 1.33 | normal |
| Mono Body | 16px Geist Mono | 400 | 1.50 | normal |
| Mono Caption | 13px Geist Mono | 500 | 1.54 | normal |
| Micro Badge | 7px | 700 | 1.00 | normal (uppercase) |

**Three weights, strict roles**: 400 (body), 500 (UI/interactive), 600 (headings). No 700 except micro-badges. Hierarchy through size and tracking, not weight.

## Component Styles

### Buttons
```css
/* Primary (shadow-bordered white) */
.btn-primary {
  background: #ffffff;
  color: #171717;
  padding: 8px 16px;
  border-radius: 6px;
  box-shadow: rgb(235,235,235) 0px 0px 0px 1px;
  font-size: 14px;
  font-weight: 500;
  font-feature-settings: "liga";
}
.btn-primary:hover { background: #171717; color: #ffffff; }

/* Dark CTA */
.btn-dark {
  background: #171717;
  color: #ffffff;
  padding: 8px 16px;
  border-radius: 6px;
  font-weight: 500;
}

/* Pill badge */
.badge-pill {
  background: #ebf5ff;
  color: #0068d6;
  border-radius: 9999px;
  padding: 0 10px;
  font-size: 12px;
  font-weight: 500;
}
```

### Cards (shadow-as-border, NOT CSS border)
```css
.card {
  background: #ffffff;
  border-radius: 8px;
  /* Full card shadow stack */
  box-shadow:
    rgba(0,0,0,0.08) 0px 0px 0px 1px,
    rgba(0,0,0,0.04) 0px 2px 2px,
    rgba(0,0,0,0.04) 0px 8px 8px -8px,
    #fafafa 0px 0px 0px 1px;
}
/* Image cards — top-rounded */
.card-image {
  border-radius: 12px 12px 0px 0px;
  border: 1px solid #ebebeb;
}
```

### Navigation
```css
.nav {
  background: #ffffff;
  position: sticky;
  top: 0;
}
.nav-link {
  color: #171717;
  font-size: 14px;
  font-weight: 500;
  font-feature-settings: "liga";
}
.nav-link:hover { font-weight: 600; }
```

### Focus Ring (all interactive elements)
```css
:focus-visible {
  outline: 2px solid hsla(212,100%,48%,1);
  outline-offset: 2px;
}
```

## Elevation System

| Level | Shadow | Use |
|-------|--------|-----|
| Flat | None | Page background |
| Ring | `rgba(0,0,0,0.08) 0px 0px 0px 1px` | Shadow-as-border |
| Light Ring | `rgb(235,235,235) 0px 0px 0px 1px` | Tabs, images |
| Subtle Card | Ring + `rgba(0,0,0,0.04) 0px 2px 2px` | Standard cards |
| Full Card | Ring + Subtle + Depth + Inner Glow | Featured panels |
| Focus | `2px solid hsla(212,100%,48%,1)` | Keyboard focus |

## Border Radius Scale
- Standard (6px): buttons, links
- Comfortable (8px): cards, list items
- Image (12px): featured cards, top-rounded containers
- Large (64px): tab nav pills
- Full (9999px): badges, status pills

## Layout
- Max content width: ~1200px
- Spacing scale jumps from 16px → 32px (no 20px/24px)
- Section spacing: 80–120px+ (gallery emptiness is intentional)
- Section separators: `border-bottom: 1px solid #171717` (full dark lines)
- No background color variation — depth from shadow + border only

## Do's and Don'ts

### Do
- Shadow-as-border everywhere — `0px 0px 0px 1px rgba(0,0,0,0.08)` not CSS `border`
- `"liga"` on all Geist text — ligatures are structural
- 3 weights: 400 (read), 500 (interact), 600 (announce)
- Include the inner `#fafafa` ring in card shadows — it's the glow
- `#171717` not `#000000` for primary text
- Aggressive negative tracking at display sizes

### Don't
- No positive letter-spacing on Geist
- No weight 700 except micro-badges
- No CSS `border` on cards — use shadow technique
- No warm colors (orange, yellow, green) in UI chrome
- No workflow accent colors (Red/Pink/Blue) decoratively
- No heavy shadows (>0.1 opacity)
- No pill radius on primary buttons — pills are badges/tags only

## Agent Prompt Guide

**Hero section**:
"White background. Headline 48px Geist weight 600, line-height 1.00, letter-spacing −2.4px, color `#171717`, `font-feature-settings: 'liga'`. Subtitle 20px weight 400, line-height 1.80, color `#4d4d4d`. Dark CTA (`#171717` bg, white text, 6px radius, 8px 16px) + ghost (white, `rgb(235,235,235) 0px 0px 0px 1px` shadow, 6px radius)."

**Card** (no CSS border):
"White bg, 8px radius. Shadow stack: `rgba(0,0,0,0.08) 0px 0px 0px 1px, rgba(0,0,0,0.04) 0px 2px 2px, #fafafa 0px 0px 0px 1px`. Title 24px Geist weight 600, −0.96px tracking, `#171717`. Body 16px weight 400, `#4d4d4d`."

**Badge**:
"`#ebf5ff` bg, `#0068d6` text, 9999px radius, 0 10px padding, 12px Geist weight 500."

**Workflow section** (Develop→Preview→Ship):
"Three steps. Develop: `#0a72ef`. Preview: `#de1d8d`. Ship: `#ff5b4f`. Labels 14px Geist Mono uppercase. Titles 24px Geist weight 600. Body 16px weight 400, `#4d4d4d`."
