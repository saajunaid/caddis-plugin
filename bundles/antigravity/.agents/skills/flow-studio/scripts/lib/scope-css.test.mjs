import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { scopeCss, parseCssBlocks, extractAnimationRefs } from "./scope-css.mjs";
import { buildEngine, buildLibrary, checkEngineFiles } from "../build-engine.mjs";
import { stateCss } from "../../src/stateCss.ts";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "../..");
const rawStyles = readFileSync(join(root, "src/styles.css"), "utf8");

function countRules(blocks) {
  let count = 0;
  for (const b of blocks) {
    const clean = b.prelude.replace(/\/\*[\s\S]*?\*\//g, "").trim();
    if (/^@(-webkit-)?keyframes\b/i.test(clean)) {
      count += 1;
    } else if (clean.startsWith("@")) {
      count += countRules(parseCssBlocks(b.body));
    } else {
      count += 1;
    }
  }
  return count;
}

test("scopeCss wraps every non-keyframes rule in @scope (.fs-root) and keeps @keyframes at top level", () => {
  const out = scopeCss(rawStyles, ".fs-root");
  const top = parseCssBlocks(out);
  const scopeBlocks = top.filter(b => b.prelude.replace(/\/\*[\s\S]*?\*\//g, "").trim() === "@scope (.fs-root)");
  assert.equal(scopeBlocks.length, 1, "expected exactly one top-level @scope (.fs-root) block");

  for (const b of top) {
    const clean = b.prelude.replace(/\/\*[\s\S]*?\*\//g, "").trim();
    assert.ok(
      clean === "@scope (.fs-root)" || /^@(-webkit-)?keyframes\b/i.test(clean),
      `unexpected top-level rule outside @scope: ${clean}`,
    );
  }

  const keyframeBlocks = top.filter(b => /^@(-webkit-)?keyframes\b/i.test(b.prelude.replace(/\/\*[\s\S]*?\*\//g, "").trim()));
  const inputKeyframes = parseCssBlocks(rawStyles).filter(b => /^@(-webkit-)?keyframes\b/i.test(b.prelude.replace(/\/\*[\s\S]*?\*\//g, "").trim()));
  assert.equal(keyframeBlocks.length, inputKeyframes.length);
  assert.ok(keyframeBlocks.length > 0, "expected @keyframes blocks in styles.css");
  assert.doesNotMatch(scopeBlocks[0].body, /@(-webkit-)?keyframes\b/i, "no @keyframes inside @scope");
});

test("scopeCss rewrites bare :root, dark-theme :root forms, and plain body while keeping element selectors", () => {
  const out = scopeCss(rawStyles, ".fs-root");
  const scopeBody = parseCssBlocks(out).find(b => b.prelude.replace(/\/\*[\s\S]*?\*\//g, "").trim() === "@scope (.fs-root)").body;

  // No bare `:root {` remains inside the scope
  assert.doesNotMatch(scopeBody, /(?:^|[}\s]):root\s*\{/);

  // Every `:root...` inside scope is an ancestor form ending in `:scope`
  const innerBlocks = parseCssBlocks(scopeBody);
  const allPreludes = [];
  const collect = blocks => {
    for (const b of blocks) {
      const clean = b.prelude.replace(/\/\*[\s\S]*?\*\//g, "").trim();
      if (clean.startsWith("@")) collect(parseCssBlocks(b.body));
      else allPreludes.push(clean);
    }
  };
  collect(innerBlocks);

  assert.ok(allPreludes.includes(":scope"), "bare :root, plain body, and bare .fs-root become :scope");
  assert.equal(allPreludes.filter(p => p === ":scope").length, 3, "bare :root, plain body, and bare .fs-root become :scope");
  assert.ok(allPreludes.includes(':root:not([data-theme="light"]) :scope'), "media dark-theme :root becomes ancestor form");
  assert.ok(allPreludes.includes(':root[data-theme="dark"] :scope'), "explicit dark-theme :root becomes ancestor form");
  assert.ok(!allPreludes.some(p => p === "body"), "plain body { is rewritten to :scope {");
  for (const p of allPreludes) {
    if (p.includes(":root")) assert.match(p, /:scope\b/, `:root selector must target :scope: ${p}`);
  }

  // Element selectors stay as written (now limited by @scope)
  assert.ok(allPreludes.includes("*"));
  assert.ok(allPreludes.includes("button, select, input"));
  assert.ok(allPreludes.includes("main"));
  assert.ok(allPreludes.includes("h1"));
  assert.ok(allPreludes.includes("footer"));
});

test("scopeCss roots .fs-root* and host state classes (.intro, .notes, .playing, .alt) on :scope and throws on body.../html... compounds", () => {
  const out = scopeCss(rawStyles, ".fs-root");
  const scopeBody = parseCssBlocks(out).find(b => b.prelude.replace(/\/\*[\s\S]*?\*\//g, "").trim() === "@scope (.fs-root)").body;

  const selectors = [];
  const collectSelectors = blocks => {
    for (const b of blocks) {
      const clean = b.prelude.replace(/\/\*[\s\S]*?\*\//g, "").trim();
      if (clean.startsWith("@")) collectSelectors(parseCssBlocks(b.body));
      else {
        for (const part of clean.split(",")) selectors.push(part.trim());
      }
    }
  };
  collectSelectors(parseCssBlocks(scopeBody));

  // No selector inside @scope starts with .fs-root
  for (const sel of selectors) {
    assert.equal(
      sel === ".fs-root" || (sel.startsWith(".fs-root") && !/^[A-Za-z0-9_-]/.test(sel.slice(".fs-root".length))),
      false,
      `selector inside @scope must not start with .fs-root: ${sel}`,
    );
  }

  // Each of the 4 host state classes appears rooted as :scope.<state>
  for (const state of ["intro", "notes", "playing", "alt"]) {
    assert.ok(
      selectors.some(sel => sel.startsWith(`:scope.${state}`)),
      `expected at least one selector starting with :scope.${state}, got: ${selectors.join(" | ")}`,
    );
  }

  // Descendant .node.playing and path.edge.playing stay untouched
  assert.ok(selectors.includes(".node.playing"), ".node.playing stays a descendant selector");
  assert.ok(selectors.includes("path.edge.playing"), "path.edge.playing stays a descendant selector");

  // Direct unit check on bare state classes and .fs-root compounds
  const direct = scopeCss(
    ".fs-root { position:relative; }\n.fs-root.notes #drawer { transform:none; }\n.intro .band, .notes .x, .playing .y, .alt .z { opacity:1; }",
    ".fs-root",
  );
  assert.match(direct, /:scope \{ position:relative; \}/);
  assert.match(direct, /:scope\.notes #drawer \{ transform:none; \}/);
  assert.match(direct, /:scope\.intro \.band, :scope\.notes \.x, :scope\.playing \.y, :scope\.alt \.z \{ opacity:1; \}/);

  // Non-plain body... and html... throw rather than guessing
  assert.throws(() => scopeCss("body.x .y { color: red; }"), /unsupported root element selector/);
  assert.throws(() => scopeCss("body > main { color: red; }"), /unsupported root element selector/);
  assert.throws(() => scopeCss("html { font-size: 16px; }"), /unsupported root element selector/);
  assert.throws(() => scopeCss("html.dark .y { color: red; }"), /unsupported root element selector/);
});

test("scopeCss throws with the rule name on unsupported at-rules and keeps @media, @supports, and @starting-style blocks", () => {
  const unsupported = [
    ["@font-face", '@font-face { font-family: "Demo"; src: url("demo.woff2"); }'],
    ["@property", '@property --demo { syntax: "<color>"; inherits: false; initial-value: red; }'],
    ["@page", "@page { margin: 1cm; }"],
    ["@counter-style", '@counter-style thumbs { system: cyclic; symbols: "x"; }'],
    ["@import", '@import "other.css";\n.node { color: red; }'],
    ["@charset", '@charset "UTF-8";\n.node { color: red; }'],
    ["@layer", "@layer base, theme;\n:root { --bg: #fff; }"],
  ];
  for (const [name, sample] of unsupported) {
    assert.throws(
      () => scopeCss(sample, ".fs-root"),
      err => err instanceof Error && err.message.includes(name),
      `expected ${name} to throw naming ${name}`,
    );
  }

  const supported = [
    "@media (max-width: 900px) { .fs-root.notes main { margin-left: 0; } }",
    "@supports (display: grid) { .fs-root { display: grid; } }",
    "@starting-style { .fs-hovercard { opacity: 0; } }",
  ].join("\n");
  const out = scopeCss(supported, ".fs-root");
  assert.match(out, /@media \(max-width: 900px\) \{\s+:scope\.notes main \{ margin-left: 0; \}\s+\}/);
  assert.match(out, /@supports \(display: grid\) \{\s+:scope \{ display: grid; \}\s+\}/);
  assert.match(out, /@starting-style \{\s+\.fs-hovercard \{ opacity: 0; \}\s+\}/);
});

test("every @keyframes and animation reference uses the fs- prefix and resolves to a defined @keyframes", () => {
  const out = scopeCss(rawStyles, ".fs-root");
  const top = parseCssBlocks(out);
  const defined = new Set();
  for (const b of top) {
    const clean = b.prelude.replace(/\/\*[\s\S]*?\*\//g, "").trim();
    const m = clean.match(/^@(?:-webkit-)?keyframes\s+([^\s{]+)/i);
    if (m) {
      assert.ok(m[1].startsWith("fs-"), `@keyframes name must start with fs-: ${m[1]}`);
      defined.add(m[1]);
    }
  }
  assert.equal(defined.size, 12, "expected all 12 fs-* @keyframes definitions");

  const refs = [];
  const collectRefs = blocks => {
    for (const b of blocks) {
      const clean = b.prelude.replace(/\/\*[\s\S]*?\*\//g, "").trim();
      if (/^@(?:-webkit-)?keyframes\b/i.test(clean)) continue;
      if (clean.startsWith("@")) collectRefs(parseCssBlocks(b.body));
      else refs.push(...extractAnimationRefs(b.body));
    }
  };
  collectRefs(top);

  // Also check dynamic stateCss output against the defined @keyframes set
  const dynCss = stateCss({
    live: { word: "LIVE", tone: "ok", border: "solid", edge: "flow", motion: "flow", bucket: "good" },
    doc: { word: "DOC", tone: "muted", border: "dashed", edge: "dash", motion: "flow-slow", bucket: "neutral" },
    code: { word: "CODE", tone: "muted", border: "dashed", edge: "dash-short", motion: "flow-slow", bucket: "neutral" },
    gap: { word: "GAP", tone: "warn", border: "dotted", edge: "dot", motion: "breathe", bucket: "gap" },
  });
  collectRefs(parseCssBlocks(dynCss));

  assert.ok(refs.length > 0, "expected animation references");
  for (const ref of refs) {
    assert.ok(ref.startsWith("fs-"), `animation reference must start with fs-: ${ref}`);
    assert.ok(defined.has(ref), `animation reference "${ref}" must match a defined @keyframes`);
  }

  // Un-prefixed @keyframes or dangling animation references fail loudly
  assert.throws(
    () => scopeCss("@keyframes fadein { from { opacity: 0; } to { opacity: 1; } }\n.x { opacity: 1; }"),
    /@keyframes "fadein" must start with "fs-"/,
  );
  assert.throws(
    () => scopeCss("@keyframes fs-fadein { to { opacity: 1; } }\n.x { animation: fadein 1s; }"),
    /animation reference "fadein" must start with "fs-"/,
  );
  assert.throws(
    () => scopeCss("@keyframes fs-fadein { to { opacity: 1; } }\n.x { animation: fs-missing 1s; }"),
    /animation reference "fs-missing" has no matching @keyframes/,
  );
  assert.throws(
    () => scopeCss("@keyframes fs-fadein { to { opacity: 1; } }\n.x { animation-name: fs-missing; }"),
    /animation reference "fs-missing" has no matching @keyframes/,
  );
});

test("scopeCss normalises CRLF input to LF with zero carriage returns", () => {
  const lf = rawStyles.replace(/\r\n?/g, "\n");
  const crlf = lf.replace(/\n/g, "\r\n");
  const outLf = scopeCss(lf, ".fs-root");
  const outCrlf = scopeCss(crlf, ".fs-root");
  assert.equal(outCrlf.includes("\r"), false, "output must contain no \\r");
  assert.equal(outCrlf, outLf, "CRLF and LF inputs must produce identical output");
});

test("scopeCss preserves exact rule count (rule count in equals rule count out)", () => {
  const out = scopeCss(rawStyles, ".fs-root");
  const inCount = countRules(parseCssBlocks(rawStyles));
  const outCount = countRules(parseCssBlocks(out));
  assert.equal(outCount, inCount, `expected ${inCount} rules out, got ${outCount}`);
});

test("committed flow-studio.scoped.css matches buildLibrary() and checkEngineFiles rejects stale scoped CSS", async () => {
  const html = await buildEngine();
  const lib = await buildLibrary();
  assert.equal(typeof lib.scopedCss, "string");
  assert.equal(lib.scopedCss.includes("\r"), false);

  const scopedPath = join(root, "templates/flow-studio.scoped.css");
  assert.equal(existsSync(scopedPath), true, "templates/flow-studio.scoped.css must exist");
  assert.equal(readFileSync(scopedPath, "utf8").replace(/\r\n/g, "\n"), lib.scopedCss);

  const dir = mkdtempSync(join(tmpdir(), "fs-check-engine-"));
  try {
    const tpl = join(dir, "templates");
    mkdirSync(tpl, { recursive: true });
    writeFileSync(join(tpl, "engine.html"), html, "utf8");
    writeFileSync(join(tpl, "flow-studio.lib.mjs"), lib.js, "utf8");
    writeFileSync(join(tpl, "flow-studio.css"), lib.css, "utf8");
    writeFileSync(join(tpl, "flow-studio.scoped.css"), lib.scopedCss, "utf8");
    assert.equal(await checkEngineFiles(dir), true);

    writeFileSync(join(tpl, "flow-studio.scoped.css"), lib.scopedCss + "\n/* stale */\n", "utf8");
    assert.equal(await checkEngineFiles(dir), false, "stale flow-studio.scoped.css must fail check:engine");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
