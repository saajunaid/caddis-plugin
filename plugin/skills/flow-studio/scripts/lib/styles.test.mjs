// The canvas look is part of the skill's contract: thin lines and a dotted background, both set by tokens
// an app can override. These tests pin the defaults so a later edit cannot quietly bring back the grid.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { join, dirname } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const css = readFileSync(join(root, "src/styles.css"), "utf8");

test("the canvas background is dots, not grid lines", () => {
  assert.match(css, /#viewport[\s\S]*radial-gradient\(circle, var\(--dot\) var\(--dot-size\)/);
  assert.doesNotMatch(css, /linear-gradient\(var\(--grid\)/, "grid lines must not come back");
});

test("dots are set by tokens: size, spacing and a colour for light and dark", () => {
  assert.match(css, /--dot-size:\s*1\.2px/);
  assert.match(css, /--dot-gap:\s*24px/);
  const colours = css.match(/--dot:\s*rgba\([^)]*\)/g) ?? [];
  assert.ok(colours.length >= 3, "a dot colour for light, dark by media query and dark by attribute");
});

test("links are thin by default and every width comes from a token", () => {
  assert.match(css, /--edge-w:\s*0\.8px/);
  assert.match(css, /path\.edge \{ fill:none; stroke-width:var\(--edge-w\)/);
  assert.match(css, /path\.edge\.hot \{[^}]*stroke-width:var\(--edge-w-hot\)/);
  assert.match(css, /path\.trail \{[^}]*stroke-width:calc\(var\(--trail-w\)/);
  assert.match(css, /path\.ripple \{[^}]*stroke-width:calc\(var\(--ripple-w\)/);
  // Thin means a hairline: at most 1 px for a plain link, 1.2 px for a highlighted or playing one.
  const w = (name) => Number(css.match(new RegExp(`${name}: *([0-9.]+)px`))[1]);
  assert.ok(w("--edge-w") <= 1 && w("--edge-w-hot") <= 1.2 && w("--edge-w-play") <= 1.2 && w("--ripple-w") <= 1.5 && w("--trail-w") <= 1.5);
});

test("the arrowhead is small: at most 7 px, and the playback dot at most 5 px in radius", () => {
  const shell = readFileSync(join(root, "templates/shell-body.html"), "utf8");
  const marker = shell.match(/<marker id="arr"[^>]*markerWidth="(\d+)" markerHeight="(\d+)"/);
  assert.ok(marker, "the arrow marker exists");
  assert.ok(Number(marker[1]) <= 7 && Number(marker[2]) <= 7, `arrowhead is ${marker[1]} x ${marker[2]}`);
  const playback = readFileSync(join(root, "src/playbackui.ts"), "utf8");
  assert.ok(Number(playback.match(/class: "token", r: "(\d+(?:\.\d+)?)"/)[1]) <= 5);
});

test("forced-colours mode drops the dot pattern", () => {
  assert.match(css, /@media \(forced-colors: active\) \{ #viewport \{ background: Canvas; \} \}/);
});
