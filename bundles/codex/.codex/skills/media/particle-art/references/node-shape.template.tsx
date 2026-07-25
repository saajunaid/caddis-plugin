"use client";
/**
 * node-shape.template.tsx — Spring-constrained particle component template.
 *
 * USAGE:
 *   1. Copy this file and rename it (e.g. JSpringArt.tsx, ConstellationArt.tsx)
 *   2. Replace the `buildTargets()` body with your shape points (use shape-sampler.ts)
 *   3. Tune the physics constants for your use-case (see SKILL.md physics table)
 *   4. Export and import into your page
 *
 * DEPENDENCIES: none (copy themeRgb from canvas-utils.ts if needed)
 */
import { useEffect, useRef } from "react";

// ── Physics constants — tune these per SKILL.md table ─────────────────────────
const LINK = 72;            // max distance between connected nodes (px)
const MAX_SPEED = 1.4;      // velocity cap
const FRICTION = 0.88;      // damping for letter/shape nodes
const AMBIENT_FRICTION = 0.985; // damping for free-floating ambient nodes
const REPEL_R = 85;         // mouse repulsion radius (px)
const REPEL_F = 0.5;        // repulsion force strength
const DRIFT = 0.06;         // random jitter per frame on shape nodes

// ── Target point type ──────────────────────────────────────────────────────────
interface Target {
  tx: number;       // x target (CSS px)
  ty: number;       // y target
  spring: number;   // spring constant — how strongly node returns to target
  r: number;        // visual radius
  alpha: number;    // visual opacity
  isDot?: boolean;  // special node with pulsing ring (e.g. tittle of "j")
}

// ── REPLACE THIS with your shape ──────────────────────────────────────────────
// Options:
//   - Call sampleText("J", size) from shape-sampler.ts
//   - Call sampleConstellation(size) or any other preset
//   - Define points manually (bezier, grids, SVG)
//
// The function receives the canvas size in CSS pixels and returns targets.
function buildTargets(size: number): Target[] {
  const cx = size * 0.5;
  const cy = size * 0.5;
  const targets: Target[] = [];

  // Example: a simple cross / plus pattern
  const ARM = 5;
  for (let i = -ARM; i <= ARM; i++) {
    const step = size * 0.06;
    // Horizontal arm
    targets.push({ tx: cx + i * step, ty: cy, spring: 0.036, r: 2.2, alpha: 0.9 });
    // Vertical arm (avoid duplicate centre)
    if (i !== 0) {
      targets.push({ tx: cx, ty: cy + i * step, spring: 0.036, r: 2.2, alpha: 0.9 });
    }
  }
  // Centre node — marked as dot for pulse ring
  targets.push({ tx: cx, ty: cy, spring: 0.038, r: 4.5, alpha: 1.0, isDot: true });

  return targets;
}

// ── Particle ───────────────────────────────────────────────────────────────────
interface Pt {
  x: number; y: number;
  vx: number; vy: number;
  tx: number; ty: number;
  spring: number;
  r: number;
  alpha: number;
  isDot: boolean;
  isShape: boolean;   // true = letter/shape node; false = ambient
}

// CSS-variable colour reader — keeps theme changes instant
function themeRgb(v: string): [number, number, number] {
  const ch = getComputedStyle(document.documentElement)
    .getPropertyValue(v).trim().split(/\s+/).map(Number);
  return [ch[0] ?? 100, ch[1] ?? 100, ch[2] ?? 100];
}

// ── Component ──────────────────────────────────────────────────────────────────
//
// Props: size (px), ambientCount (free-floating halo nodes)
//
export function NodeShapeArt({
  size = 300,
  ambientCount = 14,
}: {
  size?: number;
  ambientCount?: number;
}) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    // DPR-correct canvas
    const ctx = el.getContext("2d")!;
    const dpr = window.devicePixelRatio || 1;
    el.width = size * dpr;
    el.height = size * dpr;
    ctx.scale(dpr, dpr);

    // ── Build shape nodes ──────────────────────────────────────────────────
    const shapeTargets = buildTargets(size);
    const pts: Pt[] = shapeTargets.map(t => ({
      x: t.tx + (Math.random() - 0.5) * 20,
      y: t.ty + (Math.random() - 0.5) * 20,
      vx: 0, vy: 0,
      tx: t.tx, ty: t.ty,
      spring: t.spring,
      r: t.r,
      alpha: t.alpha,
      isDot: t.isDot ?? false,
      isShape: true,
    }));

    // ── Add ambient halo nodes ─────────────────────────────────────────────
    const cx = size * 0.5, cy = size * 0.48;
    for (let i = 0; i < ambientCount; i++) {
      const angle = (i / ambientCount) * Math.PI * 2;
      const spread = size * (0.28 + Math.random() * 0.17);
      const ax = cx + Math.cos(angle) * spread * 0.75;
      const ay = cy + Math.sin(angle) * spread;
      pts.push({
        x: ax, y: ay,
        vx: (Math.random() - 0.5) * 0.3,
        vy: (Math.random() - 0.5) * 0.3,
        tx: ax, ty: ay,
        spring: 0,
        r: Math.random() * 1.2 + 0.6,
        alpha: 0.35 + Math.random() * 0.3,
        isDot: false,
        isShape: false,
      });
    }

    // ── Mouse tracking ─────────────────────────────────────────────────────
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
    let frame = 0;

    const tick = () => {
      ctx.clearRect(0, 0, size, size);
      const [nr, ng, nb] = themeRgb("--accent-strong");
      const [lr, lg, lb] = themeRgb("--accent-soft");
      const { x: mx, y: my } = mouse;

      // ── Connection lines ───────────────────────────────────────────────
      for (let i = 0; i < pts.length; i++) {
        for (let j = i + 1; j < pts.length; j++) {
          const dx = pts[i].x - pts[j].x;
          const dy = pts[i].y - pts[j].y;
          const d = Math.sqrt(dx * dx + dy * dy);
          if (d < LINK) {
            const a = (1 - d / LINK) * 0.28;
            ctx.beginPath();
            ctx.moveTo(pts[i].x, pts[i].y);
            ctx.lineTo(pts[j].x, pts[j].y);
            ctx.strokeStyle = `rgba(${lr},${lg},${lb},${a.toFixed(3)})`;
            ctx.lineWidth = 0.65;
            ctx.stroke();
          }
        }
      }

      // ── Update and draw nodes ──────────────────────────────────────────
      pts.forEach(p => {
        // Mouse repulsion
        const mdx = p.x - mx, mdy = p.y - my;
        const md = Math.sqrt(mdx * mdx + mdy * mdy);
        if (md < REPEL_R && md > 0) {
          const f = ((REPEL_R - md) / REPEL_R) * REPEL_F;
          p.vx += (mdx / md) * f;
          p.vy += (mdy / md) * f;
        }

        if (p.isShape) {
          // Spring-back to target
          p.vx += (p.tx - p.x) * p.spring + (Math.random() - 0.5) * DRIFT;
          p.vy += (p.ty - p.y) * p.spring + (Math.random() - 0.5) * DRIFT;
          p.vx *= FRICTION;
          p.vy *= FRICTION;
        } else {
          // Free float with soft wall bounce
          p.vx *= AMBIENT_FRICTION;
          p.vy *= AMBIENT_FRICTION;
          if (p.x < 8 || p.x > size - 8) p.vx *= -1;
          if (p.y < 8 || p.y > size - 8) p.vy *= -1;
        }

        // Velocity cap
        const spd = Math.sqrt(p.vx * p.vx + p.vy * p.vy);
        if (spd > MAX_SPEED) { p.vx *= MAX_SPEED / spd; p.vy *= MAX_SPEED / spd; }

        p.x += p.vx;
        p.y += p.vy;

        // Draw
        const near = md < REPEL_R;
        let nodeR = near ? p.r * 1.3 : p.r;
        const nodeA = near ? Math.min(1, p.alpha * 1.15) : p.alpha;

        // Special dot: pulsing ring
        if (p.isDot) {
          nodeR = p.r + Math.sin(frame * 0.04) * 0.8;
          ctx.beginPath();
          ctx.arc(p.x, p.y, nodeR + 5 + Math.sin(frame * 0.04) * 2, 0, Math.PI * 2);
          ctx.strokeStyle = `rgba(${nr},${ng},${nb},0.18)`;
          ctx.lineWidth = 1;
          ctx.stroke();
        }

        ctx.beginPath();
        ctx.arc(p.x, p.y, nodeR, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${nr},${ng},${nb},${nodeA.toFixed(3)})`;
        ctx.fill();
      });

      frame++;
      raf = requestAnimationFrame(tick);
    };

    // Reduced-motion: draw one static frame at target positions, skip the loop.
    // Never return early before drawing — that leaves the canvas blank (worse than animation).
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      pts.forEach(p => {
        if (p.isShape) { p.x = p.tx; p.y = p.ty; }
      });
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
  }, [size, ambientCount]);

  return (
    <canvas
      ref={ref}
      style={{ width: size, height: size, cursor: "crosshair" }}
      aria-hidden="true"
    />
  );
}
