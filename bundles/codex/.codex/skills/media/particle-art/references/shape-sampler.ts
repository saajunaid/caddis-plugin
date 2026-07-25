/**
 * shape-sampler.ts — Target-point generators for all particle-art shapes.
 *
 * Each function returns an array of [x, y] coordinates in CSS pixel space,
 * ready to use as spring-node target positions.
 *
 * Copy the function(s) you need into your component file.
 */

export type Point = [number, number];

// ─── Text / Initials → Points ─────────────────────────────────────────────────
//
// Renders text onto an off-screen canvas at large size, samples non-transparent
// pixels, then scales back to the target size with optional density control.
//
// Usage:
//   const pts = sampleText("j", 300, { nodeCount: 28, font: "bold 200px serif" });
//
export function sampleText(
  text: string,
  size: number,
  opts: {
    nodeCount?: number;    // approximate number of nodes to return
    font?: string;         // CSS font string (default: bold 180px sans-serif)
    offsetX?: number;      // manual x offset if letter drifts
    offsetY?: number;      // manual y offset
  } = {},
): Point[] {
  const { nodeCount = 30, font = `bold 180px sans-serif`, offsetX = 0, offsetY = 0 } = opts;

  // Render at 4× size for better sampling resolution
  const SCALE = 4;
  const offW = size * SCALE;
  const offH = size * SCALE;

  const oc = document.createElement("canvas");
  oc.width = offW;
  oc.height = offH;
  const oc2 = oc.getContext("2d")!;
  oc2.fillStyle = "#fff";
  oc2.font = font.replace(/(\d+)px/, (_, n) => `${parseInt(n) * SCALE}px`);
  oc2.textAlign = "center";
  oc2.textBaseline = "middle";
  oc2.fillText(text, offW / 2 + offsetX * SCALE, offH / 2 + offsetY * SCALE);

  const { data } = oc2.getImageData(0, 0, offW, offH);
  const candidates: Point[] = [];

  // Sample every Nth pixel so we don't collect millions of points
  const step = Math.max(1, Math.floor(offW / 80));
  for (let y = 0; y < offH; y += step) {
    for (let x = 0; x < offW; x += step) {
      if (data[(y * offW + x) * 4] > 128) {
        candidates.push([x / SCALE, y / SCALE]);
      }
    }
  }

  if (candidates.length === 0) return [];

  // Downsample to nodeCount using spatial stratification
  return stratifiedSample(candidates, nodeCount);
}

// ─── Preset Shapes ────────────────────────────────────────────────────────────

export function sampleConstellation(size: number, nodeCount = 32): Point[] {
  const pts: Point[] = [];
  const cx = size / 2, cy = size / 2;
  const r = size * 0.38;
  // Main ring of nodes
  for (let i = 0; i < Math.floor(nodeCount * 0.6); i++) {
    const a = (i / Math.floor(nodeCount * 0.6)) * Math.PI * 2;
    const jitter = size * 0.06;
    pts.push([
      cx + Math.cos(a) * (r + (srand(i, 0) - 0.5) * jitter),
      cy + Math.sin(a) * (r + (srand(i, 1) - 0.5) * jitter),
    ]);
  }
  // Inner cluster
  const inner = nodeCount - pts.length;
  for (let i = 0; i < inner; i++) {
    const a = srand(i + 100, 0) * Math.PI * 2;
    const d = srand(i + 100, 1) * r * 0.5;
    pts.push([cx + Math.cos(a) * d, cy + Math.sin(a) * d]);
  }
  return pts;
}

export function sampleHelix(size: number, nodeCount = 36): Point[] {
  const pts: Point[] = [];
  const cx = size / 2;
  const spread = size * 0.20;
  for (let i = 0; i < nodeCount; i++) {
    const t = i / (nodeCount - 1);
    const y = size * 0.1 + t * size * 0.8;
    const a = t * Math.PI * 4; // 2 full turns
    pts.push(
      [cx + Math.cos(a) * spread, y],
      [cx - Math.cos(a) * spread, y],
    );
  }
  return pts.slice(0, nodeCount);
}

export function sampleSpiral(size: number, nodeCount = 40): Point[] {
  const pts: Point[] = [];
  const cx = size / 2, cy = size / 2;
  const maxR = size * 0.42;
  for (let i = 0; i < nodeCount; i++) {
    const t = i / nodeCount;
    const a = t * Math.PI * 6; // 3 turns
    const r = t * maxR;
    pts.push([cx + Math.cos(a) * r, cy + Math.sin(a) * r]);
  }
  return pts;
}

export function sampleDNA(size: number, nodeCount = 40): Point[] {
  const pts: Point[] = [];
  const cx = size / 2;
  const spread = size * 0.18;
  const rungs = Math.floor(nodeCount / 3);
  for (let i = 0; i < rungs; i++) {
    const t = i / (rungs - 1);
    const y = size * 0.08 + t * size * 0.84;
    const a = t * Math.PI * 5;
    const lx = cx + Math.cos(a) * spread;
    const rx = cx - Math.cos(a) * spread;
    pts.push([lx, y], [rx, y]);
    // Cross-rung node at midpoint every other step
    if (i % 2 === 0 && pts.length < nodeCount) {
      pts.push([(lx + rx) / 2, y]);
    }
  }
  return pts.slice(0, nodeCount);
}

export function sampleHexGrid(size: number, nodeCount = 36): Point[] {
  const pts: Point[] = [];
  const rows = 5, cols = 7;
  const hx = size / (cols + 0.5);
  const hy = size / (rows + 0.5) * 0.87;
  const ox = hx * 0.5, oy = hy * 0.5;

  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const x = ox + c * hx + (r % 2 === 0 ? 0 : hx / 2);
      const y = oy + r * hy;
      if (x > 0 && x < size && y > 0 && y < size) pts.push([x, y]);
    }
  }
  return stratifiedSample(pts, nodeCount);
}

export function sampleWave(size: number, nodeCount = 36): Point[] {
  const pts: Point[] = [];
  const rows = 4;
  const perRow = Math.ceil(nodeCount / rows);
  for (let r = 0; r < rows; r++) {
    const baseY = size * (0.2 + r * 0.18);
    for (let i = 0; i < perRow; i++) {
      const t = i / (perRow - 1);
      const x = size * 0.08 + t * size * 0.84;
      const y = baseY + Math.sin(t * Math.PI * 2 + r) * size * 0.06;
      pts.push([x, y]);
    }
  }
  return pts.slice(0, nodeCount);
}

export function sampleInfinity(size: number, nodeCount = 36): Point[] {
  const pts: Point[] = [];
  const cx = size / 2, cy = size / 2;
  const a = size * 0.38, b = size * 0.18;
  for (let i = 0; i < nodeCount; i++) {
    const t = (i / nodeCount) * Math.PI * 2;
    // Lemniscate of Bernoulli
    const denom = 1 + Math.sin(t) ** 2;
    const x = cx + (a * Math.cos(t)) / denom;
    const y = cy + (b * Math.sin(t) * Math.cos(t)) / denom;
    pts.push([x, y]);
  }
  return pts;
}

// ─── SVG Path → Points ────────────────────────────────────────────────────────
//
// Samples points along an SVG path element (must be in the DOM or created
// via document.createElementNS). Pass the path's `d` attribute string.
//
// Usage:
//   const pts = sampleSVGPath("M10,80 C40,10 65,10 95,80 S150,150 180,80", 300, 28);
//
export function sampleSVGPath(d: string, size: number, nodeCount = 30): Point[] {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.style.position = "absolute";
  svg.style.opacity = "0";
  svg.style.pointerEvents = "none";
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", d);
  svg.appendChild(path);
  document.body.appendChild(svg);

  const len = path.getTotalLength();
  const pts: Point[] = [];
  // Get bounding box to normalize to [0, size]
  const bbox = path.getBBox();
  const scaleX = size / (bbox.width || 1);
  const scaleY = size / (bbox.height || 1);
  const s = Math.min(scaleX, scaleY) * 0.85; // 85% padding
  const offX = (size - bbox.width * s) / 2 - bbox.x * s;
  const offY = (size - bbox.height * s) / 2 - bbox.y * s;

  for (let i = 0; i < nodeCount; i++) {
    const pt = path.getPointAtLength((i / (nodeCount - 1)) * len);
    pts.push([pt.x * s + offX, pt.y * s + offY]);
  }

  document.body.removeChild(svg);
  return pts;
}

// ─── Polygon / Custom Coordinate Array ────────────────────────────────────────
//
// Takes raw [x, y] pairs (in any coordinate space) and normalizes to [0, size].
//
// Usage:
//   const pts = samplePolygon([[0,0],[1,0],[0.5,1]], 300, 30);
//
export function samplePolygon(
  coords: Point[],
  size: number,
  nodeCount = 30,
): Point[] {
  if (coords.length === 0) return [];

  // Normalize to [0, 1]
  const xs = coords.map(p => p[0]);
  const ys = coords.map(p => p[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minY = Math.min(...ys), maxY = Math.max(...ys);
  const rangeX = maxX - minX || 1;
  const rangeY = maxY - minY || 1;
  const s = Math.min(size / rangeX, size / rangeY) * 0.85;

  // Interpolate along polygon edges
  const edges: Point[] = [];
  for (let i = 0; i < coords.length; i++) {
    const a = coords[i];
    const b = coords[(i + 1) % coords.length];
    const steps = Math.max(2, Math.ceil(nodeCount / coords.length));
    for (let j = 0; j < steps; j++) {
      const t = j / steps;
      edges.push([
        ((a[0] + (b[0] - a[0]) * t) - minX) * s + (size - rangeX * s) / 2,
        ((a[1] + (b[1] - a[1]) * t) - minY) * s + (size - rangeY * s) / 2,
      ]);
    }
  }
  return stratifiedSample(edges, nodeCount);
}

// ─── Internal Helpers ─────────────────────────────────────────────────────────

// Deterministic pseudo-random (avoids hydration mismatch)
function srand(x: number, y: number): number {
  return (Math.abs(Math.sin(x * 127.1 + y * 311.7) * 43758.5453)) % 1;
}

// Spatial stratified downsampling — spreads chosen points evenly across the space
function stratifiedSample(pts: Point[], n: number): Point[] {
  if (pts.length <= n) return pts;
  const step = pts.length / n;
  const result: Point[] = [];
  for (let i = 0; i < n; i++) {
    result.push(pts[Math.floor(i * step)]);
  }
  return result;
}
