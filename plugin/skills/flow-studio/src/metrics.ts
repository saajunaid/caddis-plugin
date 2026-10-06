import type { NodeMetric } from "./model.ts";
import { esc } from "./model.ts";

export function sparklinePoints(series: number[], width: number, height: number): string {
  if (!Array.isArray(series) || series.length < 2 || series.some(v => !Number.isFinite(v))) return "";
  const min = Math.min(...series), max = Math.max(...series), span = max - min;
  return series.map((v, i) => `${Math.round(i / (series.length - 1) * width * 100) / 100},${Math.round((span ? 1 - (v - min) / span : .5) * height * 100) / 100}`).join(" ");
}

export function metricBadge(metric: NodeMetric | undefined): string {
  if (!metric) return "";
  const label = metric.label ?? "Metric";
  const valStr = esc(String(metric.value));
  const unitStr = metric.unit ? " " + esc(metric.unit) : "";
  const title = `${esc(label)}: ${valStr}${unitStr}`;
  const hasMax = metric.max != null && Number.isFinite(metric.max) && metric.max > 0;
  const pct = hasMax && Number.isFinite(metric.value)
    ? Math.max(0, Math.min(100, (metric.value / metric.max!) * 100))
    : 0;
  const bar = hasMax ? `<i style="width:${pct}%"></i>` : "";
  return `<span class="metric-badge" title="${title}">${valStr}${unitStr}${bar}</span>`;
}

export function sparkline(metric: NodeMetric | undefined, width = 56, height = 12): string {
  if (!metric?.series || metric.series.length < 2) return "";
  const points = sparklinePoints(metric.series, width, height);
  if (!points) return "";
  return `<svg class="spark" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" aria-hidden="true"><polyline points="${points}"/></svg>`;
}
