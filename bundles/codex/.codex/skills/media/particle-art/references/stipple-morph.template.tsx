"use client";
/**
 * stipple-morph.template.tsx — Halftone dot cloud that morphs into a letter/shape on hover.
 *
 * USAGE:
 *   1. Copy and rename (e.g. StippleMorph.tsx, HeroHalftone.tsx)
 *   2. Pass `text` prop to set the target letter/word (default "j")
 *   3. Adjust COLS × ROWS for dot density
 *   4. The morph is driven by React synthetic onMouseMove/onMouseLeave — no addEventListener needed
 *
 * RENDERING: HTML spans (SSR-safe). Grid A built at module level; Grid B from canvas in useEffect.
 * INTERACTION: hover canvas → cloud resolves into letter; leave → drifts back
 * THEMING: --accent-strong CSS var for dot colour
 */
import { useEffect, useRef } from "react";

const COLS = 24;
const ROWS = 18;
const SCAN_PERIOD = 480;
const MORPH_SPEED = 0.045; // lerp speed; higher = snappier

function srand(x: number, y: number): number {
  return (Math.abs(Math.sin(x * 127.1 + y * 311.7) * 43758.5453)) % 1;
}

function charFor(v: number): string {
  if (v > 0.68) return "●";
  if (v > 0.35) return "•";
  return "·";
}

// ── Grid A: Gaussian cloud — module-level, SSR-safe ───────────────────────────
const GRID_A: number[][] = Array.from({ length: ROWS }, (_, yi) =>
  Array.from({ length: COLS }, (_, xi) => {
    const nx = (xi / (COLS - 1)) * 2 - 1;
    const ny = (yi / (ROWS - 1)) * 2 - 1;
    const dist = Math.sqrt(nx * nx + ny * ny);
    const base = Math.exp(-(dist * dist) / (2 * 0.28 * 0.28));
    return Math.max(0, Math.min(1, base + srand(xi * 53, yi * 97) * 0.12 - 0.06));
  })
);

// Per-cell breathing params
const B_PHASE = Array.from({ length: ROWS }, (_, yi) =>
  Array.from({ length: COLS }, (_, xi) => srand(xi * 71, yi * 113) * Math.PI * 2)
);
const B_SPEED = Array.from({ length: ROWS }, (_, yi) =>
  Array.from({ length: COLS }, (_, xi) => 0.008 + srand(xi, yi) * 0.006)
);
const B_AMP = Array.from({ length: ROWS }, (_, yi) =>
  Array.from({ length: COLS }, (_, xi) => 0.04 + srand(xi + 50, yi) * 0.10)
);

// ── Grid B: sample canvas text → density map ──────────────────────────────────
//
// REPLACE `text` param or call with any string. Single chars work best.
// For multi-char (e.g. "JS"), reduce font size:
//   const fontSize = Math.floor(Math.min(ROWS*S*0.8, COLS*S*0.35));
//
function buildLetterGrid(text: string): number[][] {
  const S = 8;
  const oc = document.createElement("canvas");
  oc.width  = COLS * S;
  oc.height = ROWS * S;
  const ctx = oc.getContext("2d")!;
  const fontSize = Math.floor(Math.min(ROWS * S * 0.88, COLS * S * 0.55));
  ctx.fillStyle = "#fff";
  ctx.font = `bold ${fontSize}px sans-serif`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(text, (COLS * S) / 2, (ROWS * S) / 2);
  const { data } = ctx.getImageData(0, 0, COLS * S, ROWS * S);
  return Array.from({ length: ROWS }, (_, yi) =>
    Array.from({ length: COLS }, (_, xi) => {
      let sum = 0;
      for (let dy = 0; dy < S; dy++)
        for (let dx = 0; dx < S; dx++)
          sum += data[((yi * S + dy) * COLS * S + (xi * S + dx)) * 4] / 255;
      return Math.min(1, (sum / (S * S)) * 2.2);
    })
  );
}

// ── Component ──────────────────────────────────────────────────────────────────
export function StippleMorphArt({ text = "j", className = "" }: { text?: string; className?: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  // Refs for cross-closure state — never stale in the RAF loop
  const active = useRef(false);
  const morphRef = useRef(0);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const GRID_B = buildLetterGrid(text);
    const spans  = Array.from(container.querySelectorAll<HTMLElement>("span[data-xi]"));

    let raf: number;
    let frame = 0;

    const tick = () => {
      // Lerp morphStrength toward 0 (idle) or 1 (letter)
      const m = morphRef.current + ((active.current ? 1 : 0) - morphRef.current) * MORPH_SPEED;
      morphRef.current = m;

      const cx = COLS / 2, cy = ROWS / 2;
      const maxR = Math.sqrt(cx * cx + cy * cy);
      const waveR = ((frame % SCAN_PERIOD) / SCAN_PERIOD) * (maxR + 1);

      spans.forEach(el => {
        const xi = +el.dataset.xi!;
        const yi = +el.dataset.yi!;
        const vA = GRID_A[yi][xi];
        const vB = GRID_B[yi][xi];

        const breathe = Math.sin(frame * B_SPEED[yi][xi] + B_PHASE[yi][xi]) * B_AMP[yi][xi] * (1 - m * 0.85);

        const dist = Math.sqrt((xi - cx) ** 2 + (yi - cy) ** 2);
        const diff = dist - waveR;
        const wave = (Math.abs(diff) < 1.6 ? 0.38 : diff < 0 && diff > -3.5 ? 0.11 : 0) * (1 - m);

        const v = Math.max(0, Math.min(1, vA * (1 - m) + vB * m + breathe + wave));
        el.style.opacity = v.toFixed(3);
        const c = charFor(v);
        if (el.textContent !== c) el.textContent = c;
      });

      frame++;
      raf = requestAnimationFrame(tick);
    };
    tick();
    return () => cancelAnimationFrame(raf);
  }, [text]);

  return (
    // React synthetic events on the container — reliable across all React modes
    <div
      ref={containerRef}
      className={className}
      style={{ userSelect: "none", lineHeight: 1.15, cursor: "crosshair" }}
      onMouseMove={() => { active.current = true; }}
      onMouseLeave={() => { active.current = false; }}
      aria-hidden="true"
    >
      <div style={{ textAlign: "center", fontSize: "1.1rem", marginBottom: "0.3em", color: "rgb(var(--accent-strong))", opacity: 0.82 }}>
        ✦
      </div>
      {Array.from({ length: ROWS }, (_, yi) => (
        <div key={yi} style={{ display: "flex", justifyContent: "center", gap: "0.18em" }}>
          {Array.from({ length: COLS }, (_, xi) => {
            const v = GRID_A[yi][xi];
            return (
              <span
                key={xi}
                data-xi={xi}
                data-yi={yi}
                style={{ fontSize: "0.68rem", color: "rgb(var(--accent-strong))", opacity: v, transition: "none" }}
              >
                {charFor(v)}
              </span>
            );
          })}
        </div>
      ))}
    </div>
  );
}
