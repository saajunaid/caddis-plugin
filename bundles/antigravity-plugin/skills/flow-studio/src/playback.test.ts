import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { planScenario, positionAt, slaState, formatElapsed, exitsOf, suggestedExit, buildManualRoute, extendScenarioWithRoute } from "./playback.ts";
import { validateModel, type Model, type ScenarioDef, type StepDef } from "./model.ts";

const model = JSON.parse(readFileSync(new URL("../examples/order-desk.json", import.meta.url), "utf8")) as Model;
const steps = [{ link: "l-intake-verify" }, { link: "l-verify-route", dur: 400 }];
test("untimed playback is sequential and clamped", () => {
  const p = planScenario(model, { id: "a", label: "A", steps });
  assert.equal(p.mode, "none"); assert.equal(p.totalMs, 1300);
  assert.deepEqual(p.steps.map(s => s.at), [0, 900]);
  assert.deepEqual(positionAt(p, -10), { stepIndex: 0, progress: 0, done: false });
  assert.deepEqual(positionAt(p, 900), { stepIndex: 1, progress: 0, done: false });
  assert.deepEqual(positionAt(p, Infinity), { stepIndex: 1, progress: 1, done: true });
});
test("elapsed playback scales the shortest gap and handles empty plans", () => {
  const p = planScenario(model, { id: "a", label: "A", steps: [{ link: "l-intake-verify", at: 2 }, { link: "l-verify-route", at: 2.2 }] });
  assert.equal(p.mode, "elapsed"); assert.equal(p.steps[1]?.at, 900);
  assert.equal(p.steps[0]?.caption, "New request to Verify details");
  const empty = planScenario(model, { id: "x", label: "X", steps: [] });
  assert.deepEqual(positionAt(empty, 0), { stepIndex: -1, progress: 0, done: true });
  const one = planScenario(model, { id: "one", label: "One", steps: [{ link: "l-intake-verify", at: 0 }] });
  assert.equal(one.totalMs, 900);
  assert.deepEqual(positionAt(one, NaN), { stepIndex: 0, progress: 0, done: false });
  assert.deepEqual(positionAt(one, 900), { stepIndex: 0, progress: 1, done: true });
});
test("time and branches have stable boundaries", () => {
  assert.equal(slaState(79.9, 100), "ok"); assert.equal(slaState(80, 100), "warn"); assert.equal(slaState(100, 100), "breach");
  assert.equal(formatElapsed(59.6), "1:00"); assert.equal(formatElapsed(3600), "1:00:00");
  assert.deepEqual(exitsOf(model, "route").map(l => l.id), ["l-route-hold", "l-route-quote"]);
  assert.equal(suggestedExit(exitsOf(model, "route"), "l-route-quote")?.id, "l-route-quote");
});
test("validator reports scenario and metric errors", () => {
  const m = structuredClone(model);
  m.scenarios = [{ id: "a", label: "A", steps: [{ link: "missing", at: 2 }, { link: "l-intake-verify" }] }, { id: "a", label: "B", steps: [] }];
  m.nodes[0]!.metrics = { value: NaN, series: Array(61).fill(0) };
  const codes = validateModel(m).map(i => i.code);
  for (const c of ["scenario-duplicate", "scenario-empty", "scenario-link", "scenario-at-partial", "metric-invalid"]) assert.ok(codes.includes(c), c);
});
test("validator warns for disconnected steps and rejects decreasing time", () => {
  const m = structuredClone(model);
  m.scenarios = [{ id: "gap", label: "Gap", steps: [{ link: "l-intake-verify", at: 10 }, { link: "l-route-quote", at: 9 }] }];
  const codes = validateModel(m).map(i => i.code);
  assert.ok(codes.includes("scenario-at-order"));
  assert.ok(codes.includes("scenario-gap"));
});
test("validator catches decreasing time even when intermediate step has NaN at", () => {
  const m = structuredClone(model);
  m.scenarios = [{
    id: "nan-order", label: "NaN Order",
    steps: [
      { link: "l-intake-verify", at: 10 },
      { link: "l-verify-route", at: NaN },
      { link: "l-route-quote", at: 5 },
    ],
  }];
  const issues = validateModel(m).filter(i => i.code === "scenario-at-order");
  assert.equal(issues.length, 2, "Both step with NaN and step with decreasing time should report scenario-at-order");
});
test("buildManualRoute and extendScenarioWithRoute preserve manual branches and elapsed timing", () => {
  const choiceLink = model.links.find(l => l.id === "l-route-hold")!;
  const route = buildManualRoute(model, choiceLink);
  assert.deepEqual(route.map(l => l.id), ["l-route-hold", "l-hold-verify", "l-verify-route"]);

  const initialScenario = model.scenarios?.[0]!;
  const plan1 = planScenario(model, initialScenario);
  // User at step 1 (gateway 'route') chooses 'l-route-hold'
  const manual1 = extendScenarioWithRoute(initialScenario, plan1, 1, route);
  assert.equal(manual1.steps.length, 5);
  assert.equal(manual1.steps[2].link, "l-route-hold");
  assert.equal(manual1.steps[3].link, "l-hold-verify");
  assert.equal(manual1.steps[4].link, "l-verify-route");
  assert.ok(manual1.steps[2].at! > manual1.steps[1].at!);
  assert.ok(manual1.steps[3].at! > manual1.steps[2].at!);
  assert.ok(manual1.steps[4].at! > manual1.steps[3].at!);

  const plan2 = planScenario(model, manual1);
  assert.equal(plan2.mode, "elapsed");

  // Subsequent manual choice from the new branch must NOT drop earlier manual steps
  const route2 = [model.links.find(l => l.id === "l-route-quote")!];
  const manual2 = extendScenarioWithRoute(manual1, plan2, 4, route2);
  assert.equal(manual2.steps.length, 6);
  assert.deepEqual(manual2.steps.map(s => s.link), [
    initialScenario.steps[0].link,
    initialScenario.steps[1].link,
    "l-route-hold",
    "l-hold-verify",
    "l-verify-route",
    "l-route-quote",
  ]);
  assert.ok(manual2.steps[5].at! > manual2.steps[4].at!);
});
test("a scenario with malformed steps plans without throwing and keeps indices aligned", () => {
  // The validator reports a null step (scenario-link) but the page still renders, so playback must not throw on it.
  const sc = { id: "n", label: "N", steps: [{ link: "l-intake-verify", at: 0 }, null as unknown as StepDef, { link: "l-verify-route", at: 5 }] } as unknown as ScenarioDef;
  const plan = planScenario(model, sc);
  assert.deepEqual(plan.steps.map(s => [s.link, s.index]), [["l-intake-verify", 0], ["l-verify-route", 2]]);
  // The counter reads a scenario step's at through the plan step's index, so the index must stay the original one.
  assert.equal(sc.steps[2]!.at, 5);
  const ext = extendScenarioWithRoute(sc, plan, 1, [model.links.find(l => l.id === "l-route-hold")!]);
  assert.doesNotThrow(() => planScenario(model, ext));
});
