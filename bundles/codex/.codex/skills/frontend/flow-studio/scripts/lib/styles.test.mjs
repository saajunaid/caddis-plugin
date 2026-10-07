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
  assert.match(css, /--edge-w:\s*1\.1px/);
  assert.match(css, /path\.edge \{ fill:none; stroke-width:var\(--edge-w\)/);
  assert.match(css, /path\.edge\.hot \{[^}]*stroke-width:var\(--edge-w-hot\)/);
  assert.match(css, /path\.trail \{[^}]*stroke-width:calc\(var\(--trail-w\)/);
  assert.match(css, /path\.ripple \{[^}]*stroke-width:calc\(var\(--ripple-w\)/);
  // Thin means at most 1.5 px for a plain link and 2 px for the highlighted one.
  const w = (name) => Number(css.match(new RegExp(`${name}:\s*([0-9.]+)px`))[1]);
  assert.ok(w("--edge-w") <= 1.5 && w("--edge-w-hot") <= 2 && w("--ripple-w") <= 2.5 && w("--trail-w") <= 2.5);
});

test("forced-colours mode drops the dot pattern", () => {
  assert.match(css, /@media \(forced-colors: active\) \{ #viewport \{ background: Canvas; \} \}/);
});
