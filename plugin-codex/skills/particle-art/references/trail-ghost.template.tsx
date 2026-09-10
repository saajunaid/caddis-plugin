"use client";
/**
 * trail-ghost.template.tsx — Spring-morph nodes with phosphorescent trailing effect.
 *
 * USAGE:
 *   1. Copy and rename (e.g. TrailGhost.tsx, HeroTrails.tsx)
 *   2. Replace `buildTargets` with any shape from shape-sampler.ts
 *   3. Tune TRAIL_DECAY (lower → shorter trails) and TRAIL_MAX (higher → longer tails)
 *   4. Background colour is baked into the persistence rect — change "0,0,0" for light mode
 *
 * KEY TECHNIQUE: instead of ctx.clearRect() each frame, fill with a semi-transparent rect
 * (rgba(0,0,0,0.10)). Old frames fade rather than vanish, creating ghostly smeared trails.
 *
 * INTERACTION: mousemove → nodes coalesce into letter; mouseleave → drift apart
 * THEMING: --accent-strong (node colour), --accent-soft (connection lines)
 */
import { useEffect, useRef } from "react";

// ── Bezier helper ─────────────────────────────────────────────────────────────
function cubicBezier(
  t: number,
  p0: [number, number], p1: [number, number],
  p2: [number, number], p3: [number, number],
): [number, number] {
  const m = 1 - t;
  return [
    m**3*p0[0] + 3*m**2*t*p1[0] + 3*m*t**2*p2[0] + t**3*p3[0],
    m**3*p0[1] + 3*m**2*t*p1[1] + 3*m*t**2*p2[1] + t**3*p3[1],
  ];
}

// ── Target shape — replace or import from shape-sampler.ts ───────────────────
//
// CUSTOMISE: swap this function for any sampleText / sampleSVGPath / sampleConstellation call.
// Return an array of { tx, ty, spring, r, alpha, isDot } objects.
//
interface Target { tx: number; ty: number; spring: number; r: number; alpha: number; isDot: boolean }

function buildTargets(size: number): Target[] {
  const cx = size * 0.50;
  const stemTop = size * 0.210, stemBot = size * 0.660;
  const targets: Target[] = [];

  // Tittle (dot above stem)
  targets.push({ tx: cx, ty: size * 0.130, spring: 0.038, r: 4.5, alpha: 1.0, isDot: true });

  // Vertical stem
  for (let i = 0; i <= 12; i++)
    targets.push({ tx: cx, ty: stemTop + (i / 12) * (stemBot - stemTop), spring: 0.036, r: 2.0, alpha: 0.92, isDot: false });

  // Hook (cubic bezier descender)
  const P0: [number,number] = [cx, stemBot];
  const P1: [number,number] = [cx, stemBot + size * 0.115];
  const P2: [number,number] = [cx - size * 0.115, stemBot + size * 0.145];
  const P3: [number,number] = [cx - size * 0.155, stemBot + size * 0.040];
  for (let i = 1; i <= 9; i++) {
    const [bx, by] = cubicBezier(i / 9, P0, P1, P2, P3);
    targets.push({ tx: bx, ty: by, spring: 0.034, r: 2.0, alpha: 0.88, isDot: false });
  }
  return targets;
}

// ── Types & theme helper ──────────────────────────────────────────────────────
interface Pt {
  x: number; y: number; vx: number; vy: number;
  tx: number; ty: number; springBase: number;
  r: number; alpha: number; isDot: boolean; isLetter: boolean;
  trail: { x: number; y: number; a: number }[];
}

function themeRgb(v: string): [number, number, number] {
  const ch = getComputedStyle(document.documentElement)
    .getPropertyValue(v).trim().split(/\s+/).map(Number);
  return [ch[0], ch[1], ch[2]];
}

// ── Constants ─────────────────────────────────────────────────────────────────
const LINK          = 68;    // connection line distance threshold (px)
const MAX_SPEED     = 1.5;
const IDLE_FRICTION = 0.984; // low friction → nodes drift organically in idle
const ACTIVE_FRICTION = 0.88; // snappy convergence on hover
const DRIFT         = 0.055; // random brownian nudge in idle
const MORPH_SPEED   = 0.05;  // lerp rate 0→1; higher = faster morph
const TRAIL_DECAY   = 0.91;  // per-frame alpha multiplier — lower = shorter trails (try 0.80–0.96)
const TRAIL_MAX     = 50;    // max trail history length per node

// ── Component ─────────────────────────────────────────────────────────────────
export function TrailGhostArt({ size = 300 }: { size?: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  // useRef for cross-RAF state — never stale in the animation loop
  const active = useRef(false);
  const morph  = useRef(0);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const ctx = el.getContext("2d")!;
    const dpr = window.devicePixelRatio || 1;
    el.width  = size * dpr;
    el.height = size * dpr;
    ctx.scale(dpr, dpr);

    const cx = size * 0.50, cy = size * 0.46;

    // Letter nodes — start scattered, attracted to targets on hover
    const pts: Pt[] = buildTargets(size).map(t => {
      const angle = Math.random() * Math.PI * 2;
      const dist  = size * (0.10 + Math.random() * 0.32);
      return {
        x: cx + Math.cos(angle) * dist,
        y: cy + Math.sin(angle) * dist,
        vx: (Math.random() - 0.5) * 0.6,
        vy: (Math.random() - 0.5) * 0.6,
        tx: t.tx, ty: t.ty, springBase: t.spring,
        r: t.r, alpha: t.alpha, isDot: t.isDot, isLetter: true,
        trail: [],
      };
    });

    // Ambient nodes — no letter target, add atmosphere
    // CUSTOMISE: increase count, adjust alpha, starting radius
    for (let i = 0; i < 10; i++) {
      const angle = (i / 10) * Math.PI * 2;
      const dist  = size * (0.24 + Math.random() * 0.18);
      pts.push({
        x: cx + Math.cos(angle) * dist * 0.75,
        y: cy + Math.sin(angle) * dist,
        vx: (Math.random() - 0.5) * 0.3,
        vy: (Math.random() - 0.5) * 0.3,
        tx: cx, ty: cy, springBase: 0,
        r: Math.random() * 0.9 + 0.5,
        alpha: 0.30 + Math.random() * 0.20,
        isDot: false, isLetter: false,
        trail: [],
      });
    }

    // mousemove is more reliable than mouseenter on canvas in React 18
    const onMove  = () => { active.current = true; };
    const onLeave = () => { active.current = false; };
    el.addEventListener("mousemove",  onMove);
    el.addEventListener("mouseleave", onLeave);

    let raf: number;
    let frame = 0;

    const tick = () => {
      // PERSISTENCE ghost — fill instead of clearRect; old pixels fade gradually
      // CUSTOMISE: increase alpha (e.g. 0.20) for shorter trails; decrease (0.05) for longer
      ctx.fillStyle = "rgba(0,0,0,0.10)";
      ctx.fillRect(0, 0, size, size);

      const [nr, ng, nb] = themeRgb("--accent-strong");
      const [lr, lg, lb] = themeRgb("--accent-soft");

      // Lerp morph 0 (idle) → 1 (letter formed)
      const m = morph.current + ((active.current ? 1 : 0) - morph.current) * MORPH_SPEED;
      morph.current = m;

      // Connection lines — faint web between nearby nodes
      for (let i = 0; i < pts.length; i++) {
        for (let j = i + 1; j < pts.length; j++) {
          const dx = pts[i].x - pts[j].x, dy = pts[i].y - pts[j].y;
          const d  = Math.sqrt(dx * dx + dy * dy);
          if (d < LINK) {
            ctx.beginPath();
            ctx.moveTo(pts[i].x, pts[i].y);
            ctx.lineTo(pts[j].x, pts[j].y);
            ctx.strokeStyle = `rgba(${lr},${lg},${lb},${((1 - d / LINK) * 0.14).toFixed(3)})`;
            ctx.lineWidth = 0.5;
            ctx.stroke();
          }
        }
      }

      pts.forEach(p => {
        // 1. Record trail before moving, decay all entries, trim to TRAIL_MAX
        p.trail.unshift({ x: p.x, y: p.y, a: p.alpha * 0.65 });
        p.trail.forEach(t => { t.a *= TRAIL_DECAY; });
        while (p.trail.length > TRAIL_MAX) p.trail.pop();

        // 2. Draw trail — fading, shrinking circles back through history
        p.trail.forEach((t, i) => {
          const frac = i / TRAIL_MAX;
          const r = Math.max(0.2, p.r * (1 - frac * 0.88));
          ctx.beginPath();
          ctx.arc(t.x, t.y, r, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(${nr},${ng},${nb},${Math.max(0, t.a).toFixed(3)})`;
          ctx.fill();
        });

        // 3. Physics
        if (p.isLetter) {
          // Spring toward target (scales with morph)
          p.vx += (p.tx - p.x) * p.springBase * m;
          p.vy += (p.ty - p.y) * p.springBase * m;
          // Brownian drift fades out as letter forms
          p.vx += (Math.random() - 0.5) * DRIFT * (1 - m);
          p.vy += (Math.random() - 0.5) * DRIFT * (1 - m);
          // Gentle centre gravity in idle so nodes don't escape
          p.vx += (cx - p.x) * 0.0009 * (1 - m);
          p.vy += (cy - p.y) * 0.0009 * (1 - m);
          // Friction blends from idle to active
          const fr = IDLE_FRICTION + (ACTIVE_FRICTION - IDLE_FRICTION) * m;
          p.vx *= fr; p.vy *= fr;
          // Soft wall bounce in idle
          if (m < 0.15) {
            if (p.x < 6 || p.x > size - 6) p.vx *= -0.8;
            if (p.y < 6 || p.y > size - 6) p.vy *= -0.8;
          }
        } else {
          p.vx += (Math.random() - 0.5) * DRIFT * 0.5;
          p.vy += (Math.random() - 0.5) * DRIFT * 0.5;
          p.vx += (cx - p.x) * 0.0006;
          p.vy += (cy - p.y) * 0.0006;
          p.vx *= IDLE_FRICTION; p.vy *= IDLE_FRICTION;
          if (p.x < 6 || p.x > size - 6) p.vx *= -0.8;
          if (p.y < 6 || p.y > size - 6) p.vy *= -0.8;
        }

        const spd = Math.sqrt(p.vx * p.vx + p.vy * p.vy);
        if (spd > MAX_SPEED) { p.vx *= MAX_SPEED / spd; p.vy *= MAX_SPEED / spd; }
        p.x += p.vx; p.y += p.vy;

        // 4. Node head — bright dot on top of trail
        let nodeR = p.r;
        if (p.isDot && m > 0.15) {
          // Pulsing glow ring for the tittle (dot above "j" stem)
          nodeR = p.r + Math.sin(frame * 0.04) * 0.8;
          ctx.beginPath();
          ctx.arc(p.x, p.y, nodeR + 5 + Math.sin(frame * 0.04) * 2, 0, Math.PI * 2);
          ctx.strokeStyle = `rgba(${nr},${ng},${nb},${(0.20 * m).toFixed(3)})`;
          ctx.lineWidth = 1;
          ctx.stroke();
        }
        ctx.beginPath();
        ctx.arc(p.x, p.y, nodeR, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(${nr},${ng},${nb},${p.alpha.toFixed(3)})`;
        ctx.fill();
      });

      frame++;
      raf = requestAnimationFrame(tick);
    };
    tick();

    // ⚠️ prefers-reduced-motion: do NOT early-return before drawing (leaves canvas blank).
    // Correct approach would be: snap all pts to targets, call tick() once, then cancelRAF.
    // This component always animates — add static-snap logic here if reduced motion is required.

    return () => {
      cancelAnimationFrame(raf);
      el.removeEventListener("mousemove",  onMove);
      el.removeEventListener("mouseleave", onLeave);
    };
  }, [size]);

  return (
    <canvas
      ref={ref}
      style={{ width: size, height: size, cursor: "crosshair" }}
      aria-hidden="true"
    />
  );
}
