import { test } from "node:test";
import assert from "node:assert/strict";
import type { Model } from "./model.ts";
import { stateCss, toneVar } from "./stateCss.ts";

const states: Model["states"] = {
  live: { word: "LIVE", tone: "ok", border: "solid", edge: "flow", motion: "flow", bucket: "good" },
  doc: { word: "DOC", tone: "muted", border: "dashed", edge: "dash", motion: "flow-slow", bucket: "neutral" },
  code: { word: "CODE", tone: "muted", border: "dashed", edge: "dash-short", motion: "flow-slow", bucket: "neutral" },
  gap: { word: "GAP", tone: "warn", border: "dotted", edge: "dot", motion: "breathe", bucket: "gap" },
};

test("toneVar maps every tone to a CSS variable", () => {
  for (const t of ["ok", "warn", "crit", "info", "muted", "accent"] as const) assert.match(toneVar(t), /^var\(--[a-z]+\)$/);
});
test("each state gets a node rule, a word rule and an edge rule", () => {
  const css = stateCss(states);
  for (const id of Object.keys(states)) {
    assert.ok(css.includes(`.node.st-${id}`), `node ${id}`);
    assert.ok(css.includes(`.ev.st-${id}`), `word ${id}`);
    assert.ok(css.includes(`path.edge.st-${id}`), `edge ${id}`);
  }
});
test("a dotted state is a tinted card with a dotted border", () => {
  const css = stateCss(states);
  assert.match(css, /\.node\.st-gap\s*\{[^}]*dotted/);
  assert.match(css, /\.node\.st-gap\s*\{[^}]*background/);
});
test("a solid state has a solid left border", () => assert.match(stateCss(states), /\.node\.st-live\s*\{[^}]*border-left:4px solid/));
test("breathe adds the breathing animation only to the node", () => {
  const css = stateCss(states);
  assert.match(css, /\.node\.st-gap:not\(\.dim\)\s*\{[^}]*animation:breathe/);
  assert.doesNotMatch(css, /path\.edge\.st-gap\s*\{[^}]*animation/);
});
test("flow speed follows the motion: fast for flow, slow for flow-slow", () => {
  const css = stateCss(states);
  assert.match(css, /path\.edge\.st-live\s*\{[^}]*flow 3s/);
  assert.match(css, /path\.edge\.st-doc\s*\{[^}]*flowd 7s/);
  assert.match(css, /path\.edge\.st-code\s*\{[^}]*flowc 7s/);
});
test("the dash pattern follows the edge style", () => {
  const css = stateCss(states);
  assert.match(css, /path\.edge\.st-live\s*\{[^}]*stroke-dasharray:5 9/);
  assert.match(css, /path\.edge\.st-doc\s*\{[^}]*stroke-dasharray:7 6/);
  assert.match(css, /path\.edge\.st-code\s*\{[^}]*stroke-dasharray:3 6/);
  assert.match(css, /path\.edge\.st-gap\s*\{[^}]*stroke-dasharray:2 6/);
});
test("a flowing state turns solid under reduced motion", () => {
  const css = stateCss(states);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)[^@]*path\.edge\.st-live[^}]*stroke-dasharray:none/);
});
test("an unexpected edge or motion value never prints 'undefined' into the CSS", () => {
  const css = stateCss({ odd: { word: "ODD", tone: "ok", border: "solid", edge: "wavy" as any, motion: "spin" as any, bucket: "good" } });
  assert.doesNotMatch(css, /undefined/);
});
test("names from Object.prototype are not accepted as an edge style", () => {
  for (const edge of ["constructor", "toString", "__proto__", "hasOwnProperty"]) {
    const css = stateCss({ odd: { word: "ODD", tone: edge as any, border: "solid", edge: edge as any, motion: "flow", bucket: "good" } });
    assert.doesNotMatch(css, /native code|function|undefined|\[object/, edge);
  }
});
test("a state id with markup characters cannot break out of the selector", () => {
  const css = stateCss({ 'x"}<script>': states.live });
  assert.doesNotMatch(css, /<script>/);
  assert.doesNotMatch(css, /x"\}/);
});
