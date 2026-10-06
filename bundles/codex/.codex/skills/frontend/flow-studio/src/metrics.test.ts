import { test } from "node:test";
import assert from "node:assert/strict";
import { sparklinePoints, metricBadge, sparkline } from "./metrics.ts";

test("sparkline handles flat, missing and varied series", () => {
  assert.equal(sparklinePoints([], 56, 12), "");
  assert.equal(sparklinePoints([4, 4], 56, 12), "0,6 56,6");
  assert.equal(sparklinePoints([0, 10], 56, 12), "0,12 56,0");
});

test("metricBadge renders value, unit, and consistent title", () => {
  assert.equal(metricBadge(undefined), "");
  const badge1 = metricBadge({ value: 92, unit: "ms", label: "Hit rate" });
  assert.ok(badge1.includes('title="Hit rate: 92 ms"'), "Title includes label, value and unit");
  assert.ok(badge1.includes(">92 ms"), "Badge body includes value and unit");
  assert.ok(!badge1.includes("<i"), "No fill bar when max is omitted");
});

test("metricBadge renders clamped fill bar when max is valid, ignores invalid max", () => {
  const withMax = metricBadge({ value: 50, max: 100, label: "CPU" });
  assert.ok(withMax.includes('<i style="width:50%"></i>'));

  const clamped = metricBadge({ value: 150, max: 100 });
  assert.ok(clamped.includes('<i style="width:100%"></i>'));

  const negativeVal = metricBadge({ value: -10, max: 100 });
  assert.ok(negativeVal.includes('<i style="width:0%"></i>'));

  const nullMax = metricBadge({ value: 50, max: null as any });
  assert.ok(!nullMax.includes("<i"), "null max produces no bar");

  const zeroMax = metricBadge({ value: 50, max: 0 });
  assert.ok(!zeroMax.includes("<i"), "zero max produces no bar");
});

test("metricBadge escapes special HTML characters", () => {
  const hostile = metricBadge({ value: 1, unit: '<script>"&', label: '<tag>&"' });
  assert.ok(!hostile.includes("<script>"));
  assert.ok(!hostile.includes("<tag>"));
  assert.ok(hostile.includes("&lt;script&gt;"));
  assert.ok(hostile.includes("&lt;tag&gt;"));
});
test("metricBadge escapes quotes so nothing can break out of the title attribute", () => {
  // label and unit land inside title="…": a raw quote there would open attacker-controlled attributes.
  const hostile = metricBadge({ value: 1, unit: '">&x', label: 'y" onmouseover="z' });
  assert.ok(hostile.includes('title="y&quot; onmouseover=&quot;z: 1 &quot;&gt;&amp;x"'));
});

test("sparkline renders accessible SVG with aria-hidden", () => {
  assert.equal(sparkline(undefined), "");
  assert.equal(sparkline({ value: 10 }), "");
  assert.equal(sparkline({ value: 10, series: [1] }), "");

  const svg = sparkline({ value: 10, series: [2, 8] }, 56, 12);
  assert.ok(svg.startsWith('<svg class="spark" width="56" height="12" viewBox="0 0 56 12" aria-hidden="true">'));
  assert.ok(svg.includes('<polyline points="0,12 56,0"/>'));
});
