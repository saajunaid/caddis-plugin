import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { mount } from "./engine.ts";
import type { Model } from "./model.ts";

const here = dirname(fileURLToPath(import.meta.url));
const skillRoot = resolve(here, "..");
const shellHtml = readFileSync(join(skillRoot, "templates/shell-body.html"), "utf8");

function loadJsdom() {
  const configured = process.env.FLOW_STUDIO_NODE_MODULES;
  const candidates = [
    ...(configured ? [resolve(configured, ".."), configured] : []),
    skillRoot,
    resolve(skillRoot, "../../../../cli"),
    process.cwd(),
  ];
  for (const dir of candidates) {
    if (!existsSync(dir)) continue;
    try {
      return createRequire(join(dir, "package.json"))("jsdom");
    } catch {
      try { return createRequire(join(dir, "x.js"))("jsdom"); } catch { /* next */ }
    }
  }
  throw new Error("jsdom was not found. Set FLOW_STUDIO_NODE_MODULES or run `npm ci` in cli/.");
}

function setupDom() {
  const { JSDOM } = loadJsdom();
  const dom = new JSDOM("<!doctype html><html><head></head><body></body></html>", {
    url: "http://localhost/",
    pretendToBeVisual: true,
  });
  const { window } = dom;
  const win = window as unknown as Record<string, unknown>;
  win.matchMedia = () => ({
    matches: false,
    media: "",
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  });
  win.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  win.CSS = { escape: (s: string) => s.replace(/[^a-zA-Z0-9_-]/g, "\\$&") };
  win.scrollTo = () => {};
  const svgProto = (window as unknown as { SVGElement: { prototype: Record<string, unknown> } }).SVGElement.prototype;
  svgProto.getTotalLength = () => 100;
  svgProto.getPointAtLength = (d: number) => ({ x: d, y: 0 });
  (window.HTMLElement.prototype as unknown as Record<string, unknown>).scrollIntoView = () => {};

  const keys = [
    "window", "document", "Document", "Node", "Element", "HTMLElement", "HTMLInputElement",
    "HTMLSelectElement", "HTMLButtonElement", "HTMLDetailsElement", "HTMLStyleElement",
    "SVGElement", "SVGSVGElement", "SVGGElement", "SVGPathElement", "SVGCircleElement",
    "Event", "MouseEvent", "KeyboardEvent", "FocusEvent", "WheelEvent",
    "matchMedia", "ResizeObserver", "CSS", "requestAnimationFrame", "cancelAnimationFrame",
    "getComputedStyle", "scrollX", "scrollY",
  ];
  const prev = new Map<string, PropertyDescriptor | undefined>();
  for (const k of keys) {
    prev.set(k, Object.getOwnPropertyDescriptor(globalThis, k));
    Object.defineProperty(globalThis, k, { value: win[k], configurable: true, writable: true });
  }
  return {
    dom,
    restore() {
      for (const [k, desc] of prev) {
        if (desc) Object.defineProperty(globalThis, k, desc);
        else delete (globalThis as Record<string, unknown>)[k];
      }
      dom.window.close();
    },
  };
}

function makeModel(): Model {
  return {
    version: 1,
    meta: { title: "Scoped Test", help: "h", asOf: "2026-11-25", source: "s" },
    layout: "columns-lanes",
    columns: [
      { id: "c0", title: "Stage 1", width: 160 },
      { id: "c1", title: "Stage 2", width: 160 },
      { id: "c2", title: "Stage 3", width: 160 },
    ],
    lanes: [{ id: "l1", title: "Lane 1" }],
    states: {
      ok: { word: "OK", tone: "ok", border: "solid", edge: "flow", motion: "flow", bucket: "good" },
    },
    nodes: [
      { id: "a", kind: "card", lane: "l1", col: 0, row: 0, state: "ok", title: "Node A" },
      { id: "b", kind: "card", lane: "l1", col: 1, row: 0, state: "ok", title: "Node B" },
      { id: "c", kind: "card", lane: "l1", col: 2, row: 0, state: "ok", title: "Node C", visibleIn: ["v2"] },
    ],
    links: [
      { id: "ab", from: "a", to: "b", state: "ok" },
      { id: "bc", from: "b", to: "c", state: "ok" },
    ],
    views: [
      { id: "v1", label: "Baseline", default: true },
      { id: "v2", label: "Expanded" },
    ],
    scenarios: [
      {
        id: "s1",
        label: "Run",
        steps: [
          { link: "ab", at: 0, dur: 1000, caption: "A to B" },
          { link: "bc", at: 10, dur: 1000, caption: "B to C" },
        ],
      },
    ],
    notes: [{ anchor: "#viewport", title: "Canvas note", text: "Explains the canvas." }],
  };
}

const rect = (left: number, top: number, width: number, height: number): DOMRect => ({
  x: left, y: top, left, top, width, height, right: left + width, bottom: top + height, toJSON: () => ({}),
});

test("mount into a div adds fs-root, scopes state classes & markers to the host, leaves page body untouched, and cleans up on destroy", async () => {
  const env = setupDom();
  try {
    const { body } = document;
    body.className = "host-app-body";
    const host = document.createElement("div");
    host.innerHTML = shellHtml;
    body.appendChild(host);
    host.getBoundingClientRect = () => rect(40, 30, 1000, 700);
    const vp = host.querySelector<HTMLElement>("#viewport")!;
    vp.getBoundingClientRect = () => rect(100, 80, 800, 600);

    const api = mount(host, makeModel());
    assert.equal(host.classList.contains("fs-root"), true, "host gets fs-root");
    assert.equal(host.classList.contains("intro"), true, "host gets intro on initial mount");
    assert.equal(body.className, "host-app-body", "body.className stays unchanged on mount");

    // Toggle alt view
    assert.equal(host.classList.contains("alt"), false);
    api.setMode("v2");
    assert.equal(host.classList.contains("alt"), true, "switching to non-baseline view sets alt on host");
    assert.equal(body.className, "host-app-body", "body.className unchanged after setMode");

    // Toggle playback
    api.play("s1");
    assert.equal(host.classList.contains("playing"), true, "play() sets playing on host");
    assert.equal(body.className, "host-app-body", "body.className unchanged during playback");
    api.pause();
    assert.equal(host.classList.contains("playing"), false, "pause() removes playing from host");
    api.play("s1");
    assert.equal(host.classList.contains("playing"), true);

    // Toggle notes and verify marker is a descendant of host with host-relative coordinates
    host.querySelector<HTMLButtonElement>("#notesBtn")!.click();
    assert.equal(host.classList.contains("notes"), true, "clicking notesBtn sets notes on host");
    assert.equal(body.className, "host-app-body", "body.className unchanged when notes open");

    await new Promise(r => setTimeout(r, 380));
    const markers = host.querySelectorAll<HTMLElement>(".marker");
    assert.equal(markers.length, 1, "note marker is created inside host");
    assert.equal(markers[0]!.parentElement, host, "marker is appended to host");
    assert.equal(body.querySelectorAll(":scope > .marker").length, 0, "no marker appended directly to body");
    assert.equal(markers[0]!.style.left, "50px", "marker left is host-relative (100 - 40 - 10)");
    assert.equal(markers[0]!.style.top, "40px", "marker top is host-relative (80 - 30 - 10)");

    // Destroy removes fs-root, state classes, and markers while keeping body untouched
    api.destroy();
    assert.equal(host.classList.contains("fs-root"), false, "destroy removes fs-root");
    for (const cls of ["intro", "notes", "playing", "alt"]) {
      assert.equal(host.classList.contains(cls), false, `destroy removes state class ${cls}`);
    }
    assert.equal(host.querySelectorAll(".marker").length, 0, "destroy removes note markers");
    assert.equal(body.className, "host-app-body", "body.className remains untouched after destroy");
  } finally {
    env.restore();
  }
});

test("two mounts on one page keep independent state classes and markers", async () => {
  const env = setupDom();
  try {
    const { body } = document;
    body.className = "shared-page";
    const hostA = document.createElement("div");
    const hostB = document.createElement("div");
    hostA.innerHTML = shellHtml;
    hostB.innerHTML = shellHtml;
    body.append(hostA, hostB);
    hostA.getBoundingClientRect = () => rect(0, 0, 800, 600);
    hostB.getBoundingClientRect = () => rect(820, 0, 800, 600);
    hostA.querySelector<HTMLElement>("#viewport")!.getBoundingClientRect = () => rect(20, 20, 700, 500);
    hostB.querySelector<HTMLElement>("#viewport")!.getBoundingClientRect = () => rect(840, 20, 700, 500);

    const apiA = mount(hostA, makeModel());
    const apiB = mount(hostB, makeModel());

    apiA.setMode("v2");
    apiA.play("s1");
    hostA.querySelector<HTMLButtonElement>("#notesBtn")!.click();
    await new Promise(r => setTimeout(r, 380));

    assert.equal(hostA.classList.contains("alt"), true);
    assert.equal(hostB.classList.contains("alt"), false, "hostB stays in baseline view");
    assert.equal(hostA.classList.contains("playing"), true);
    assert.equal(hostB.classList.contains("playing"), false, "hostB is not playing");
    assert.equal(hostA.classList.contains("notes"), true);
    assert.equal(hostB.classList.contains("notes"), false, "hostB notes stay closed");
    assert.equal(hostA.querySelectorAll(".marker").length, 1);
    assert.equal(hostB.querySelectorAll(".marker").length, 0, "hostB has no markers");
    assert.equal(body.className, "shared-page");

    // Opening and closing notes on hostB must not wipe hostA's markers
    hostB.querySelector<HTMLButtonElement>("#notesBtn")!.click();
    await new Promise(r => setTimeout(r, 380));
    assert.equal(hostB.querySelectorAll(".marker").length, 1);
    hostB.querySelector<HTMLButtonElement>("#notesBtn")!.click();
    assert.equal(hostB.querySelectorAll(".marker").length, 0);
    assert.equal(hostA.querySelectorAll(".marker").length, 1, "closing hostB notes keeps hostA markers intact");

    apiA.destroy();
    assert.equal(hostA.classList.contains("fs-root"), false);
    assert.equal(hostB.classList.contains("fs-root"), true, "destroying hostA leaves hostB mounted");
    apiB.destroy();
  } finally {
    env.restore();
  }
});
