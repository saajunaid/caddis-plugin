# Plain HTML Word Cloud — Implementation Reference

Uses **wordcloud2.js** (canvas) via CDN. Zero build tooling required.

## CDN Links
```html
<script src="https://cdnjs.cloudflare.com/ajax/libs/wordcloud2.js/1.2.2/wordcloud2.min.js"></script>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;700;800&display=swap" rel="stylesheet">
```

---

## Complete Self-Contained Template

```html
<!DOCTYPE html>
<html lang="en" data-theme="auto">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Word Cloud</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;700;800&display=swap" rel="stylesheet">
<style>
/* ── CSS Variables / Themes ── */
:root {
  --cloud-bg:       #fafaf9;
  --cloud-surface:  #ffffff;
  --cloud-noun:     #1c6499;
  --cloud-positive: #16a34a;
  --cloud-negative: #dc2626;
  --cloud-verb:     #7c3aed;
  --cloud-neutral:  #a8a29e;
  --cloud-glow:     rgba(124, 58, 237, 0.15);
  --cloud-border:   rgba(0,0,0,0.06);
}
[data-theme="dark"] {
  --cloud-bg:       #0c0a09;
  --cloud-surface:  #1c1917;
  --cloud-noun:     #7dd3fc;
  --cloud-positive: #4ade80;
  --cloud-negative: #f87171;
  --cloud-verb:     #c4b5fd;
  --cloud-neutral:  #78716c;
  --cloud-glow:     rgba(167, 139, 250, 0.2);
  --cloud-border:   rgba(255,255,255,0.08);
}
@media (prefers-color-scheme: dark) {
  [data-theme="auto"] {
    --cloud-bg:       #0c0a09;
    --cloud-surface:  #1c1917;
    --cloud-noun:     #7dd3fc;
    --cloud-positive: #4ade80;
    --cloud-negative: #f87171;
    --cloud-verb:     #c4b5fd;
    --cloud-neutral:  #78716c;
    --cloud-glow:     rgba(167, 139, 250, 0.2);
    --cloud-border:   rgba(255,255,255,0.08);
  }
}

* { box-sizing: border-box; margin: 0; padding: 0; }

body {
  background: var(--cloud-bg);
  font-family: 'Syne', sans-serif;
  display: flex;
  flex-direction: column;
  align-items: center;
  min-height: 100vh;
  padding: 32px 16px;
  transition: background 0.3s;
}

.cloud-container {
  width: min(900px, 100%);
  background: var(--cloud-surface);
  border-radius: 24px;
  border: 1px solid var(--cloud-border);
  overflow: hidden;
  position: relative;
  box-shadow: 0 24px 80px var(--cloud-glow), 0 4px 16px rgba(0,0,0,0.1);
}

/* Radial glow overlay */
.cloud-container::before {
  content: '';
  position: absolute;
  inset: 0;
  background: radial-gradient(ellipse at center, var(--cloud-glow) 0%, transparent 70%);
  pointer-events: none;
  z-index: 0;
}

canvas#wordcloud {
  display: block;
  width: 100% !important;
  position: relative;
  z-index: 1;
}

/* Controls bar */
.controls {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  width: min(900px, 100%);
  margin-bottom: 16px;
}

.theme-toggle {
  background: var(--cloud-surface);
  border: 1px solid var(--cloud-border);
  border-radius: 50px;
  padding: 8px 20px;
  font-family: 'Syne', sans-serif;
  font-size: 13px;
  cursor: pointer;
  color: var(--cloud-noun);
  transition: all 0.2s;
}
.theme-toggle:hover { border-color: var(--cloud-noun); }

/* Tooltip */
#tooltip {
  position: fixed;
  background: var(--cloud-surface);
  border: 1px solid var(--cloud-noun);
  border-radius: 10px;
  padding: 8px 14px;
  font-family: 'Syne', sans-serif;
  font-size: 13px;
  pointer-events: none;
  z-index: 9999;
  display: none;
  box-shadow: 0 8px 24px rgba(0,0,0,0.15);
  transform: translate(-50%, calc(-100% - 8px));
  gap: 8px;
  align-items: center;
  color: var(--cloud-noun);
}
#tooltip.visible { display: flex; }
.tt-word { font-weight: 800; color: var(--cloud-noun); }
.tt-count { opacity: 0.5; font-size: 11px; }
.tt-cat { font-size: 10px; padding: 2px 8px; border-radius: 20px; font-weight: 700; }

/* Legend */
.legend {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  margin-top: 12px;
  font-size: 12px;
  opacity: 0.8;
}
.legend-item { display: flex; align-items: center; gap: 6px; }
.legend-dot { width: 10px; height: 10px; border-radius: 50%; }

/* Accessible fallback */
.sr-only {
  position: absolute; width: 1px; height: 1px;
  padding: 0; margin: -1px; overflow: hidden;
  clip: rect(0,0,0,0); border: 0;
}

/* Entrance animation shimmer */
@keyframes shimmerIn {
  from { opacity: 0; transform: scale(0.96); }
  to   { opacity: 1; transform: scale(1); }
}
.cloud-container { animation: shimmerIn 0.5s ease-out; }
</style>
</head>
<body>

<div class="controls">
  <h1 style="font-size:18px;font-weight:800;color:var(--cloud-noun)">Word Cloud</h1>
  <button class="theme-toggle" onclick="toggleTheme()">Toggle Theme</button>
</div>

<div class="cloud-container">
  <canvas id="wordcloud" width="900" height="520"></canvas>
</div>

<div class="legend" id="legend"></div>

<div id="tooltip">
  <span class="tt-word" id="tt-word"></span>
  <span class="tt-count" id="tt-count"></span>
  <span class="tt-cat" id="tt-cat"></span>
</div>

<!-- Accessible list -->
<ul class="sr-only" id="word-list" aria-label="Word cloud contents"></ul>

<script src="https://cdnjs.cloudflare.com/ajax/libs/wordcloud2.js/1.2.2/wordcloud2.min.js"></script>
<script>
// ─────────────────────────────────────────────
// 1. PASTE YOUR WORDS HERE (or generate dynamically)
// Format: [word, frequency, category?]
// category: 'positive' | 'negative' | 'verb' | 'noun' | 'neutral'
// ─────────────────────────────────────────────
const WORD_DATA = [
  // REPLACE THIS with computed frequencies from text extraction
  ['innovation', 42, 'noun'],
  ['growth', 38, 'positive'],
  ['challenge', 31, 'negative'],
  ['strategy', 29, 'noun'],
  ['transform', 27, 'verb'],
  ['success', 25, 'positive'],
  ['risk', 22, 'negative'],
  ['develop', 20, 'verb'],
  ['impact', 19, 'noun'],
  ['optimize', 17, 'verb'],
  // ... add more
];

// ─────────────────────────────────────────────
// 2. COLOR MAPPING
// ─────────────────────────────────────────────
function getCSSVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function getColor(category) {
  const map = {
    positive: '--cloud-positive',
    negative: '--cloud-negative',
    verb:     '--cloud-verb',
    noun:     '--cloud-noun',
    neutral:  '--cloud-neutral',
  };
  return getCSSVar(map[category] || '--cloud-noun');
}

// Store word metadata for tooltip
const wordMeta = {};
WORD_DATA.forEach(([w, count, cat]) => {
  wordMeta[w.toLowerCase()] = { count, category: cat || 'neutral' };
});

// ─────────────────────────────────────────────
// 3. RENDER
// ─────────────────────────────────────────────
function renderCloud() {
  const canvas = document.getElementById('wordcloud');
  const w = canvas.parentElement.clientWidth;
  canvas.width = w;
  canvas.height = Math.round(w * 0.58);

  const maxVal = Math.max(...WORD_DATA.map(d => d[1]));
  const minVal = Math.min(...WORD_DATA.map(d => d[1]));
  const sizeRange = [14, Math.min(canvas.width, canvas.height) / 4.5];

  function sizeScale(v) {
    const t = Math.pow((v - minVal) / (maxVal - minVal + 1), 0.55);
    return sizeRange[0] + t * (sizeRange[1] - sizeRange[0]);
  }

  WordCloud(canvas, {
    list: WORD_DATA.map(([w, v, cat]) => [w, sizeScale(v)]),
    gridSize: Math.round(16 * canvas.width / 1024),
    weightFactor: 1,
    fontFamily: 'Syne, sans-serif',
    color: (word) => {
      const meta = wordMeta[word.toLowerCase()];
      return getColor(meta?.category || 'neutral');
    },
    rotateRatio: 0.2,
    rotationSteps: 3,
    backgroundColor: 'transparent',
    drawOutOfBound: false,
    shrinkToFit: true,
    minSize: 10,
    hover: handleHover,
    click: handleClick,
  });
}

// ─────────────────────────────────────────────
// 4. INTERACTIONS
// ─────────────────────────────────────────────
const tooltip = document.getElementById('tooltip');

function handleHover(item, dimension, event) {
  if (!item) { tooltip.classList.remove('visible'); return; }
  const [word] = item;
  const meta = wordMeta[word.toLowerCase()] || {};
  document.getElementById('tt-word').textContent = word;
  document.getElementById('tt-count').textContent = meta.count ? `${meta.count}×` : '';
  const catEl = document.getElementById('tt-cat');
  catEl.textContent = meta.category || '';
  catEl.style.background = getColor(meta.category || 'neutral');
  catEl.style.color = '#fff';
  tooltip.style.left = event.clientX + 'px';
  tooltip.style.top  = event.clientY + 'px';
  tooltip.classList.add('visible');
}

function handleClick(item) {
  if (item) console.log('Word clicked:', item[0]);
}

document.addEventListener('mousemove', (e) => {
  if (tooltip.classList.contains('visible')) {
    tooltip.style.left = e.clientX + 'px';
    tooltip.style.top  = e.clientY + 'px';
  }
});

// ─────────────────────────────────────────────
// 5. THEME TOGGLE
// ─────────────────────────────────────────────
function toggleTheme() {
  const html = document.documentElement;
  const current = html.getAttribute('data-theme');
  html.setAttribute('data-theme', current === 'dark' ? 'light' : 'dark');
  setTimeout(renderCloud, 50); // re-render with new colors
}

// ─────────────────────────────────────────────
// 6. LEGEND
// ─────────────────────────────────────────────
function buildLegend() {
  const cats = [
    ['positive', 'Positive'],
    ['negative', 'Negative'],
    ['verb', 'Verbs'],
    ['noun', 'Nouns'],
    ['neutral', 'Neutral'],
  ];
  const legend = document.getElementById('legend');
  legend.innerHTML = cats.map(([cat, label]) => `
    <span class="legend-item">
      <span class="legend-dot" style="background:${getColor(cat)}"></span>
      ${label}
    </span>
  `).join('');
}

// ─────────────────────────────────────────────
// 7. ACCESSIBLE LIST
// ─────────────────────────────────────────────
function buildA11yList() {
  const list = document.getElementById('word-list');
  list.innerHTML = WORD_DATA.map(([w, v]) => `<li>${w} (${v})</li>`).join('');
}

// ─────────────────────────────────────────────
// 8. INIT
// ─────────────────────────────────────────────
window.addEventListener('load', () => {
  renderCloud();
  buildLegend();
  buildA11yList();
});

window.addEventListener('resize', () => {
  clearTimeout(window._resizeTimer);
  window._resizeTimer = setTimeout(renderCloud, 200);
});
</script>
</body>
</html>
```

---

## Injecting Words Dynamically (from fetch/API)

Replace the static `WORD_DATA` section with:

```js
async function loadWords() {
  const res = await fetch('/api/word-frequencies'); // your endpoint
  const data = await res.json();
  // data format: [{word, count, category}]
  window.WORD_DATA = data.map(d => [d.word, d.count, d.category]);
  renderCloud();
  buildLegend();
  buildA11yList();
}
window.addEventListener('load', loadWords);
```
