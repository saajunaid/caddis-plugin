import { on, sv, type Ctx } from "./ctx.ts";
import { buildManualRoute, extendScenarioWithRoute, exitsOf, formatElapsed, planScenario, positionAt, slaState, suggestedExit, type Plan, type PlannedStep } from "./playback.ts";
import type { ScenarioDef } from "./model.ts";

export interface PlaybackController {
  play(id?: string): void;
  pause(): void;
  step(): void;
  seek(t: number): void;
  playback(): { scenario: string | null; step: number; playing: boolean; t: number };
  restore(state: ReturnType<PlaybackController["playback"]>): void;
  reset(): void;
}

export function install(ctx: Ctx): PlaybackController {
  const e = ctx.els;
  const scenarios = ctx.model.scenarios ?? [];
  e.playbar.hidden = !scenarios.length;
  e.pbScenario.replaceChildren(...scenarios.map(s => { const o = document.createElement("option"); o.value = s.id; o.textContent = s.label; return o; }));
  let scenario: ScenarioDef | undefined = scenarios[0];
  let plan: Plan = scenario ? planScenario(ctx.model, scenario) : { steps: [], mode: "none", totalMs: 0 };
  let t = 0, idx = -1, playing = false, frame = 0, timer = 0, stamp = 0, choicesKey = "";
  // Only the elements marked in the last draw are cleared again, so a frame does not walk the whole graph.
  let markedEdges: SVGPathElement[] = [];
  let markedNodes: HTMLElement[] = [];
  const token = sv("circle", { id: "token", class: "token", r: "4" }) as SVGCircleElement;
  e.layer.appendChild(token);
  const pathOf = (link: string): SVGPathElement | undefined => ctx.edgeEls[ctx.links.findIndex(l => l.id === link)];
  const nodeOf = (id: string) => ctx.nodeEls.get(id);
  const clearMarks = () => {
    for (const p of markedEdges) p.classList.remove("playing", "visited");
    for (const n of markedNodes) n.classList.remove("playing", "visited");
    markedEdges = []; markedNodes = [];
  };
  function stop(): void {
    playing = false; cancelAnimationFrame(frame); clearTimeout(timer);
    document.body.classList.remove("playing");
    e.pbPlay.setAttribute("aria-label", "Play"); e.pbPlay.textContent = "▶";
  }
  function pause(): void {
    if (!playing) return;
    stop();
    // Redraw with playing false, so the branch buttons of the step we paused on come back.
    const p = positionAt(plan, t);
    draw(p.stepIndex, ctx.reduced ? 1 : p.progress);
  }
  function choices(step: PlannedStep | undefined): void {
    if (playing || !step) {
      // Hidden while playing; clear once, then leave the container alone for the rest of the frames.
      if (choicesKey !== "") { e.pbChoices.replaceChildren(); choicesKey = ""; }
      return;
    }
    const key = `${scenario?.id ?? ""}|${idx}|${plan.steps.length}|${plan.steps[idx + 1]?.link ?? ""}`;
    if (key === choicesKey) return;
    choicesKey = key;
    e.pbChoices.replaceChildren();
    const exits = exitsOf(ctx.model, step.to);
    if (exits.length < 2) return;
    const suggested = suggestedExit(exits, plan.steps[idx + 1]?.link);
    for (const link of exits) {
      const b = document.createElement("button"); b.type = "button";
      b.textContent = link.label ?? ctx.nodes.get(link.to)?.title ?? link.to;
      b.dataset.link = link.id;
      if (link.id === suggested?.id) b.classList.add("suggested");
      b.addEventListener("click", () => {
        // A plan step exists only when a scenario does, so scenario is set here.
        if (!scenario) return;
        const route = buildManualRoute(ctx.model, link);
        scenario = extendScenarioWithRoute(scenario, plan, idx, route);
        plan = planScenario(ctx.model, scenario);
        t = plan.steps[idx + 1]?.at ?? 0;
        play();
      });
      e.pbChoices.appendChild(b);
    }
  }
  function draw(stepIndex: number, progress: number): void {
    const step = plan.steps[stepIndex];
    clearMarks();
    if (!step) { token.style.display = "none"; return; }
    token.style.display = "";
    for (let i = 0; i < stepIndex; i++) {
      const s = plan.steps[i]!;
      const p = pathOf(s.link);
      if (p) { p.classList.add("visited"); markedEdges.push(p); }
      const n = nodeOf(s.to);
      if (n) { n.classList.add("visited"); markedNodes.push(n); }
    }
    const path = pathOf(step.link);
    if (path) { path.classList.add("playing"); markedEdges.push(path); }
    const node = nodeOf(step.to);
    if (node) { node.classList.add("playing"); markedNodes.push(node); }
    if (path && !path.classList.contains("off")) {
      const p = path.getPointAtLength(path.getTotalLength() * progress);
      token.setAttribute("cx", String(p.x)); token.setAttribute("cy", String(p.y));
    } else token.style.display = "none";
    e.pbCaption.textContent = step.caption;
    e.pbScrub.value = String(plan.totalMs ? Math.round(t / plan.totalMs * 1000) : 0);
    e.pbScrub.setAttribute("aria-valuetext", `Step ${stepIndex + 1} of ${plan.steps.length}: ${step.caption}`);
    e.pbCounter.className = "";
    e.pbCounter.hidden = plan.mode === "none";
    if (plan.mode === "elapsed") {
      const sec = scenario?.steps[step.index]?.at ?? 0;
      const sla = ctx.nodes.get(step.to)?.sla;
      e.pbCounter.textContent = sla === undefined ? formatElapsed(sec) : `${formatElapsed(sec)} / ${formatElapsed(sla)}`;
      if (sla !== undefined) e.pbCounter.classList.add(slaState(sec, sla));
    }
    if (idx !== stepIndex) ctx.fn.announce(step.caption);
    idx = stepIndex;
    choices(step);
  }
  function rewind(): void {
    stop(); t = 0; idx = -1; clearMarks(); choicesKey = "";
    e.pbCaption.textContent = "";
    e.pbCounter.hidden = true; e.pbCounter.className = "";
    e.pbChoices.replaceChildren();
    token.style.display = "none";
    e.pbScrub.value = "0"; e.pbScrub.setAttribute("aria-valuetext", "");
  }
  function select(id: string): void {
    scenario = scenarios.find(s => s.id === id) ?? scenarios[0];
    plan = scenario ? planScenario(ctx.model, scenario) : { steps: [], mode: "none", totalMs: 0 };
    e.pbScenario.value = scenario?.id ?? "";
    rewind();
  }
  function seek(value: number): void {
    stop(); t = Math.max(0, Math.min(plan.totalMs, Number.isFinite(value) ? value : 0));
    const p = positionAt(plan, t); draw(p.stepIndex, ctx.reduced ? 1 : p.progress);
  }
  function tick(now: number): void {
    if (!playing) return;
    if (!stamp) stamp = now;
    const delta = (now - stamp) * Number(e.pbSpeed.value || 1); stamp = now;
    t = Math.min(plan.totalMs, t + delta);
    const p = positionAt(plan, t);
    if (p.done) { stop(); draw(p.stepIndex, 1); return; }
    draw(p.stepIndex, p.progress);
    frame = requestAnimationFrame(tick);
  }
  function reducedStep(): void {
    if (!playing) return;
    const next = Math.min(plan.steps.length - 1, idx + 1);
    if (next < 0) { stop(); return; }
    t = plan.steps[next]!.at + plan.steps[next]!.dur;
    // Stop before the last draw so the branch buttons of the final step are built.
    if (next === plan.steps.length - 1) stop();
    draw(next, 1);
    if (playing) timer = window.setTimeout(reducedStep, 1000 / Number(e.pbSpeed.value || 1));
  }
  function play(id?: string): void {
    if (id && id !== scenario?.id) select(id);
    // Cancel any loop already running, or two frames would advance t together.
    stop();
    if (!plan.steps.length) return;
    if (t >= plan.totalMs) { t = 0; idx = -1; }
    playing = true;
    document.body.classList.add("playing");
    e.pbPlay.setAttribute("aria-label", "Pause"); e.pbPlay.textContent = "❚❚";
    e.pbChoices.replaceChildren(); choicesKey = "";
    if (ctx.reduced) reducedStep(); else { stamp = 0; frame = requestAnimationFrame(tick); }
  }
  function step(): void {
    stop();
    const next = Math.min(idx + 1, plan.steps.length - 1);
    if (next < 0) return;
    t = plan.steps[next]!.at + plan.steps[next]!.dur;
    draw(next, 1);
  }
  on(ctx, e.pbScenario, "change", () => select(e.pbScenario.value));
  on(ctx, e.pbPlay, "click", () => playing ? pause() : play());
  on(ctx, e.pbStep, "click", step);
  // Reset rewinds the current plan (a manual branch stays); picking from the scenario list starts over.
  on(ctx, e.pbReset, "click", () => rewind());
  on(ctx, e.pbScrub, "input", () => seek(Number(e.pbScrub.value) / 1000 * plan.totalMs));
  on(ctx, document, "keydown", (event: KeyboardEvent) => {
    if (event.ctrlKey || event.metaKey || event.altKey || (event.target instanceof HTMLElement && (event.target.isContentEditable || /INPUT|TEXTAREA|SELECT/.test(event.target.tagName)))) return;
    if (event.key.toLowerCase() === "p") { event.preventDefault(); playing ? pause() : play(); }
    if (event.key === ".") { event.preventDefault(); step(); }
  });
  ctx.disposers.push(() => { stop(); token.remove(); });
  select(scenario?.id ?? "");
  return { play, pause, step, seek, playback: () => ({ scenario: scenario?.id ?? null, step: idx, playing, t }),
    restore: state => {
      if (!state.scenario || !scenarios.some(s => s.id === state.scenario)) return;
      select(state.scenario);
      const current = plan.steps[state.step];
      if (!current) return;
      t = Math.max(current.at, Math.min(current.at + current.dur, state.t));
      draw(state.step, ctx.reduced ? 1 : current.dur > 0 ? (t - current.at) / current.dur : 1);
      if (state.playing) play();
    },
    reset: () => rewind() };
}
