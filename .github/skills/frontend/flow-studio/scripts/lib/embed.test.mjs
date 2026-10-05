import { test } from "node:test";
import assert from "node:assert/strict";
import { escapeJson, embedModel } from "./embed.mjs";

const hostile = { t: "</script><script>window.pwned=1</script>", u: "<img src=x onerror=alert(1)>", q: `"'&`, ls: "a\u2028b\u2029c" };

test("escapeJson leaves no markup characters and round-trips", () => {
  const s = escapeJson(hostile);
  assert.ok(!/[<>&\u2028\u2029]/.test(s));
  assert.deepEqual(JSON.parse(s), hostile);
});

test("embedModel fills both slots and adds no script tag", () => {
  const shell = `<script id="m" type="application/json">/*__MODEL__*/{}</script><script id="n" type="application/json">/*__NOTES__*/[]</script>`;
  const out = embedModel(shell, hostile, [{ anchor: "#x", title: "<b>", text: "</script>" }]);
  assert.equal((out.match(/<\/script>/g) ?? []).length, 2);
  assert.equal((out.match(/<script/g) ?? []).length, 2);
  assert.ok(!out.includes("/*__MODEL__*/") && !out.includes("/*__NOTES__*/"));
});

test("a dollar sign in the model is not treated as a replacement pattern", () => {
  const shell = `<script>/*__MODEL__*/{}</script><script>/*__NOTES__*/[]</script>`;
  const out = embedModel(shell, { p: "$1 and $$ and $` and $'" }, []);
  assert.ok(out.includes("$1 and $$ and $` and $'"));
});

test("embedModel refuses a shell without the slots", () => {
  assert.throws(() => embedModel("<html></html>", {}, []), /slot/i);
});
