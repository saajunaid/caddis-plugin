import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { keepDefaultNotes } from "./demo-pack.mjs";

const root = resolve(fileURLToPath(import.meta.url), "../../..");
const run = (script, ...args) =>
  spawnSync(process.execPath, ["--experimental-strip-types", "--no-warnings", join(root, "scripts", script), ...args], { encoding: "utf8" });

const good = {
  version: 1,
  meta: { title: "T", help: "h", asOf: "2026-01-01", source: "s" },
  layout: "columns-lanes",
  columns: [{ id: "c0", title: "A", width: 150 }, { id: "c1", title: "B", width: 150 }],
  lanes: [{ id: "l1", title: "Lane" }],
  states: { ok: { word: "OK", tone: "ok", border: "solid", edge: "flow", motion: "flow", bucket: "good" } },
  nodes: [
    { id: "a", kind: "card", lane: "l1", col: 0, row: 0, state: "ok", title: "A" },
    { id: "b", kind: "card", lane: "l1", col: 1, row: 0, state: "ok", title: "B" },
  ],
  links: [{ id: "a-b", from: "a", to: "b", state: "ok" }],
};
const dir = mkdtempSync(join(tmpdir(), "flow-studio-"));
const write = (name, value) => { const p = join(dir, name); writeFileSync(p, typeof value === "string" ? value : JSON.stringify(value)); return p; };

test("validate: a good model exits 0 and prints OK", () => {
  const r = run("validate.mjs", write("good.json", good));
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /OK/);
});
test("validate: a missing file exits 2", () => assert.equal(run("validate.mjs", join(dir, "nope.json")).status, 2));
test("validate: invalid JSON exits 2", () => assert.equal(run("validate.mjs", write("bad.json", "{not json")).status, 2));
test("validate: a link to a missing node exits 1 and names the link", () => {
  const m = structuredClone(good);
  m.links[0].to = "zzz";
  const r = run("validate.mjs", write("broken.json", m));
  assert.equal(r.status, 1);
  assert.match(r.stdout, /links\[a-b\]/);
});
test("build: a note file cannot override the numbering and must be an array", () => {
  const out = join(dir, "out-notes.html");
  const p = write("notes-model.json", good);
  const notes = write("notes.json", [{ id: 99, anchor: "#viewport", title: "One", text: "t" }, { anchor: "#tools", title: "Two", text: "t" }]);
  // the build needs the generated engine; this test only needs it to exist
  const r = run("build.mjs", p, out, "--notes", notes);
  assert.equal(r.status, 0, r.stderr);
  const html = readFileSync(out, "utf8");
  const m = html.match(/id="flow-notes">(.*?)<\/script>/s);
  assert.ok(m, "the embedded notes script tag is present");
  const parsed = JSON.parse(m[1]);
  assert.deepEqual(parsed.map(n => n.id), [1, 2]);
  const bad = write("notes-bad.json", { not: "an array" });
  assert.equal(run("build.mjs", p, join(dir, "out-bad.html"), "--notes", bad).status, 2);
});
test("build: refuses a model with errors and writes nothing", () => {
  const m = structuredClone(good);
  m.nodes[0].lane = "nope";
  const out = join(dir, "out-refused.html");
  const r = run("build.mjs", write("refused.json", m), out);
  assert.equal(r.status, 1);
  assert.equal(existsSync(out), false);
});

test("build --demo-pack: order and numbering (default first, model second, extra third)", () => {
  const m = structuredClone(good);
  m.notes = [{ anchor: "#viewport", title: "Model Note", text: "model" }];
  const p = write("demo-pack-model.json", m);
  const extra = write("demo-pack-extra.json", [{ anchor: "#kpis", title: "Extra Note", text: "extra" }]);
  const out = join(dir, "out-demo-pack-order.html");
  const r = run("build.mjs", p, out, "--demo-pack", "--notes", extra);
  assert.equal(r.status, 0, r.stderr);
  const html = readFileSync(out, "utf8");
  const match = html.match(/id="flow-notes">(.*?)<\/script>/s);
  assert.ok(match, "the embedded notes script tag is present");
  const parsed = JSON.parse(match[1]);

  // Numbering 1..n
  assert.deepEqual(parsed.map(n => n.id), Array.from({ length: parsed.length }, (_, i) => i + 1));

  // Default notes come first (e.g. Page frame)
  assert.equal(parsed[0].title, "Page frame");

  // Model notes come second
  const modelIdx = parsed.findIndex(n => n.title === "Model Note");
  assert.ok(modelIdx > 0, "model note should be present");

  // Extra notes come third
  const extraIdx = parsed.findIndex(n => n.title === "Extra Note");
  assert.equal(extraIdx, parsed.length - 1);
  assert.ok(modelIdx < extraIdx, "model notes come before extra notes");
});

test("build --demo-pack: drops #playbar without scenarios and #modeSwitch with < 2 views", () => {
  const m = structuredClone(good); // no scenarios, no views
  const p = write("demo-pack-drop.json", m);
  const out = join(dir, "out-demo-pack-drop.html");
  const r = run("build.mjs", p, out, "--demo-pack");
  assert.equal(r.status, 0, r.stderr);
  const html = readFileSync(out, "utf8");
  const match = html.match(/id="flow-notes">(.*?)<\/script>/s);
  assert.ok(match, "the embedded notes script tag is present");
  const parsed = JSON.parse(match[1]);
  assert.equal(parsed.some(n => n.anchor === "#playbar"), false, "should drop playbar note");
  assert.equal(parsed.some(n => n.anchor === "#modeSwitch"), false, "should drop modeSwitch note");
});

test("build --demo-pack: keeps #playbar with scenarios and #modeSwitch with 2+ views", () => {
  const m = structuredClone(good);
  m.views = [
    { id: "v1", title: "View 1" },
    { id: "v2", title: "View 2" },
  ];
  m.scenarios = [
    { id: "s1", label: "Scenario 1", steps: [{ link: "a-b" }] },
  ];
  const p = write("demo-pack-keep.json", m);
  const out = join(dir, "out-demo-pack-keep.html");
  const r = run("build.mjs", p, out, "--demo-pack");
  assert.equal(r.status, 0, r.stderr);
  const html = readFileSync(out, "utf8");
  const match = html.match(/id="flow-notes">(.*?)<\/script>/s);
  assert.ok(match, "the embedded notes script tag is present");
  const parsed = JSON.parse(match[1]);
  assert.equal(parsed.some(n => n.anchor === "#playbar"), true, "should keep playbar note");
  assert.equal(parsed.some(n => n.anchor === "#modeSwitch"), true, "should keep modeSwitch note");
});

test("build: hostile anchors in model notes are preserved safely", () => {
  const m = structuredClone(good);
  m.notes = [
    { anchor: "<script>alert('xss')</script>", title: "Hostile Tag", text: "t" },
    { anchor: "[invalid:css(selector", title: "Invalid Selector", text: "t" },
    { anchor: "\"></script><script>alert(1)</script>", title: "Breakout", text: "t" },
  ];
  const p = write("hostile-notes.json", m);
  const out = join(dir, "out-hostile-notes.html");
  const r = run("build.mjs", p, out);
  assert.equal(r.status, 0, r.stderr);
  const html = readFileSync(out, "utf8");
  const match = html.match(/id="flow-notes">(.*?)<\/script>/s);
  assert.ok(match, "notes script tag should be present and intact");
  const parsed = JSON.parse(match[1]);
  assert.equal(parsed.length, 3);
  assert.equal(parsed[0].anchor, "<script>alert('xss')</script>");
  assert.equal(parsed[1].anchor, "[invalid:css(selector");
  assert.equal(parsed[2].anchor, "\"></script><script>alert(1)</script>");
});

test("build --demo-pack: examples/lineage.json gets kept defaults first, then its own model notes", () => {
  // Expectations come from the example and the shared filter, so the test does not break when
  // the example changes. The filter's own logic is pinned by demo-pack.test.mjs.
  const lineage = JSON.parse(readFileSync(join(root, "examples", "lineage.json"), "utf8"));
  const defaults = JSON.parse(readFileSync(join(root, "scripts", "default-notes.json"), "utf8"));
  const shell = readFileSync(join(root, "templates", "engine.html"), "utf8");
  const kept = keepDefaultNotes(defaults, lineage, shell);
  const expected = kept.length + (lineage.notes?.length ?? 0);
  const outPack = join(dir, "out-lineage-pack.html"); // temp folder: the build must not leave repo artifacts
  const r = run("build.mjs", join(root, "examples", "lineage.json"), outPack, "--demo-pack");
  assert.equal(r.status, 0, r.stderr);
  assert.equal(existsSync(outPack), true);
  const html = readFileSync(outPack, "utf8");
  const match = html.match(/id="flow-notes">(.*?)<\/script>/s);
  assert.ok(match, "the embedded notes script tag is present");
  const parsed = JSON.parse(match[1]);
  assert.equal(parsed.length, expected, `expected ${expected} notes, got ${parsed.length}`);
  for (let i = 0; i < kept.length; i++) {
    assert.equal(parsed[i].anchor, kept[i].anchor, `note ${i + 1} should be the kept default ${kept[i].anchor}`);
  }
  if (lineage.notes?.length) {
    assert.equal(parsed[kept.length].anchor, lineage.notes[0].anchor, "the first model note follows the kept defaults");
    assert.equal(parsed[kept.length].title, lineage.notes[0].title, "the first model note follows the kept defaults");
  }
  assert.deepEqual(parsed.map(n => n.id), Array.from({ length: expected }, (_, i) => i + 1));
});

