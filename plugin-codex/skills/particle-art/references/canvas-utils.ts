/**
 * canvas-utils.ts — Shared canvas helpers for all particle-art components.
 *
 * Copy the functions you need directly into your component file.
 * These are NOT meant to be imported as a module — they are reference implementations.
 */

// ─── DPR-Correct Canvas Setup ────────────────────────────────────────────────
//
// Must be called in useEffect, AFTER the canvas ref is attached.
// Returns the 2D context; the canvas is scaled so all drawing coordinates
// are in CSS pixels (no need to multiply by dpr elsewhere).
//
// Usage:
//   const ctx = setupCanvas(ref.current!, size);
//
export function setupCanvas(
  el: HTMLCanvasElement,
  size: number,
): CanvasRenderingContext2D {
  const ctx = el.getContext("2d")!;
  const dpr = window.devicePixelRatio || 1;
  el.width = size * dpr;
  el.height = size * dpr;
  ctx.scale(dpr, dpr);
  return ctx;
}

// ─── Theme-Aware Colour Reading ───────────────────────────────────────────────
//
// Reads a CSS custom property (e.g. "--accent-strong") and returns [R, G, B].
// The value must be space-separated channels: "79 209 197".
// Call this INSIDE the RAF loop so theme changes (light/dark toggle) auto-apply.
//
// Standard variable names for projects using CSS-variable design tokens:
//   "--accent-strong"  →  primary colour (brightest nodes, tittle glow)
//   "--accent-soft"    →  secondary colour (lines, ambient nodes)
//   "--fg"             →  foreground / text colour
//   "--bg"             →  page background
//
export function themeRgb(varName: string): [number, number, number] {
  const raw = getComputedStyle(document.documentElement)
    .getPropertyValue(varName)
    .trim()
    .split(/\s+/)
    .map(Number);
  return [raw[0] ?? 100, raw[1] ?? 100, raw[2] ?? 100];
}

// Convenience: build a CSS rgba() string from a themeRgb result + alpha
export function rgba(
  [r, g, b]: [number, number, number],
  alpha: number,
): string {
  return `rgba(${r},${g},${b},${alpha.toFixed(3)})`;
}

// ─── Hex Colour Fallback ──────────────────────────────────────────────────────
//
// Use when the project does NOT have CSS custom properties.
// Pass hex strings in the component's props and convert once.
//
export function hexToRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.replace("#", ""), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

// ─── Mouse Tracking ───────────────────────────────────────────────────────────
//
// Returns a ref-compatible object and attaches listeners to the canvas.
// The position is in CSS pixels (matches drawing coordinates).
// Returns a cleanup function — call it in the useEffect return.
//
// Usage:
//   const mouse = { x: -9999, y: -9999 };
//   const cleanupMouse = attachMouseTracking(el, mouse);
//   return () => { cancelAnimationFrame(raf); cleanupMouse(); };
//
export function attachMouseTracking(
  el: HTMLCanvasElement,
  mouse: { x: number; y: number },
): () => void {
  const onMove = (e: MouseEvent) => {
    const r = el.getBoundingClientRect();
    mouse.x = e.clientX - r.left;
    mouse.y = e.clientY - r.top;
  };
  const onLeave = () => {
    mouse.x = -9999;
    mouse.y = -9999;
  };
  el.addEventListener("mousemove", onMove);
  el.addEventListener("mouseleave", onLeave);
  return () => {
    el.removeEventListener("mousemove", onMove);
    el.removeEventListener("mouseleave", onLeave);
  };
}

// ─── Velocity Cap ─────────────────────────────────────────────────────────────
//
// Prevents particles from flying off-screen after strong mouse interactions.
// Apply AFTER adding forces, BEFORE updating position.
//
export function capVelocity(
  p: { vx: number; vy: number },
  maxSpeed: number,
): void {
  const spd = Math.sqrt(p.vx * p.vx + p.vy * p.vy);
  if (spd > maxSpeed) {
    p.vx *= maxSpeed / spd;
    p.vy *= maxSpeed / spd;
  }
}

// ─── Reduced-Motion Guard ─────────────────────────────────────────────────────
//
// ⚠️  DO NOT use this as an early `return` before drawing — that leaves the
//     canvas completely blank, which is WORSE than showing animation.
//
// Correct pattern for canvas components:
//   draw one static frame (nodes at target positions), then skip the RAF loop.
//
//   const reduced = prefersReducedMotion();
//   // ... build pts, set up canvas ...
//   if (reduced) {
//     pts.forEach(p => { p.x = p.tx; p.y = p.ty; });  // snap to targets
//     drawOneFrame(ctx, pts, size);                      // render static
//     return;                                            // no RAF
//   }
//   tick(); // full animation
//
// For HTML/stipple components the early return IS fine because HTML content
// is already visible in the DOM without JavaScript.
//
export function prefersReducedMotion(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

// ─── Connection Lines ─────────────────────────────────────────────────────────
//
// Draw faded lines between all particle pairs within linkDist.
// Call this BEFORE drawing nodes so lines appear underneath.
//
// pts must have { x, y } properties.
//
export function drawConnections(
  ctx: CanvasRenderingContext2D,
  pts: { x: number; y: number }[],
  linkDist: number,
  lineColor: [number, number, number],
  maxAlpha = 0.32,
): void {
  const [r, g, b] = lineColor;
  for (let i = 0; i < pts.length; i++) {
    for (let j = i + 1; j < pts.length; j++) {
      const dx = pts[i].x - pts[j].x;
      const dy = pts[i].y - pts[j].y;
      const d = Math.sqrt(dx * dx + dy * dy);
      if (d < linkDist) {
        const a = (1 - d / linkDist) * maxAlpha;
        ctx.beginPath();
        ctx.moveTo(pts[i].x, pts[i].y);
        ctx.lineTo(pts[j].x, pts[j].y);
        ctx.strokeStyle = `rgba(${r},${g},${b},${a.toFixed(3)})`;
        ctx.lineWidth = 0.65;
        ctx.stroke();
      }
    }
  }
}
