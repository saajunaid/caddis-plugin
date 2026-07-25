---
name: word-cloud
description: Generate beautiful word clouds — static or animated — from any input source. Handles text extraction from PDF, DOCX, XLSX, PPTX, HTML, CSV, TXT and produces production-ready components. Includes light/dark theming, sentiment/POS color coding, shape masking, and multiple animation modes.
---

# Word Cloud Skill
## How to Use This Skill With Any AI Agent

This skill works with **any AI coding assistant** — Claude, GitHub Copilot (via Copilot Chat), Cursor, Windsurf, ChatGPT, Gemini Code Assist, etc.

**To activate it, paste this prompt into your AI agent:**
```
Read the file word-cloud-skill/SKILL.md and follow its instructions to generate a word cloud.
My input: [paste text OR file path]
My target stack: [react / html / python / streamlit]
```

**For GitHub Copilot specifically:**
- Open Copilot Chat in VS Code
- Drag the `SKILL.md` file into the chat, or use `#file:word-cloud-skill/SKILL.md`
- Then describe what you want

**For Cursor:**
- Add `word-cloud-skill/SKILL.md` to Cursor's context with `@file`
- Or copy its contents into `.cursorrules`

**For any other agent:**
- Simply paste the contents of `SKILL.md` as a system prompt or context block

---

# Word Cloud Skill

Generates **premium, visually stunning word clouds** from any text source. The output is always a production-ready frontend component — not a placeholder or demo. Think editorial design meets data visualization: luxurious typography, intentional color, and satisfying motion.

## Quick Decision Tree

```
Input source? → See §1 (Text Extraction)
Target stack?  → See §2 (Stack Selection)
Want animation? → See §3 (Animation Modes)
Sentiment/POS?  → See §4 (NLP Highlighting)
Shape/layout?   → See §5 (Shape Masking)
Dark/light?     → See §6 (Theming)
Agentic use?    → See §7 (Agent Interface)
```

---

## §1 · Text Extraction

Extract raw text first, then proceed to rendering. Use the appropriate method per file type.

### Plain Text / HTML
Use directly — strip HTML tags with a regex or DOMParser if needed.

### PDF
Read `/mnt/skills/public/pdf-reading/SKILL.md` for extraction strategy.  
Preferred: `pdfplumber` (Python) or `pdf-parse` (Node).

### DOCX
Read `/mnt/skills/public/docx/SKILL.md`.  
Preferred: `python-docx` (Python) or `mammoth` (JS/browser).

### XLSX / CSV
Read `/mnt/skills/public/xlsx/SKILL.md`.  
Concatenate all cell text values from all sheets. For CSV: join all rows.

### PPTX
Read `/mnt/skills/public/pptx/SKILL.md`.  
Extract text from all slide shapes and notes.

### After extraction
- Remove stopwords (see `references/stopwords.md`)
- Count word frequencies
- Optionally run NLP (§4) before rendering

---

## §2 · Stack Selection

| Stack | Primary Renderer | Notes |
|-------|-----------------|-------|
| React (browser) | D3-cloud + SVG | Most flexible, best animations |
| Plain HTML | wordcloud2.js (canvas) | Zero-dependency drop-in |
| Streamlit | Python `wordcloud` + matplotlib OR `st.components` with D3 | Server-side generation or embedded HTML |
| Vue / Svelte | D3-cloud | Same as React pattern |
| Next.js / SSR | D3-cloud client-side only (dynamic import) | `use client` + `typeof window !== 'undefined'` guard |
| Static export / PNG | Python `wordcloud` lib | Best for server-side image export |

**Default**: When target stack is unspecified or ambiguous → generate a **self-contained HTML file** (works everywhere, zero deps from CDN).

Read the relevant reference file for your stack:
- React → `references/react.md`
- HTML → `references/html.md`
- Python/Streamlit → `references/python.md`

---

## §3 · Animation Modes

### Static
No animation. Words are placed and stay. Best for exports, print, or performance-sensitive contexts.

### Entrance (default for web)
Words fade/scale/fly in on load. Stagger by frequency: most-frequent words appear first.
```css
@keyframes wordEntrance {
  from { opacity: 0; transform: scale(0.4) rotate(var(--r)); }
  to   { opacity: 1; transform: scale(1)   rotate(var(--r)); }
}
```
Apply `animation-delay` proportional to word rank.

### Hover interactions (always include on web)
- **Scale + glow** on hover
- **Tooltip** showing word + frequency + sentiment label
- **Cursor**: pointer

### Idle float (optional, premium feel)
Subtle sinusoidal translation on each word, offset by word index. Creates a living, breathing feel.
```css
@keyframes float {
  0%, 100% { transform: translateY(0px) rotate(var(--r)); }
  50%       { transform: translateY(-4px) rotate(var(--r)); }
}
```

### Full cinematic (max impact)
Combine entrance + idle + hover. Add a radial gradient pulse behind the cloud on load. Use sparingly.

---

## §4 · NLP Highlighting

Color-code words by semantic category. Choose the right approach for the stack:

### Approach A — Keyword Lists (fastest, no deps)
Use bundled lists in `references/nlp-keywords.md`:
- Positive sentiment words → accent color (gold / emerald)
- Negative sentiment words → warning color (rose / amber)
- Strong verbs → highlight color (violet / cyan)

### Approach B — Browser-side NLP (React/HTML)
Use `compromise.js` (CDN: `https://unpkg.com/compromise`) for POS tagging.
```js
import nlp from 'compromise'
const doc = nlp(text)
const verbs = new Set(doc.verbs().out('array'))
const nouns = new Set(doc.nouns().out('array'))
```
Then assign color by category when building the word list.

### Approach C — Python NLP (Streamlit / server)
```python
import nltk
from nltk.sentiment import SentimentIntensityAnalyzer
sia = SentimentIntensityAnalyzer()
# score each word, assign to positive/negative/neutral bucket
```
Or use `spaCy` for POS tagging.

### Color Assignment Schema
```
Positive sentiment  →  var(--cloud-positive)   # e.g. #4ade80 / #22c55e
Negative sentiment  →  var(--cloud-negative)   # e.g. #f87171 / #ef4444  
Strong verbs        →  var(--cloud-verb)        # e.g. #a78bfa / #8b5cf6
Nouns (default)     →  var(--cloud-noun)        # base palette gradient
Neutral / other     →  var(--cloud-neutral)     # muted version of base
```

---

## §5 · Shape Masking

Shape masking confines word placement to a silhouette. 

### Available built-in shapes
See `references/shapes.md` for SVG path data:
- Circle (default)
- Speech bubble
- Star / burst
- Diamond
- Cloud silhouette
- Heart
- Arrow
- Custom SVG upload

### How to apply (D3-cloud)
D3-cloud uses a pixel-mask approach. For complex shapes, rasterize the SVG to a canvas, read pixel data, and pass as the mask to the layout engine. See `references/react.md` §Shape Masking.

### How to apply (Python wordcloud)
```python
from PIL import Image
import numpy as np
mask = np.array(Image.open("shape.png"))
wc = WordCloud(mask=mask, background_color=None, mode="RGBA")
```

---

## §6 · Theming

Always implement **both light and dark modes** using CSS custom properties.

```css
:root {
  /* Light theme */
  --cloud-bg:        #fafaf9;
  --cloud-surface:   #ffffff;
  --cloud-text:      #1c1917;
  --cloud-positive:  #16a34a;
  --cloud-negative:  #dc2626;
  --cloud-verb:      #7c3aed;
  --cloud-noun:      #0369a1;
  --cloud-neutral:   #78716c;
  --cloud-shadow:    rgba(0,0,0,0.08);
}

[data-theme="dark"], .dark {
  --cloud-bg:        #0c0a09;
  --cloud-surface:   #1c1917;
  --cloud-text:      #fafaf9;
  --cloud-positive:  #4ade80;
  --cloud-negative:  #f87171;
  --cloud-verb:      #c4b5fd;
  --cloud-noun:      #7dd3fc;
  --cloud-neutral:   #a8a29e;
  --cloud-shadow:    rgba(0,0,0,0.4);
}
```

Use `prefers-color-scheme` media query as default, with a manual toggle override.

### Premium palette presets
See `references/palettes.md` for 8 curated color schemes:
- **Obsidian** (dark, moody, editorial)
- **Ivory** (light, minimal, luxury)
- **Aurora** (dark, colorful, vibrant)
- **Parchment** (warm, sepia, editorial)
- **Midnight Ocean** (deep blue, cool)
- **Neon Noir** (dark bg, neon accents)
- **Botanical** (earthy greens)
- **Rose Gold** (warm pink/gold)

---

## §7 · Agent Interface

When used in an agentic pipeline (agents.md workflow), accept and return structured data:

### Input schema
```json
{
  "text": "string | null",
  "file_path": "string | null",
  "options": {
    "max_words": 150,
    "shape": "circle | star | speech_bubble | heart | diamond | custom",
    "custom_shape_svg": "string | null",
    "animation": "none | entrance | float | cinematic",
    "highlight": ["sentiment", "verbs", "nouns", "custom"],
    "custom_highlight_words": ["array", "of", "words"],
    "theme": "auto | light | dark",
    "palette": "obsidian | ivory | aurora | parchment | midnight_ocean | neon_noir | botanical | rose_gold",
    "stack": "react | html | python | streamlit",
    "width": 800,
    "height": 500,
    "font_family": "string | null"
  }
}
```

### Output schema
```json
{
  "component_code": "string",
  "word_frequencies": [{"word": "string", "count": 42, "category": "positive|negative|verb|noun|neutral"}],
  "stack": "react | html | python",
  "theme_vars": { "--cloud-bg": "#...", "...": "..." },
  "preview_notes": "string"
}
```

### agents.md usage
When invoked by an orchestrator agent, read the input JSON from the task context, execute §1 extraction if `file_path` is provided, then generate the component per the `stack` option. Return the output JSON. Do not ask clarifying questions in agentic mode — use defaults for missing options.

---

## §8 · Design Principles

These are non-negotiable for premium output:

1. **Typography first** — word size encoding must feel *intentional*, not mechanical. Use a range of at least 4–6 size steps (e.g. 12px → 72px). Choose a distinctive font — never default system fonts. Good defaults: `Playfair Display`, `Syne`, `Space Grotesk`, `DM Serif Display`, `Archivo Black`.

2. **Density** — aim for 60–150 words. Too sparse feels empty; too dense is unreadable. Scale `max_words` based on canvas size.

3. **Rotation** — use sparingly. Max ±30° for most words, with only a few at ±90°. Pure horizontal reads faster; slight rotation adds energy.

4. **Padding** — minimum 2px between words. 4–6px for luxury feel.

5. **Background** — never pure white or pure black. Use off-tones: `#fafaf9`, `#0c0a09`. Add a subtle radial gradient or noise texture for depth.

6. **Responsive** — the container must be responsive. Use `viewBox` for SVG, or `ResizeObserver` + re-layout for canvas.

7. **Accessibility** — include a hidden `<ul>` list of words for screen readers. Provide `aria-label` on the cloud container.

---

## §9 · Output Checklist

Before delivering, verify:

- [ ] Text extracted and stopwords removed
- [ ] Top N words computed (N = max_words, default 100)
- [ ] Sizes mapped to frequencies (power scale or log scale)
- [ ] Colors assigned (neutral default + category highlights if requested)
- [ ] Font chosen (premium, not generic)
- [ ] Background: off-tone, possibly textured
- [ ] Animation: entrance by default for web targets
- [ ] Hover: tooltip + scale always on
- [ ] Responsive container
- [ ] Light + dark theme vars defined
- [ ] Accessible fallback `<ul>` present
- [ ] No console errors; tested edge case of very short texts (< 20 words)

---

## Reference Files

| File | When to read |
|------|-------------|
| `references/react.md` | Building React component (D3-cloud) |
| `references/html.md` | Building standalone HTML (wordcloud2.js) |
| `references/python.md` | Python / Streamlit output |
| `references/palettes.md` | Color scheme details & CSS vars |
| `references/shapes.md` | SVG shape paths & masking code |
| `references/nlp-keywords.md` | Bundled sentiment & verb word lists |
| `references/stopwords.md` | Stopword list to filter before counting |
