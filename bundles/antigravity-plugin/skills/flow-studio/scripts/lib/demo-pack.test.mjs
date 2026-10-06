import { test } from "node:test";
import assert from "node:assert/strict";
import { keepDefaultNotes } from "./demo-pack.mjs";

// The shell here is a fixture, not the real engine.html: the filter only reads id attributes.
const shell = '<div id="q"></div><span data-id="title"></span><i id="qxy"></i><section id="playbar"></section><nav id="modeSwitch"></nav>';
const note = anchor => ({ anchor, title: anchor, text: "t" });

test("demo-pack: keeps a default note whose id exists in the shell", () => {
  assert.equal(keepDefaultNotes([note("#q")], {}, shell).length, 1);
});

test("demo-pack: drops a default note whose id is missing; a data-id substring is not an id", () => {
  assert.deepEqual(keepDefaultNotes([note("#title")], {}, shell), []);
});

test("demo-pack: does not treat regex metacharacters in an id as a pattern", () => {
  // "qx+y" read as a regular expression would match the shell's id="qxy"; read as an id it must not.
  assert.deepEqual(keepDefaultNotes([note("#qx+y")], {}, shell), []);
});

test("demo-pack: drops #playbar without scenarios and keeps it with at least one", () => {
  assert.deepEqual(keepDefaultNotes([note("#playbar")], {}, shell), []);
  assert.equal(keepDefaultNotes([note("#playbar")], { scenarios: [{ id: "s1", steps: [{ link: "l1" }] }] }, shell).length, 1);
});

test("demo-pack: drops #modeSwitch with fewer than two views and keeps it with two", () => {
  assert.deepEqual(keepDefaultNotes([note("#modeSwitch")], { views: [{ id: "v1", label: "V" }] }, shell), []);
  assert.equal(keepDefaultNotes([note("#modeSwitch")], { views: [{ id: "v1", label: "V" }, { id: "v2", label: "W" }] }, shell).length, 1);
});

test("demo-pack: leaves anchors that are not ids (class and attribute selectors) unfiltered", () => {
  assert.equal(keepDefaultNotes([note(".anything"), note("[data-x='y']")], {}, shell).length, 2);
});
