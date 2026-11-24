import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { buildLibrary, buildEngine } from "../build-engine.mjs";

test("the library bundle imports without page auto-start", async () => {
  const { js, css } = await buildLibrary();
  assert.doesNotMatch(js, /addEventListener\(["']DOMContentLoaded["']/);
  assert.doesNotMatch(js, /window\.flowStudioMount\s*=/);
  assert.match(js, /SHELL_BODY_HTML/);
  assert.equal(css, readFileSync(new URL("../../src/styles.css", import.meta.url), "utf8"));
  const lib = await import("data:text/javascript," + encodeURIComponent(js));
  assert.equal(typeof lib.mount, "function");
  assert.equal(typeof lib.validateModel, "function");
  assert.equal(typeof lib.zoomAt, "function");
  assert.equal(typeof lib.elbow, "function");
  assert.match(lib.SHELL_BODY_HTML, /id="viewport"/);
});

// A Windows checkout gives shell-body.html CRLF line ends. JSON.stringify turns each CR into the text
// "\r", which normalise() cannot remove, so the committed library differed between Windows and Linux.
test("the library shell body has no carriage return on any platform", async () => {
  const { js } = await buildLibrary();
  const lib = await import("data:text/javascript," + encodeURIComponent(js));
  assert.equal(lib.SHELL_BODY_HTML.includes("\r"), false);
});

test("the committed library matches the sources", async () => {
  const normalise = text => text.replace(/\r\n/g, "\n");
  const { js } = await buildLibrary();
  const committed = normalise(readFileSync(new URL("../../templates/flow-studio.lib.mjs", import.meta.url), "utf8"));
  assert.equal(committed, js, "run: node --experimental-strip-types scripts/build-engine.mjs --lib");
});

test("page build includes the shared shell body once", async () => {
  const normalise = text => text.replace(/\r\n/g, "\n");
  const body = readFileSync(new URL("../../templates/shell-body.html", import.meta.url), "utf8");
  const page = await buildEngine();
  assert.ok(normalise(page).includes(normalise(body)));
  assert.equal(page.split('id="viewport"').length - 1, 1);
});
