import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "../..");

test("docs: (1) every property in model.schema.json appears in references/model-schema.md", () => {
  const schemaPath = join(root, "model.schema.json");
  const docPath = join(root, "references", "model-schema.md");
  assert.ok(existsSync(schemaPath), "model.schema.json exists");
  assert.ok(existsSync(docPath), "references/model-schema.md exists");

  const schema = JSON.parse(readFileSync(schemaPath, "utf8"));
  const doc = readFileSync(docPath, "utf8");

  function collectProperties(obj, props = new Set()) {
    if (!obj || typeof obj !== "object") return props;
    if (obj.properties && typeof obj.properties === "object") {
      for (const p of Object.keys(obj.properties)) {
        props.add(p);
        collectProperties(obj.properties[p], props);
      }
    }
    // tuple-style schemas put subschemas in an items array
    if (Array.isArray(obj.items)) obj.items.forEach(x => collectProperties(x, props));
    else if (obj.items) collectProperties(obj.items, props);
    // definitions/$defs are name->schema maps: walk the schemas, never the names
    if (obj.definitions) for (const def of Object.values(obj.definitions)) collectProperties(def, props);
    if (obj.$defs) for (const def of Object.values(obj.$defs)) collectProperties(def, props);
    if (Array.isArray(obj.allOf)) obj.allOf.forEach(x => collectProperties(x, props));
    if (Array.isArray(obj.anyOf)) obj.anyOf.forEach(x => collectProperties(x, props));
    if (Array.isArray(obj.oneOf)) obj.oneOf.forEach(x => collectProperties(x, props));
    return props;
  }

  // a whole word, not a substring: `id` must not be satisfied by `identifier`
  const wordIn = (text, word) =>
    new RegExp(`(?<![A-Za-z0-9_$-])${word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?![A-Za-z0-9_$-])`).test(text);

  const allProps = Array.from(collectProperties(schema));
  const missing = allProps.filter(p => !wordIn(doc, p));
  assert.deepEqual(missing, [], `Schema properties missing from model-schema.md: ${missing.join(", ")}`);
});

test("docs: (2) every example in examples/ is listed in examples/README.md", () => {
  const examplesDir = join(root, "examples");
  const readmePath = join(examplesDir, "README.md");
  assert.ok(existsSync(readmePath), "examples/README.md exists");

  const examples = readdirSync(examplesDir).filter(f => f.endsWith(".json"));
  const readme = readFileSync(readmePath, "utf8");
  const missing = examples.filter(e => !readme.includes(e));
  assert.deepEqual(missing, [], `Examples missing from examples/README.md: ${missing.join(", ")}`);
});

test("docs: (3) every check group name used in scripts/check.mjs appears in references/verify.md", () => {
  const checkScript = join(root, "scripts", "check.mjs");
  const verifyDoc = join(root, "references", "verify.md");
  assert.ok(existsSync(checkScript), "scripts/check.mjs exists");
  assert.ok(existsSync(verifyDoc), "references/verify.md exists");

  const checkCode = readFileSync(checkScript, "utf8");
  const docText = readFileSync(verifyDoc, "utf8");

  const groups = new Set();
  for (const m of checkCode.matchAll(/\bcheck\(\s*["\x27]([^"\x27]+)["\x27]/g)) {
    groups.add(m[1]);
  }
  const allGroups = Array.from(groups);
  const missing = allGroups.filter(g => !docText.includes(g));
  assert.deepEqual(missing, [], `Check groups missing from references/verify.md: ${missing.join(", ")}`);
});

test("docs: (4) SKILL.md frontmatter has name and description, name is flow-studio, under 220 lines", () => {
  const skillPath = join(root, "SKILL.md");
  assert.ok(existsSync(skillPath), "SKILL.md exists");

  const content = readFileSync(skillPath, "utf8");
  const lines = content.split(/\r?\n/);
  if (lines.length && lines[lines.length - 1] === "") lines.pop(); // a trailing newline is not a line
  assert.ok(lines.length < 220, `SKILL.md has ${lines.length} lines, must be under 220`);

  const fmM = content.match(/^---\r?\n([\s\S]*?)\r?\n---/);
  assert.ok(fmM, "SKILL.md has valid frontmatter block");
  const fm = fmM[1];
  assert.match(fm, /^name:\s*flow-studio\s*$/m, "frontmatter name is flow-studio");
  assert.match(fm, /^description:\s*.+$/m, "frontmatter description is present");
});

test("docs: (5) every relative path in backticks starting with scripts/, src/, references/, examples/, templates/ exists", () => {
  const refDir = join(root, "references");
  const files = [
    join(root, "SKILL.md"),
    ...readdirSync(refDir).map(f => join(refDir, f))
  ];
  const prefixes = ["scripts/", "src/", "references/", "examples/", "templates/"];
  const missing = [];

  for (const file of files) {
    const rawContent = readFileSync(file, "utf8");
    // Strip fenced code blocks so we only check inline backtick code references
    const stripped = rawContent.replace(/```[\s\S]*?```/g, "");
    const matches = stripped.match(/`([^`\r\n]+)`/g) || [];

    for (const m of matches) {
      const token = m.slice(1, -1).trim();
      // A span may hold a command (`scripts/check.mjs --json`) or a line reference
      // (`scripts/check.mjs:23`), so check each whitespace-separated part, stripped of
      // surrounding punctuation and a trailing :line suffix.
      for (const part of token.split(/\s+/)) {
        const candidate = part.replace(/^[("']+/, "").replace(/[.,;:)"']+$/, "").replace(/:\d+$/, "");
        for (const prefix of prefixes) {
          if (candidate.startsWith(prefix)) {
            const resolved = resolve(root, candidate);
            if (!existsSync(resolved)) {
              missing.push({ file: file.replace(root, ""), path: candidate });
            }
          }
        }
      }
    }
  }

  assert.deepEqual(missing, [], `Referenced paths do not exist: ${JSON.stringify(missing)}`);
});
