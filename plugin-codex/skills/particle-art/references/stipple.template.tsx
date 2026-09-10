"use client";
/**
 * stipple.template.tsx — Animated Unicode halftone dot component template.
 *
 * USAGE:
 *   1. Copy and rename (e.g. StipplePortrait.tsx, HeroStipple.tsx)
 *   2. Adjust COLS × ROWS to control dot density
 *   3. Replace the GRID density function with your own if desired
 *   4. The scan wave and breathing animation work automatically
 *
 * RENDERING: Pure HTML/CSS spans — no canvas. Works with SSR.
 * THEMING: Uses --accent-strong and --accent-soft CSS vars.
 *
 * DEPENDENCIES: none
 */
import { useEffect, useRef } from "react";

// ── Grid parameters ────────────────────────────────────────────────────────────
const COLS = 24;           // horizontal dot count
const ROWS = 18;           // vertical dot count
const SCAN_PERIOD = 480;   // frames per scan wave cycle

// ── Dot character selection ────────────────────────────────────────────────────
function charFor(v: number): string {
  if (v > 0.68) return "●";
  if (v > 0.35) return "•";
  return "·";
}

// ── Deterministic pseudo-random (SSR-safe, no hydration mismatch) ──────────────
function srand(x: number, y: number): number {
  return (Math.abs(Math.sin(x * 127.1 + y * 311.7) * 43758.5453)) % 1;
}

// ── Pre-compute density grid at module level (stable across re-renders) ────────
//
// REPLACE THIS with your own density function.
// Current: Gaussian falloff from centre — denser at middle, dispersing at edges.
//
// `v` is in [0, 1]: 1 = densest (●), 0 = emptiest (·)
//
const GRID: number[][] = Array.from({ length: ROWS }, (_, yi) =>
  Array.from({ length: COLS }, (_, xi) => {
    // Normalised distance from centre [0, 1]
    const nx = (xi / (COLS - 1)) * 2 - 1;
    const ny = (yi / (ROWS - 1)) * 2 - 1;
    const dist = Math.sqrt(nx * nx + ny * ny);

    // Gaussian envelope
    const base = Math.exp(-(dist * dist) / (2 * 0.28 * 0.28));

    // Jitter so dots don't look perfectly smooth
    const jitter = srand(xi * 53, yi * 97) * 0.12 - 0.06;

    return Math.max(0, Math.min(1, base + jitter));
  })
);

// ── Animation state per dot ────────────────────────────────────────────────────
interface DotAnim {
  el: HTMLElement;
  v: number;           // density value [0, 1]
  x: number;           // column index
  y: number;           // row index
  phase: number;       // breathing phase offset
  speed: number;       // breathing speed
  amp: number;         // breathing amplitude
}

// ── Component ──────────────────────────────────────────────────────────────────
//
// Renders COLS×ROWS dots as animated spans.
// The scan wave sweeps outward from centre periodically.
// Each dot breathes (opacity oscillation) independently.
//
export function StippleArt({ className = "" }: { className?: string }) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // Reduced-motion: render static dots, skip animation
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    // Collect all dot spans with their attributes
    const spans = container.querySelectorAll<HTMLElement>("span[data-v]");
    const MAX_DOT_R = Math.sqrt(COLS * COLS + ROWS * ROWS) / 2;

    const dots: DotAnim[] = Array.from(spans).map(el => ({
      el,
      v: parseFloat(el.dataset.v ?? "0"),
      x: parseFloat(el.dataset.x ?? "0"),
      y: parseFloat(el.dataset.y ?? "0"),
      phase: srand(parseFloat(el.dataset.x ?? "0") * 71, parseFloat(el.dataset.y ?? "0") * 113) * Math.PI * 2,
      speed: 0.008 + srand(parseFloat(el.dataset.x ?? "0"), parseFloat(el.dataset.y ?? "0")) * 0.006,
      amp: 0.04 + srand(parseFloat(el.dataset.x ?? "0") + 50, parseFloat(el.dataset.y ?? "0")) * 0.10,
    }));

    let raf: number;
    let frame = 0;
    const cx = COLS / 2, cy = ROWS / 2;

    const tick = () => {
      const waveR = ((frame % SCAN_PERIOD) / SCAN_PERIOD) * (MAX_DOT_R + 1);

      dots.forEach(d => {
        const dist = Math.sqrt((d.x - cx) ** 2 + (d.y - cy) ** 2);
        const diff = dist - waveR;

        // Scan wave ring boost
        const ringBoost = Math.abs(diff) < 1.6 ? 0.40 : 0;
        // Trailing glow behind the wave
        const trailBoost = diff < 0 && diff > -3.5 ? 0.12 : 0;
        // Per-dot breathing
        const breathe = Math.sin(frame * d.speed + d.phase) * d.amp;

        const opacity = Math.max(0, Math.min(1, d.v + breathe + ringBoost + trailBoost));
        d.el.style.opacity = opacity.toFixed(3);
      });

      frame++;
      raf = requestAnimationFrame(tick);
    };
    tick();
    return () => cancelAnimationFrame(raf);
  }, []);

  return (
    <div
      ref={containerRef}
      className={className}
      style={{ userSelect: "none", lineHeight: 1.15 }}
      aria-hidden="true"
    >
      {/* ✦ glyph above the dot grid */}
      <div
        style={{
          textAlign: "center",
          fontSize: "1.1rem",
          letterSpacing: "0.05em",
          marginBottom: "0.3em",
          color: "rgb(var(--accent-strong))",
          opacity: 0.82,
        }}
      >
        ✦
      </div>

      {/* Dot grid */}
      {GRID.map((row, yi) => (
        <div key={yi} style={{ display: "flex", justifyContent: "center", gap: "0.18em" }}>
          {row.map((v, xi) => (
            <span
              key={xi}
              data-v={v.toFixed(4)}
              data-x={xi}
              data-y={yi}
              style={{
                fontSize: "0.68rem",
                color: v > 0.55
                  ? "rgb(var(--accent-strong))"
                  : "rgb(var(--accent-soft))",
                opacity: v,
                transition: "none",
              }}
            >
              {charFor(v)}
            </span>
          ))}
        </div>
      ))}
    </div>
  );
}
