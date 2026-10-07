import { test } from "node:test";
import assert from "node:assert/strict";
import { barsHtml, markKey } from "./bars.ts";
import { validateModel, type Model, type NodeBar } from "./model.ts";

const bars: NodeBar[] = [
  { key: "2026-09-01", value: 10 },
  { key: "2026-09-02", value: null },
  { key: "2026-09-03", value: 4, kind: "low" },
  { key: "2026-09-04", value: 20 },
];

test("no bars, no chart", () => {
  assert.equal(barsHtml(undefined), "");
  assert.equal(barsHtml([]), "");
});

test("one rect per bar, each carrying its key; a missing day is a short red tick, never a zero bar", () => {
  const html = barsHtml(bars);
  assert.equal((html.match(/<rect /g) ?? []).length, 4);
  for (const b of bars) assert.match(html, new RegExp(`data-key="${b.key}"`));
  assert.match(html, /<rect class="miss" data-key="2026-09-02"/);
  assert.match(html, /<rect class="low" data-key="2026-09-03"/);
  // The last bar with data is the accent one.
  assert.match(html, /<rect class="last" data-key="2026-09-04"/);
});

test("bar height follows the value against the largest, and the largest fills the chart", () => {
  const html = barsHtml([{ key: "a", value: 5 }, { key: "b", value: 10 }], 20);
  const heights = [...html.matchAll(/height="([0-9.]+)"/g)].map(m => Number(m[1])).filter(h => h < 20);
  assert.equal(heights.length, 2);
  assert.ok(Math.abs(heights[1]! - 15) < 0.01, "the largest bar is height - 5");
  assert.ok(Math.abs(heights[0]! - 7.5) < 0.01, "half the value is half the height");
});

test("keys and labels are escaped, so a hostile key cannot become markup", () => {
  const html = barsHtml([{ key: '"><script>x</script>', value: 1, label: "<b>" }]);
  assert.doesNotMatch(html, /<script>/);
  assert.doesNotMatch(html, /<b>/);
  assert.match(html, /&lt;b&gt;/);
});

test("the chart is described for a screen reader", () => {
  assert.match(barsHtml(bars), /role="img" aria-label="[^"]+"/);
});

interface FakeRect { key: string; attrs: Map<string, string>; getAttribute(n: string): string | null; setAttribute(n: string, v: string): void; removeAttribute(n: string): void }
const fakeRect = (key: string): FakeRect => {
  const attrs = new Map<string, string>([["data-key", key]]);
  return { key, attrs, getAttribute: n => attrs.get(n) ?? null, setAttribute: (n, v) => void attrs.set(n, v), removeAttribute: n => void attrs.delete(n) };
};

test("markKey marks every bar with that key, on every chart, and clears the others", () => {
  const rects = [fakeRect("a"), fakeRect("b"), fakeRect("a")];
  const root = { querySelectorAll: () => rects } as unknown as ParentNode;
  markKey(root, "a");
  assert.deepEqual(rects.map(r => r.attrs.get("data-hl")), ["true", undefined, "true"]);
  markKey(root, "b");
  assert.deepEqual(rects.map(r => r.attrs.get("data-hl")), [undefined, "true", undefined]);
  markKey(root, null);
  assert.deepEqual(rects.map(r => r.attrs.get("data-hl")), [undefined, undefined, undefined]);
});

const base = (): Model => ({
  version: 1,
  meta: { title: "T", help: "h", asOf: "2026-01-01", source: "s" },
  layout: "columns-lanes",
  columns: [{ id: "c0", title: "A", width: 150 }],
  lanes: [{ id: "l1", title: "Lane 1" }],
  states: { ok: { word: "OK", tone: "ok", border: "solid", edge: "flow", motion: "flow", bucket: "good" } },
  nodes: [{ id: "a", kind: "card", lane: "l1", col: 0, row: 0, state: "ok", title: "A", allowIsolated: true, bars }],
  links: [],
});
const codes = (m: unknown) => validateModel(m).filter(i => i.level === "error").map(i => i.code);

test("a node may carry bars", () => assert.deepEqual(codes(base()), []));
test("bars must be a list", () => {
  const m = base(); (m.nodes[0] as unknown as { bars: unknown }).bars = "nope";
  assert.ok(codes(m).includes("bars-invalid"));
});
test("each bar needs a string key and a finite, non-negative value or null", () => {
  for (const bad of [{ key: 1, value: 1 }, { key: "k", value: -1 }, { key: "k", value: Number.NaN }, { key: "k", value: "3" }, null]) {
    const m = base(); (m.nodes[0] as unknown as { bars: unknown[] }).bars = [bad];
    assert.ok(codes(m).includes("bars-invalid"), JSON.stringify(bad));
  }
});
test("at most 120 bars", () => {
  const m = base(); m.nodes[0]!.bars = Array.from({ length: 121 }, (_, i) => ({ key: String(i), value: 1 }));
  assert.ok(codes(m).includes("bars-invalid"));
});
