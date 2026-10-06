// CSS generated from the model's states. Each state becomes a class (st-<id>) for its card, its word
// and its links, so the engine never assumes state names. The result goes BEFORE the static styles, so
// the static rules for hover, select and failure win when specificity is equal.

import type { Model, Tone, EdgeStyle } from "./model.ts";

/** A state id used as a CSS class. The model validator also restricts ids to this alphabet. */
export const cssId = (id: string): string => id.replace(/[^A-Za-z0-9_-]/g, "_");

const TONES: Record<Tone, string> = { ok: "var(--ok)", warn: "var(--warn)", crit: "var(--crit)", info: "var(--up)", muted: "var(--muted)", accent: "var(--accent)" };
export const toneVar = (t: Tone): string => (Object.hasOwn(TONES, t) ? TONES[t] : TONES.muted);

export const DASH: Record<EdgeStyle, string> = { flow: "5 9", dash: "7 6", "dash-short": "3 6", dot: "2 6" };
const KEYFRAMES: Record<EdgeStyle, string> = { flow: "flow", dash: "flowd", "dash-short": "flowc", dot: "" };

export function stateCss(states: Model["states"]): string {
  const out: string[] = [];
  const reduced: string[] = [];
  for (const [id, s] of Object.entries(states)) {
    const c = cssId(id);
    const T = toneVar(s.tone);
    if (s.border === "dotted") {
      out.push(`.node.st-${c} { border:1px dotted ${T}; background:color-mix(in srgb, ${T} 10%, var(--panel)); --breath:${T}; }`);
      out.push(`.node.st-${c} .t { color:${T}; }`);
    } else {
      const glow = s.bucket === "good" ? ` box-shadow:0 0 14px -4px color-mix(in srgb, ${T} 55%, transparent), var(--shadow);` : "";
      out.push(`.node.st-${c} { border-left:4px ${s.border} ${T};${glow} --breath:${T}; }`);
    }
    out.push(`.node.st-${c}.gateway polygon { stroke:${T}; fill:color-mix(in srgb, ${T} 10%, var(--panel)); }`);
    out.push(`.ev.st-${c} { color:${T}; }`);
    if (s.motion === "breathe") out.push(`.node.st-${c}:not(.dim) { animation:breathe 3.2s ease-in-out infinite; }`);

    const edge: EdgeStyle = Object.hasOwn(DASH, s.edge) ? s.edge : "dash"; // a closed table: an unexpected value never reaches the CSS text
    const flows = edge !== "dot" && (s.motion === "flow" || s.motion === "flow-slow");
    let rule = `stroke:${T}; stroke-dasharray:${DASH[edge]}; opacity:${s.motion === "flow" ? ".85" : ".9"};`;
    if (edge === "dot") rule += " stroke-linecap:round;";
    if (flows) rule += ` animation:${KEYFRAMES[edge]} ${s.motion === "flow" ? "3s" : "7s"} linear infinite;`;
    if (flows && s.motion === "flow") rule += ` filter:drop-shadow(0 0 3px ${T});`;
    out.push(`path.edge.st-${c} { ${rule} }`);
    if (s.bucket === "gap") out.push(`path.edge.hot.st-${c} { stroke:${T}; filter:drop-shadow(0 0 5px ${T}); }`);
    if (flows) reduced.push(`path.edge.st-${c} { stroke-dasharray:none; }`);
  }
  if (reduced.length) out.push(`@media (prefers-reduced-motion: reduce) { ${reduced.join(" ")} }`);
  return out.join("\n");
}
