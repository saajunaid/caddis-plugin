# React Word Cloud — Implementation Reference

## Dependencies

```bash
npm install d3-cloud d3 compromise sentiment
# or with yarn:
yarn add d3-cloud d3 compromise sentiment
```

For font loading (optional but recommended):
```html
<!-- In index.html or _document.tsx -->
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;700;800&family=DM+Serif+Display&display=swap" rel="stylesheet">
```

---

## Core Component: `WordCloud.tsx`

```tsx
'use client'; // Next.js: client-only
import React, { useEffect, useRef, useState, useCallback } from 'react';
import cloud from 'd3-cloud';
import * as d3 from 'd3';

interface WordData {
  text: string;
  value: number;           // raw frequency
  category?: 'positive' | 'negative' | 'verb' | 'noun' | 'neutral';
  size?: number;           // computed by d3-cloud
  x?: number;
  y?: number;
  rotate?: number;
}

interface WordCloudProps {
  words: WordData[];
  width?: number;
  height?: number;
  fontFamily?: string;
  theme?: 'light' | 'dark' | 'auto';
  palette?: string;
  animation?: 'none' | 'entrance' | 'float' | 'cinematic';
  shape?: 'circle' | 'star' | 'speech_bubble' | 'none';
  maxWords?: number;
  onWordClick?: (word: WordData) => void;
}

const CATEGORY_COLORS: Record<string, string> = {
  positive: 'var(--cloud-positive)',
  negative: 'var(--cloud-negative)',
  verb:     'var(--cloud-verb)',
  noun:     'var(--cloud-noun)',
  neutral:  'var(--cloud-neutral)',
};

export const WordCloud: React.FC<WordCloudProps> = ({
  words,
  width = 800,
  height = 500,
  fontFamily = 'Syne, sans-serif',
  theme = 'auto',
  palette = 'obsidian',
  animation = 'entrance',
  maxWords = 100,
  onWordClick,
}) => {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [layoutWords, setLayoutWords] = useState<WordData[]>([]);
  const [tooltip, setTooltip] = useState<{ word: WordData; x: number; y: number } | null>(null);
  const [dims, setDims] = useState({ width, height });

  // Responsive resize
  useEffect(() => {
    if (!containerRef.current) return;
    const ro = new ResizeObserver(([entry]) => {
      const w = entry.contentRect.width;
      setDims({ width: w, height: Math.round(w * (height / width)) });
    });
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, [width, height]);

  // D3-cloud layout
  useEffect(() => {
    const top = words
      .sort((a, b) => b.value - a.value)
      .slice(0, maxWords);

    const maxVal = Math.max(...top.map(w => w.value));
    const minVal = Math.min(...top.map(w => w.value));
    const sizeScale = d3.scalePow()
      .exponent(0.6)
      .domain([minVal, maxVal])
      .range([12, Math.min(dims.width, dims.height) / 5]);

    cloud<WordData>()
      .size([dims.width, dims.height])
      .words(top.map(w => ({ ...w, size: sizeScale(w.value) })))
      .padding(5)
      .rotate(() => {
        const r = Math.random();
        if (r < 0.6) return 0;
        if (r < 0.8) return 90;
        return Math.round((Math.random() - 0.5) * 30);
      })
      .font(fontFamily)
      .fontSize(d => d.size ?? 12)
      .on('end', (computed) => setLayoutWords(computed as WordData[]))
      .start();
  }, [words, dims, fontFamily, maxWords]);

  const getColor = (w: WordData) =>
    w.category ? CATEGORY_COLORS[w.category] : 'var(--cloud-noun)';

  const getAnimStyle = (i: number): React.CSSProperties => {
    if (animation === 'none') return {};
    if (animation === 'entrance' || animation === 'cinematic') {
      return {
        animation: `wordEntrance 0.6s ease-out both`,
        animationDelay: `${i * 30}ms`,
        '--r': `${layoutWords[i]?.rotate ?? 0}deg`,
      } as React.CSSProperties;
    }
    if (animation === 'float') {
      return {
        animation: `wordFloat ${3 + (i % 5) * 0.4}s ease-in-out infinite`,
        animationDelay: `${(i * 137) % 2000}ms`,
        '--r': `${layoutWords[i]?.rotate ?? 0}deg`,
      } as React.CSSProperties;
    }
    return {};
  };

  return (
    <div
      ref={containerRef}
      data-theme={theme}
      className={`word-cloud-wrapper ${palette}`}
      style={{ width: '100%', position: 'relative' }}
    >
      <style>{CLOUD_STYLES}</style>

      {/* Accessible fallback */}
      <ul className="sr-only" aria-label="Word cloud words">
        {layoutWords.map(w => (
          <li key={w.text}>{w.text} ({w.value})</li>
        ))}
      </ul>

      <svg
        ref={svgRef}
        viewBox={`0 0 ${dims.width} ${dims.height}`}
        aria-label="Word cloud visualization"
        role="img"
        style={{ width: '100%', height: 'auto', display: 'block' }}
      >
        {/* Background */}
        <rect width={dims.width} height={dims.height} fill="var(--cloud-bg)" rx={16} />
        <radialGradient id="bgGlow" cx="50%" cy="50%" r="60%">
          <stop offset="0%" stopColor="var(--cloud-glow)" stopOpacity="0.15" />
          <stop offset="100%" stopColor="transparent" stopOpacity="0" />
        </radialGradient>
        <rect width={dims.width} height={dims.height} fill="url(#bgGlow)" rx={16} />

        <g transform={`translate(${dims.width / 2},${dims.height / 2})`}>
          {layoutWords.map((w, i) => (
            <text
              key={w.text}
              className="cloud-word"
              style={{
                ...getAnimStyle(i),
                fontSize: w.size,
                fontFamily,
                fontWeight: (w.size ?? 12) > 40 ? 800 : (w.size ?? 12) > 24 ? 700 : 400,
                fill: getColor(w),
                cursor: 'pointer',
                userSelect: 'none',
              }}
              textAnchor="middle"
              transform={`translate(${w.x},${w.y}) rotate(${w.rotate})`}
              onClick={() => onWordClick?.(w)}
              onMouseEnter={(e) => {
                const rect = (e.target as SVGTextElement).getBoundingClientRect();
                setTooltip({ word: w, x: rect.left + rect.width / 2, y: rect.top - 8 });
              }}
              onMouseLeave={() => setTooltip(null)}
            >
              {w.text}
            </text>
          ))}
        </g>
      </svg>

      {/* Tooltip */}
      {tooltip && (
        <div
          className="cloud-tooltip"
          style={{ left: tooltip.x, top: tooltip.y }}
        >
          <span className="tooltip-word">{tooltip.word.text}</span>
          <span className="tooltip-count">{tooltip.word.value}×</span>
          {tooltip.word.category && (
            <span className={`tooltip-cat ${tooltip.word.category}`}>
              {tooltip.word.category}
            </span>
          )}
        </div>
      )}
    </div>
  );
};
```

---

## CSS (inject as string or in your .css file)

```css
const CLOUD_STYLES = `
  /* ── Themes ── */
  .word-cloud-wrapper {
    --cloud-bg:       #fafaf9;
    --cloud-noun:     #1c6499;
    --cloud-positive: #16a34a;
    --cloud-negative: #dc2626;
    --cloud-verb:     #7c3aed;
    --cloud-neutral:  #a8a29e;
    --cloud-glow:     #7c3aed;
  }
  .word-cloud-wrapper[data-theme="dark"],
  .dark .word-cloud-wrapper {
    --cloud-bg:       #0c0a09;
    --cloud-noun:     #7dd3fc;
    --cloud-positive: #4ade80;
    --cloud-negative: #f87171;
    --cloud-verb:     #c4b5fd;
    --cloud-neutral:  #78716c;
    --cloud-glow:     #a78bfa;
  }
  @media (prefers-color-scheme: dark) {
    .word-cloud-wrapper[data-theme="auto"] {
      --cloud-bg:       #0c0a09;
      --cloud-noun:     #7dd3fc;
      --cloud-positive: #4ade80;
      --cloud-negative: #f87171;
      --cloud-verb:     #c4b5fd;
      --cloud-neutral:  #78716c;
      --cloud-glow:     #a78bfa;
    }
  }

  /* ── Palette overrides ── */
  .word-cloud-wrapper.aurora {
    --cloud-bg: #050510;
    --cloud-noun: #38bdf8;
    --cloud-verb: #e879f9;
    --cloud-positive: #34d399;
    --cloud-negative: #fb923c;
    --cloud-glow: #818cf8;
  }
  .word-cloud-wrapper.parchment {
    --cloud-bg: #f5f0e8;
    --cloud-noun: #92400e;
    --cloud-verb: #9a3412;
    --cloud-positive: #365314;
    --cloud-negative: #7f1d1d;
    --cloud-glow: #b45309;
  }

  /* ── Word interactions ── */
  .cloud-word {
    transition: opacity 0.2s, filter 0.2s, transform 0.2s;
  }
  .cloud-word:hover {
    filter: brightness(1.3) drop-shadow(0 0 8px currentColor);
    transform-origin: center;
  }

  /* ── Animations ── */
  @keyframes wordEntrance {
    from { opacity: 0; transform: scale(0.3) rotate(var(--r, 0deg)); }
    to   { opacity: 1; transform: scale(1)   rotate(var(--r, 0deg)); }
  }
  @keyframes wordFloat {
    0%, 100% { transform: translateY(0)    rotate(var(--r, 0deg)); }
    50%       { transform: translateY(-5px) rotate(var(--r, 0deg)); }
  }

  /* ── Tooltip ── */
  .cloud-tooltip {
    position: fixed;
    transform: translate(-50%, -100%);
    background: var(--cloud-bg);
    border: 1px solid var(--cloud-noun);
    border-radius: 8px;
    padding: 6px 12px;
    font-family: inherit;
    font-size: 13px;
    display: flex;
    gap: 8px;
    align-items: center;
    pointer-events: none;
    z-index: 1000;
    box-shadow: 0 8px 24px rgba(0,0,0,0.2);
  }
  .tooltip-word { font-weight: 700; }
  .tooltip-count { opacity: 0.6; }
  .tooltip-cat { font-size: 11px; padding: 2px 6px; border-radius: 4px; background: var(--cloud-noun); color: #fff; }
  .tooltip-cat.positive { background: var(--cloud-positive); }
  .tooltip-cat.negative { background: var(--cloud-negative); }
  .tooltip-cat.verb     { background: var(--cloud-verb); }

  /* ── Accessibility ── */
  .sr-only {
    position: absolute; width: 1px; height: 1px;
    padding: 0; margin: -1px; overflow: hidden;
    clip: rect(0,0,0,0); border: 0;
  }
`;
```

---

## Word Frequency Utility

```ts
// utils/wordFrequency.ts
const DEFAULT_STOPWORDS = new Set([
  'the','a','an','and','or','but','in','on','at','to','for','of','with',
  'is','are','was','were','be','been','have','has','had','do','does','did',
  'will','would','could','should','may','might','shall','this','that','these',
  'those','it','its','i','we','you','he','she','they','my','your','our',
  'their','what','which','who','when','where','how','all','each','both',
  'more','also','just','not','no','so','if','as','by','from','up','about',
  'into','through','then','than','very','even','any','one','two','three',
]);

export function computeFrequencies(
  text: string,
  customStopwords: string[] = [],
  minLength = 3
): Array<{ text: string; value: number }> {
  const stops = new Set([...DEFAULT_STOPWORDS, ...customStopwords.map(w => w.toLowerCase())]);
  const counts: Record<string, number> = {};

  text
    .toLowerCase()
    .replace(/[^a-z\s'-]/g, ' ')
    .split(/\s+/)
    .filter(w => w.length >= minLength && !stops.has(w) && !/^\d+$/.test(w))
    .forEach(w => { counts[w] = (counts[w] ?? 0) + 1; });

  return Object.entries(counts)
    .map(([text, value]) => ({ text, value }))
    .sort((a, b) => b.value - a.value);
}
```

---

## Shape Masking (D3-cloud)

For non-rectangular shapes, provide a pixel mask:

```ts
function buildCircleMask(width: number, height: number): boolean[][] {
  const cx = width / 2, cy = height / 2;
  const r = Math.min(cx, cy) * 0.92;
  return Array.from({ length: height }, (_, y) =>
    Array.from({ length: width }, (_, x) =>
      (x - cx) ** 2 + (y - cy) ** 2 <= r ** 2
    )
  );
}

// Pass to d3-cloud via custom spiral:
// d3-cloud doesn't natively support pixel masks but you can approximate
// by using a bounded region and clipping with SVG clipPath:
```

```tsx
// SVG ClipPath approach (simpler, works great):
<defs>
  <clipPath id="cloudShape">
    <circle cx={dims.width/2} cy={dims.height/2} r={Math.min(dims.width, dims.height)/2 - 10} />
    {/* or use <path d={STAR_PATH} /> from references/shapes.md */}
  </clipPath>
</defs>
<g clipPath="url(#cloudShape)" transform={`translate(${dims.width/2},${dims.height/2})`}>
  {/* words */}
</g>
```

---

## Full Usage Example

```tsx
import { WordCloud } from './WordCloud';
import { computeFrequencies } from './utils/wordFrequency';
import { applySentiment } from './utils/nlp'; // optional

const text = `...extracted text from PDF/DOCX/XLSX...`;
const freqs = computeFrequencies(text);
const words = applySentiment(freqs); // adds .category field

export default function MyPage() {
  return (
    <div style={{ padding: 32, background: 'var(--cloud-bg)' }}>
      <WordCloud
        words={words}
        width={900}
        height={550}
        theme="auto"
        palette="obsidian"
        animation="cinematic"
        fontFamily="Syne, sans-serif"
        maxWords={120}
        onWordClick={w => console.log('clicked', w)}
      />
    </div>
  );
}
```
