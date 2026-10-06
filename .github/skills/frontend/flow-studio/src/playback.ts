import type { LinkDef, Model, ScenarioDef, StepDef } from "./model.ts";

export interface PlannedStep { link: string; from: string; to: string; at: number; dur: number; caption: string; index: number }
export interface Plan { steps: PlannedStep[]; mode: "elapsed" | "none"; totalMs: number }

export function planScenario(model: Model, scenario: ScenarioDef): Plan {
  const source = scenario.steps ?? [];
  const mode = source.some(s => s?.at !== undefined) ? "elapsed" : "none";
  const start = source[0]?.at ?? 0;
  // One global scale keeps the relative spacing. Zero gaps cannot be scaled, so they follow the prior duration.
  const scale = mode === "elapsed" ? Math.max(1, ...source.slice(1).map((s, i) => {
    const gap = ((s?.at ?? 0) - (source[i]?.at ?? 0)) * 1000;
    return gap > 0 ? (source[i]?.dur ?? 900) / gap : 1;
  })) : 1;
  const steps: PlannedStep[] = [];
  for (let i = 0; i < source.length; i++) {
    const s = source[i];
    // A step that is not an object is a validator error (scenario-link), but the page still renders:
    // skip it and keep the original index, because the counter reads a step's at back through it.
    if (!s || typeof s !== "object") continue;
    const link = model.links.find(l => l.id === s.link);
    if (!link) continue;
    const from = model.nodes.find(n => n.id === link.from);
    const to = model.nodes.find(n => n.id === link.to);
    const dur = Number.isFinite(s.dur) && (s.dur ?? 0) > 0 ? s.dur! : 900;
    const proposed = mode === "elapsed" ? Math.max(0, ((s.at ?? 0) - start) * 1000 * scale) : 0;
    const at = steps.length === 0 ? 0 : Math.max(proposed, steps.at(-1)!.at + steps.at(-1)!.dur);
    steps.push({ link: s.link, from: from?.ref ?? link.from, to: to?.ref ?? link.to, at, dur, caption: s.caption ?? `${from?.title ?? link.from} to ${to?.title ?? link.to}`, index: i });
  }
  return { steps, mode, totalMs: steps.length ? steps.at(-1)!.at + steps.at(-1)!.dur : 0 };
}

export function positionAt(plan: Plan, tMs: number): { stepIndex: number; progress: number; done: boolean } {
  if (!plan.steps.length) return { stepIndex: -1, progress: 0, done: true };
  const t = Number.isNaN(tMs) ? 0 : Math.max(0, tMs);
  if (t >= plan.totalMs) return { stepIndex: plan.steps.length - 1, progress: 1, done: true };
  let i = plan.steps.length - 1;
  while (i > 0 && t < plan.steps[i]!.at) i--;
  const s = plan.steps[i]!;
  return { stepIndex: i, progress: Math.max(0, Math.min(1, (t - s.at) / s.dur)), done: false };
}

export function slaState(elapsedSec: number, sla: number): "ok" | "warn" | "breach" {
  if (elapsedSec >= sla) return "breach";
  return elapsedSec >= sla * .8 ? "warn" : "ok";
}

export function formatElapsed(sec: number): string {
  const n = Math.max(0, Math.round(Number.isFinite(sec) ? sec : 0));
  const m = Math.floor(n / 60), s = String(n % 60).padStart(2, "0");
  return n < 3600 ? `${m}:${s}` : `${Math.floor(n / 3600)}:${String(m % 60).padStart(2, "0")}:${s}`;
}

export function exitsOf(model: Model, nodeId: string): LinkDef[] {
  const canon = (id: string) => model.nodes.find(n => n.id === id)?.ref ?? id;
  return model.links.filter(l => canon(l.from) === canon(nodeId));
}

export function suggestedExit(exits: LinkDef[], nextLink: string | undefined): LinkDef | undefined {
  return exits.find(l => l.id === nextLink);
}

export function buildManualRoute(model: Model, choiceLink: LinkDef): LinkDef[] {
  const route = [choiceLink];
  const seen = new Set([choiceLink.id]);
  let at = choiceLink.to;
  while (exitsOf(model, at).length === 1) {
    const next = exitsOf(model, at)[0]!;
    if (seen.has(next.id)) break;
    route.push(next);
    seen.add(next.id);
    at = next.to;
  }
  return route;
}

export function extendScenarioWithRoute(
  scenario: ScenarioDef,
  plan: Plan,
  stepIndex: number,
  route: LinkDef[]
): ScenarioDef {
  const isElapsed = plan.mode === "elapsed" || scenario.steps.some(s => s?.at !== undefined);
  const prefix: StepDef[] = scenario.steps.slice(0, stepIndex + 1).map(s => ({ ...s }));
  for (let i = prefix.length; i <= stepIndex && i < plan.steps.length; i++) {
    const ps = plan.steps[i]!;
    prefix.push({ link: ps.link, dur: ps.dur, caption: ps.caption });
  }
  let lastAt = 0;
  if (isElapsed) {
    const lastWithAt = [...prefix].reverse().find(s => s?.at !== undefined);
    lastAt = lastWithAt?.at ?? 0;
  }
  const newSteps: StepDef[] = route.map(l => {
    const step: StepDef = { link: l.id };
    if (isElapsed) {
      lastAt += 1;
      step.at = lastAt;
    }
    return step;
  });
  return {
    ...scenario,
    steps: [...prefix, ...newSteps],
  };
}
