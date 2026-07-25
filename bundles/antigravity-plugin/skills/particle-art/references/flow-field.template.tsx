"use client";
/**
 * flow-field.template.tsx — Particles driven by 2D value noise; morph into shape on hover.
 *
 * USAGE:
 *   1. Copy and rename (e.g. FlowField.tsx, HeroFlow.tsx)
 *   2. Replace `buildTargets` with any shape from shape-sampler.ts
 *   3. Tune FLOW_FORCE (current strength), FRICTION, and MORPH_SPEED
 *   4. Ambient-only mode: remove letter targets entirely; particles just drift with noise
 *
 * KEY TECHNIQUE: every particle follows a `flowAngle` derived from two octaves of value noise
 * (vnoise). On hover, spring forces toward letter targets compete with the noise field; morph
 * controls the blend (0 = pure noise, 1 = 25% noise + 75% spring). Particles are drawn as
 * velocity-aligned streaks to show flow direction.
 *
 * INTERACTION: mousemove → letter assembles from flowing particles; mouseleave → disperses back
 * THEMING: --accent-strong (streak/node), --accent-soft (connection lines)
 */
import { useEffect, useRef } from "react";

// ── 2D value noise ─────────────────────────────────────────────────────────────
//
// Coherent noise — same sin-hash base as shape-sampler.ts.
// Input: continuous (x, y). Output: 0..1, smoothly varying.
//
function vnoise(x: number, y: number): number {
  const ix = Math.floor(x), iy = Math.floor(y);
  const fx = x - ix, fy = y - iy;
  const ux = fx * fx * (3 - 2 * fx); // smoothstep
  const uy = fy * fy * (3 - 2 * fy);
  const h = (a: number, b: number) =>
    (Math.abs(Math.sin(a * 127.1 + b * 311.7) * 43758.5453)) % 1;
  const aa = h(ix,   iy),   ba = h(ix+1, iy);
  const ab = h(ix,   iy+1), bb = h(ix+1, iy+1);
  return aa + (ba-aa)*ux + (ab-aa)*uy + (aa-ba-ab+bb)*ux*uy;
}

// Two-octave flow angle — animates over time via `t`
// CUSTOMISE: adjust multipliers for scale (0.008 = large cells) and speed (0.00035 = slow drift)
function flowAngle(x: number, y: number, t: number): number {
  const n1 = vnoise(x * 0.008 + t * 0.00035, y * 0.008);
  const n2 = vnoise(x * 0.015 + t * 0.0005 + 100, y * 0.015 + 50);
  return (n1 * 0.65 + n2 * 0.35) * Math.PI * 4;
}

// ── Target shape — replace or import from shape-sampler.ts ───────────────────
function cubicBezier(
  t: number,
  p0: [number,number], p1: [number,number],
  p2: [number,number], p3: [number,number],
): [number,number] {
  const m = 1 - t;
  return [
    m**3*p0[0]+3*m**2*t*p1[0]+3*m*t**2*p2[0]+t**3*p3[0],
    m**3*p0[1]+3*m**2*t*p1[1]+3*m*t**2*p2[1]+t**3*p3[1],
  ];
}

interface Target { tx: number; ty: number; spring: number; r: number; alpha: number; isDot: boolean }

function buildTargets(size: number): Target[] {
  const cx = size * 0.50;
  const stemTop = size * 0.210, stemBot = size * 0.660;
  const out: Target[] = [];

  // Tittle
  out.push({ tx: cx, ty: size * 0.130, spring: 0.030, r: 4.5, alpha: 1.0, isDot: true });

  // Stem
  for (let i = 0; i <= 12; i++)
    out.push({ tx: cx, ty: stemTop + (i/12) * (stemBot-stemTop), spring: 0.028, r: 2.2, alpha: 0.92, isDot: false });

  // Hook
  const P0: [number,number] = [cx, stemBot];
  const P1: [number,number] = [cx, stemBot + size*0.115];
  const P2: [number,number] = [cx - size*0.115, stemBot + size*0.145];
  const P3: [number,number] = [cx - size*0.155, stemBot + size*0.040];
  for (let i = 1; i <= 9; i++) {
    const [bx,by] = cubicBezier(i/9, P0, P1, P2, P3);
    out.push({ tx: bx, ty: by, spring: 0.026, r: 2.2, alpha: 0.88, isDot: false });
  }
  return out;
}

// ── Types & theme helper ──────────────────────────────────────────────────────
interface Pt {
  x: number; y: number; vx: number; vy: number;
  tx: number; ty: number; spring: number;
  r: number; alpha: number; isDot: boolean; isLetter: boolean;
}

function themeRgb(v: string): [number, number, number] {
  const ch = getComputedStyle(document.documentElement)
    .getPropertyValue(v).trim().split(/\s+/).map(Number);
  return [ch[0], ch[1], ch[2]];
}

// ── Constants ─────────────────────────────────────────────────────────────────
const FLOW_FORCE  = 0.06;   // noise field push strength; raise for wilder currents
const FRICTION    = 0.965;  // less damping than spring components — particles glide
const MAX_SPEED   = 1.8;
const MORPH_SPEED = 0.048;  // lerp speed 0→1; lower = longer, dreamier transition
const LINK        = 80;     // connection line distance threshold (px)

// ── Component ─────────────────────────────────────────────────────────────────
export function FlowFieldArt({ size = 300 }: { size?: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  // useRef — never stale in the RAF loop
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

    // Letter particles — scattered initially; attracted to letter on hover
    const pts: Pt[] = buildTargets(size).map(t => ({
      x:  cx + (Math.random() - 0.5) * size * 0.6,
      y:  cy + (Math.random() - 0.5) * size * 0.6,
      vx: (Math.random() - 0.5) * 0.5,
      vy: (Math.random() - 0.5) * 0.5,
      tx: t.tx, ty: t.ty, spring: t.spring,
      r: t.r, alpha: t.alpha, isDot: t.isDot, isLetter: true,
    }));

    // Ambient flow-only particles — no letter target; fill the field
    // CUSTOMISE: increase count for denser streams
    for (let i = 0; i < 22; i++) {
      pts.push({
        x: Math.random() * size, y: Math.random() * size,
        vx: (Math.random() - 0.5) * 0.4,
        vy: (Math.random() - 0.5) * 0.4,
        tx: cx, ty: cy, spring: 0,
        r: Math.random() * 1.2 + 0.5,
        alpha: 0.28 + Math.random() * 0.22,
        isDot: false, isLetter: false,
      });
    }

    const onMove  = () => { active.current = true; };
    const onLeave = () => { active.current = false; };
    el.addEventListener("mousemove",  onMove);
    el.addEventListener("mouseleave", onLeave);

    let raf: number;
    let frame = 0;

    const tick = () => {
      ctx.clearRect(0, 0, size, size);
      const [nr, ng, nb] = themeRgb("--accent-strong");
      const [lr, lg, lb] = themeRgb("--accent-soft");

      const m = morph.current + ((active.current ? 1 : 0) - morph.current) * MORPH_SPEED;
      morph.current = m;

      // Connection lines — grow more visible as letter forms
      for (let i = 0; i < pts.length; i++) {
        for (let j = i + 1; j < pts.length; j++) {
          const dx = pts[i].x - pts[j].x, dy = pts[i].y - pts[j].y;
          const d  = Math.sqrt(dx*dx + dy*dy);
          if (d < LINK) {
            const a = (1 - d/LINK) * 0.14 * (0.4 + m*0.6);
            ctx.beginPath();
            ctx.moveTo(pts[i].x, pts[i].y);
            ctx.lineTo(pts[j].x, pts[j].y);
            ctx.strokeStyle = `rgba(${lr},${lg},${lb},${a.toFixed(3)})`;
            ctx.lineWidth = 0.6;
            ctx.stroke();
          }
        }
      }

      pts.forEach(p => {
        // 1. Flow field force — attenuates as morph strengthens (25% remains at m=1)
        const angle      = flowAngle(p.x, p.y, frame);
        const flowScale  = 1 - m * 0.75;
        p.vx += Math.cos(angle) * FLOW_FORCE * flowScale;
        p.vy += Math.sin(angle) * FLOW_FORCE * flowScale;

        // 2. Spring toward letter target (only for letter particles; scales with morph)
        if (p.isLetter && m > 0.01) {
          p.vx += (p.tx - p.x) * p.spring * m;
          p.vy += (p.ty - p.y) * p.spring * m;
        }

        // 3. Edge wrap in idle (disable during morph to let letter form cleanly)
        if (m < 0.3) {
          if (p.x < 0)    p.x = size;
          if (p.x > size) p.x = 0;
          if (p.y < 0)    p.y = size;
          if (p.y > size) p.y = 0;
        }

        p.vx *= FRICTION; p.vy *= FRICTION;
        const spd = Math.sqrt(p.vx*p.vx + p.vy*p.vy);
        if (spd > MAX_SPEED) { p.vx *= MAX_SPEED/spd; p.vy *= MAX_SPEED/spd; }
        p.x += p.vx; p.y += p.vy;

        // 4. Velocity-aligned streak — shows flow direction
        // Length proportional to speed (particles moving faster cast longer streaks)
        const streakLen = Math.sqrt(p.vx*p.vx + p.vy*p.vy) * 5;
        const alpha     = p.isLetter
          ? p.alpha * (0.55 + m * 0.45) // letter particles brighten as form solidifies
          : p.alpha;

        ctx.beginPath();
        ctx.moveTo(p.x - p.vx * streakLen, p.y - p.vy * streakLen);
        ctx.lineTo(p.x, p.y);
        ctx.strokeStyle = `rgba(${nr},${ng},${nb},${alpha.toFixed(3)})`;
        ctx.lineWidth   = p.r * 1.4;
        ctx.lineCap     = "round";
        ctx.stroke();

        // 5. Solid node dot at head — visible only once letter starts forming
        if (m > 0.2 && p.isLetter) {
          let nodeR = p.r;
          if (p.isDot) {
            nodeR = p.r + Math.sin(frame * 0.04) * 0.8;
            // Pulsing glow ring for tittle
            ctx.beginPath();
            ctx.arc(p.x, p.y, nodeR + 4 + Math.sin(frame * 0.04) * 2, 0, Math.PI * 2);
            ctx.strokeStyle = `rgba(${nr},${ng},${nb},${(0.18 * m).toFixed(3)})`;
            ctx.lineWidth = 1;
            ctx.stroke();
          }
          ctx.beginPath();
          ctx.arc(p.x, p.y, nodeR * m, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(${nr},${ng},${nb},${(alpha * m).toFixed(3)})`;
          ctx.fill();
        }
      });

      frame++;
      raf = requestAnimationFrame(tick);
    };
    tick();

    // ⚠️ prefers-reduced-motion: do NOT early-return before drawing (leaves canvas blank).
    // To support reduced-motion: snap pts to targets, call tick() once, then cancelRAF.

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
