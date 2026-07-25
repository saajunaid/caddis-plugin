# Word Cloud — Premium Palette Reference

8 curated palettes. Each defines CSS custom properties. Apply by adding the palette name as a class on `.word-cloud-wrapper` (React/HTML) or passing `palette` prop.

---

## Obsidian (default dark)
Moody, editorial, sophisticated.
```css
.obsidian {
  --cloud-bg:       #0c0a09;
  --cloud-surface:  #1c1917;
  --cloud-noun:     #e7e5e4;
  --cloud-positive: #4ade80;
  --cloud-negative: #f87171;
  --cloud-verb:     #c4b5fd;
  --cloud-neutral:  #78716c;
  --cloud-glow:     rgba(167,139,250,0.18);
}
```

## Ivory (default light)
Clean, minimal, luxury print editorial.
```css
.ivory {
  --cloud-bg:       #fafaf9;
  --cloud-surface:  #ffffff;
  --cloud-noun:     #1c1917;
  --cloud-positive: #15803d;
  --cloud-negative: #b91c1c;
  --cloud-verb:     #6d28d9;
  --cloud-neutral:  #a8a29e;
  --cloud-glow:     rgba(109,40,217,0.08);
}
```

## Aurora
Dark with vibrant neon aurora borealis palette.
```css
.aurora {
  --cloud-bg:       #030712;
  --cloud-surface:  #0f0f23;
  --cloud-noun:     #60a5fa;
  --cloud-positive: #34d399;
  --cloud-negative: #fb7185;
  --cloud-verb:     #e879f9;
  --cloud-neutral:  #6b7280;
  --cloud-glow:     rgba(96,165,250,0.2);
}
```

## Parchment
Warm, aged paper, literary.
```css
.parchment {
  --cloud-bg:       #f5f0e8;
  --cloud-surface:  #fdf8f0;
  --cloud-noun:     #44260c;
  --cloud-positive: #3d6b1c;
  --cloud-negative: #8b1a1a;
  --cloud-verb:     #7b3e00;
  --cloud-neutral:  #9c8060;
  --cloud-glow:     rgba(180,120,40,0.1);
}
```

## Midnight Ocean
Deep navy, cool and corporate-elegant.
```css
.midnight_ocean {
  --cloud-bg:       #020817;
  --cloud-surface:  #0f172a;
  --cloud-noun:     #93c5fd;
  --cloud-positive: #6ee7b7;
  --cloud-negative: #fca5a5;
  --cloud-verb:     #a5b4fc;
  --cloud-neutral:  #475569;
  --cloud-glow:     rgba(147,197,253,0.15);
}
```

## Neon Noir
Dark background, vivid neon accents. Cyberpunk energy.
```css
.neon_noir {
  --cloud-bg:       #09090b;
  --cloud-surface:  #18181b;
  --cloud-noun:     #f4f4f5;
  --cloud-positive: #00ff87;
  --cloud-negative: #ff2d55;
  --cloud-verb:     #bf5af2;
  --cloud-neutral:  #52525b;
  --cloud-glow:     rgba(0,255,135,0.12);
}
```

## Botanical
Earthy greens, natural, calm.
```css
.botanical {
  --cloud-bg:       #f0f4f0;
  --cloud-surface:  #ffffff;
  --cloud-noun:     #1e3a2f;
  --cloud-positive: #2d6a4f;
  --cloud-negative: #b5482a;
  --cloud-verb:     #557a45;
  --cloud-neutral:  #8aab7e;
  --cloud-glow:     rgba(46,107,79,0.1);
}
```

## Rose Gold
Warm pink and gold tones. Elegant, feminine, premium.
```css
.rose_gold {
  --cloud-bg:       #1a0e10;
  --cloud-surface:  #2a1418;
  --cloud-noun:     #f8d7b0;
  --cloud-positive: #f0a070;
  --cloud-negative: #e8507a;
  --cloud-verb:     #d4b090;
  --cloud-neutral:  #8a6060;
  --cloud-glow:     rgba(248,215,176,0.12);
}
```

---

## Usage in React
```tsx
<WordCloud palette="aurora" ... />
// Applies via className: <div class="word-cloud-wrapper aurora">
```

## Usage in HTML
```html
<div class="word-cloud-wrapper midnight_ocean" data-theme="dark">
```

## Usage in Python (matplotlib colormap equivalents)
| Palette | Closest matplotlib colormap |
|---------|---------------------------|
| obsidian | `plasma_r` |
| aurora | `cool` |
| parchment | `copper` |
| midnight_ocean | `Blues` |
| neon_noir | `spring` |
| botanical | `Greens` |
| rose_gold | `RdPu` |
