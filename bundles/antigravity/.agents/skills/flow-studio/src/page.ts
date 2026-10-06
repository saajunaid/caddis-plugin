import { mount } from "./engine.ts";
import type { Model, NoteDef } from "./model.ts";

function auto(): void {
  const m = document.getElementById("flow-model");
  if (!m) return;
  try {
    const model = JSON.parse(m.textContent ?? "{}") as Model;
    const n = document.getElementById("flow-notes");
    const notes = n ? (JSON.parse(n.textContent ?? "[]") as NoteDef[]) : undefined;
    mount(document, model, { notes });
  } catch (e) {
    console.error(e);
    const h = document.getElementById("help");
    if (h) h.textContent = "This page could not be drawn: " + (e instanceof Error ? e.message : String(e));
  }
}

window.flowStudioMount = mount;
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", auto);
else auto();
