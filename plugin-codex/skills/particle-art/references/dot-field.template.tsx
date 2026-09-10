"use client";
/**
 * dot-field.template.tsx — Gaussian canvas dot cloud with sparks template.
 *
 * USAGE:
 *   1. Copy and rename (e.g. HeroDotField.tsx, CosmicField.tsx)
 *   2. Adjust DOT_COUNT, SIGMA (spread), spark parameters to taste
 *   3. Mouse moves dots away; they spring back slowly to their base positions
 *
 * THEMING: --accent-strong (inner/bright), --accent-soft (outer/dim) CSS vars
 * DEPENDENCIES: none
 */
import { useEffect, useRef } from "react";

// ── Constants ──────────────────────────────────────────────────────────────────
const DOT_COUNT = 120;      // total dot count (lower for fine dot feel)
const SIGMA = 0.28;         // Gaussian standard deviation [0–0.5]; lower = tighter cluster
const SPRING_BACK = 0.08;   // how fast dots return to base position after repulsion
const REPEL_MULT = 0.2;     // repulsion radius = size * REPEL_MULT
const SPARK_PROB = 0.008;   // probability per frame to spawn a spark
const MAX_SPARKS = 8;

// ── Helpers ────────────────────────────────────────────────────────────────────
function themeRgb(v: string): [number, number, number] {
  const ch = getComputedStyle(document.documentElement)
    .getPropertyValue(v).trim().split(/\s+/).map(Number);
  return [ch[0] ?? 100, ch[1] ?? 100, ch[2] ?? 100];
}

// Box-Muller: Gaussian sample with mean=0, std=sigma
function gaussian(sigma: number): number {
  let u = 0, v = 0;
  while (u === 0) u = Math.random();
  while (v === 0) v = Math.random();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v) * sigma;
}

interface Dot {
  bx: number; by: number;   // base position (centre of gravity)
  x: number;  y: number;   // current position
  r: number;                // radius
  distRatio: number;        // normalised distance from centre [0, 1]
}

interface Spark {
  x: number; y: number;
  vx: number; vy: number;
  life: number;             // [1, 0] — fades and shrinks as it dies
}

function buildDots(size: number): Dot[] {
  const cx = size / 2, cy = size / 2;
  const dots: Dot[] = [];
  for (let i = 0; i < DOT_COUNT; i++) {
    const bx = cx + gaussian(SIGMA) * size;
    const by = cy + gaussian(SIGMA) * size;
    const dx = (bx - cx) / (size * 0.5);
    const dy = (by - cy) / (size * 0.5);
    dots.push({
      bx, by, x: bx, y: by,
      r: Math.random() * 1.8 + 0.8,
      distRatio: Math.sqrt(dx * dx + dy * dy),
    });
  }
  return dots;
}

// ── Component ──────────────────────────────────────────────────────────────────
export function DotFieldArt({ size = 280 }: { size?: number }) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const ctx = el.getContext("2d")!;
    const dpr = window.devicePixelRatio || 1;
    el.width = size * dpr;
    el.height = size * dpr;
    ctx.scale(dpr, dpr);

    const dots = buildDots(size);
    const sparks: Spark[] = [];
    const REPEL = size * REPEL_MULT;

    // Mouse tracking
    const mouse = { x: -9999, y: -9999 };
    const onMove = (e: MouseEvent) => {
      const r = el.getBoundingClientRect();
      mouse.x = e.clientX - r.left;
      mouse.y = e.clientY - r.top;
    };
    const onLeave = () => { mouse.x = -9999; mouse.y = -9999; };
    el.addEventListener("mousemove", onMove);
    el.addEventListener("mouseleave", onLeave);

    let raf: number;

    const tick = () => {
      ctx.clearRect(0, 0, size, size);
      const [sr, sg, sb] = themeRgb("--accent-strong");
      const [lr, lg, lb] = themeRgb("--accent-soft");
      const { x: mx, y: my } = mouse;

      // ── Update dots ────────────────────────────────────────────────────
      dots.forEach(d => {
        // Repulsion
        const dx = d.x - mx, dy = d.y - my;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < REPEL && dist > 0) {
          const f = ((REPEL - dist) / REPEL) * 2.5;
          d.x += (dx / dist) * f;
          d.y += (dy / dist) * f;
        }
        // Spring back to base
        d.x += (d.bx - d.x) * SPRING_BACK;
        d.y += (d.by - d.y) * SPRING_BACK;

        // Colour blend: inner → --accent-strong, outer → --accent-soft
        const t = Math.min(1, d.distRatio * 1.6);
        const r2 = sr + (lr - sr) * t;
        const g2 = sg + (lg - sg) * t;
        const b2 = sb + (lb - sb) * t;
        const alpha = Math.max(0.12, 0.85 - d.distRatio * 0.7);

        ctx.beginPath();
        ctx.arc(d.x, d.y, d.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${Math.round(r2)},${Math.round(g2)},${Math.round(b2)},${alpha.toFixed(3)})`;
        ctx.fill();
      });

      // ── Sparks ────────────────────────────────────────────────────────
      if (Math.random() < SPARK_PROB && sparks.length < MAX_SPARKS) {
        const angle = Math.random() * Math.PI * 2;
        const spawnR = size * 0.08 + Math.random() * size * 0.15;
        sparks.push({
          x: size / 2 + Math.cos(angle) * spawnR,
          y: size / 2 + Math.sin(angle) * spawnR,
          vx: (Math.random() - 0.5) * 2.2,
          vy: (Math.random() - 0.5) * 2.2,
          life: 1,
        });
      }

      for (let i = sparks.length - 1; i >= 0; i--) {
        const s = sparks[i];
        s.x += s.vx;
        s.y += s.vy;
        s.vx *= 0.96;
        s.vy *= 0.96;
        s.life -= 0.025;
        if (s.life <= 0) { sparks.splice(i, 1); continue; }

        ctx.beginPath();
        ctx.arc(s.x, s.y, s.life * 1.8, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${sr},${sg},${sb},${(s.life * 0.9).toFixed(3)})`;
        ctx.fill();
      }

      raf = requestAnimationFrame(tick);
    };

    // Reduced-motion: draw one static frame of dots at base positions, skip the loop.
    // Never return early before drawing — that leaves the canvas blank.
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      tick();
      cancelAnimationFrame(raf);
      return;
    }

    tick();
    return () => {
      cancelAnimationFrame(raf);
      el.removeEventListener("mousemove", onMove);
      el.removeEventListener("mouseleave", onLeave);
    };
  }, [size]);

  return (
    <div style={{ position: "relative", width: size, height: size }} aria-hidden="true">
      <canvas
        ref={ref}
        style={{ width: size, height: size }}
      />
      {/* Centre ✦ as HTML so it scales with the canvas and stays crisp */}
      <span
        style={{
          position: "absolute",
          top: "50%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          fontSize: "1.4rem",
          color: "rgb(var(--accent-strong))",
          opacity: 0.72,
          pointerEvents: "none",
          userSelect: "none",
        }}
      >
        ✦
      </span>
    </div>
  );
}
