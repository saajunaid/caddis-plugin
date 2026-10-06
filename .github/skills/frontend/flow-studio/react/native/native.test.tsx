if (typeof window !== "undefined" && typeof window.PointerEvent === "undefined") {
  class PointerEvent extends MouseEvent {
    pointerId: number;
    pointerType: string;
    constructor(type: string, params: PointerEventInit = {}) {
      super(type, params);
      this.pointerId = params.pointerId ?? 0;
      this.pointerType = params.pointerType ?? "mouse";
    }
  }
  window.PointerEvent = PointerEvent as unknown as typeof window.PointerEvent;
}
import React from "react";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { Model } from "../../src/model.ts";
import { useViewport } from "./useViewport.ts";
import { useFlowGeometry } from "./useFlowGeometry.ts";
import { FlowCanvas } from "./FlowCanvas.tsx";

const model: Model = {
  version: 1, meta: { title: "Sample", help: "", asOf: "", source: "" }, layout: "columns-lanes",
  columns: [{ id: "one", title: "One", width: 180 }, { id: "two", title: "Two", width: 180 }],
  lanes: [{ id: "lane", title: "Lane" }],
  states: { good: { word: "Ready", tone: "ok", border: "solid", edge: "flow", motion: "none", bucket: "good" } },
  nodes: [
    { id: "a", kind: "card", lane: "lane", col: 0, row: 0, state: "good", title: "Alpha" },
    { id: "b", kind: "card", lane: "lane", col: 1, row: 0, state: "good", title: "Beta" },
  ], links: [{ id: "ab", from: "a", to: "b", state: "good" }],
};

function ViewProbe() {
  const { view, bind, fit, zoomBy, zoomAboutCenter } = useViewport({ x: 0, y: 0, w: 1000, h: 500 });
  return <>
    <div data-testid="pad" {...bind} />
    <output data-testid="view">{JSON.stringify(view)}</output>
    <button onClick={() => zoomBy(2, 100, 80)}>Zoom at point</button>
    <button onClick={() => zoomAboutCenter(2)}>Zoom about center</button>
    <button onClick={() => fit()}>Fit measured</button>
    <button onClick={() => fit({ w: 500, h: 300 })}>Fit explicit</button>
  </>;
}

const view = () => JSON.parse(screen.getByTestId("view").textContent!) as { x: number; y: number; k: number };
/** jsdom reports 0 for every box; the hook must read the sizes from the attached element. */
const measure = (element: Element, w: number, h: number) => {
  Object.defineProperty(element, "clientWidth", { value: w, configurable: true });
  Object.defineProperty(element, "clientHeight", { value: h, configurable: true });
};

afterEach(cleanup);

describe("native flow viewport", () => {
  it("keeps the point below the cursor during zoom and fits given bounds", () => {
    render(<ViewProbe />);
    fireEvent.click(screen.getByText("Zoom at point"));
    expect(view()).toEqual({ x: -100, y: -80, k: 2 });
    fireEvent.click(screen.getByText("Fit explicit"));
    expect(view().k).toBeLessThan(1);
  });

  it("measures the attached element when fit() gets no size", () => {
    render(<ViewProbe />);
    measure(screen.getByTestId("pad"), 800, 400);
    fireEvent.click(screen.getByText("Fit measured"));
    expect(view().k).toBeCloseTo(0.616, 5);
    expect(view().x).toBeCloseTo(92, 5);
    expect(view().y).toBeCloseTo(68, 5);
  });

  it("zooms from a native non-passive wheel listener that can block page scroll", () => {
    render(<ViewProbe />);
    const pad = screen.getByTestId("pad");
    const wheel = new WheelEvent("wheel", { deltaY: -120, clientX: 60, clientY: 40, cancelable: true, bubbles: true });
    fireEvent(pad, wheel);
    expect(wheel.defaultPrevented).toBe(true);
    expect(view().k).toBeGreaterThan(1);
  });

  it("pans with a pointer drag and stops tracking after pointer up", () => {
    render(<ViewProbe />);
    const pad = screen.getByTestId("pad");
    // jsdom has no real pointer capture; the pan maths must not depend on it.
    if (typeof pad.setPointerCapture === "function") pad.setPointerCapture = () => {};
    if (typeof pad.releasePointerCapture === "function") pad.releasePointerCapture = () => {};
    measure(pad, 800, 400);
    fireEvent.pointerDown(pad, { button: 0, pointerId: 1, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(pad, { pointerId: 1, clientX: 150, clientY: 120 });
    expect(view()).toEqual({ x: 50, y: 20, k: 1 });
    fireEvent.pointerUp(pad, { pointerId: 1 });
    fireEvent.pointerMove(pad, { pointerId: 1, clientX: 400, clientY: 300 });
    expect(view()).toEqual({ x: 50, y: 20, k: 1 });
  });

  it("zooms with the keyboard about the measured center and fits with 0", () => {
    render(<ViewProbe />);
    const pad = screen.getByTestId("pad");
    measure(pad, 800, 400);
    fireEvent.keyDown(pad, { key: "+" });
    expect(view()).toEqual({ x: -80, y: -40, k: 1.2 });
    fireEvent.keyDown(pad, { key: "-" });
    expect(view().k).toBeCloseTo(1, 10);
    fireEvent.keyDown(pad, { key: "0" });
    expect(view().k).toBeCloseTo(0.616, 5);
  });

  it("zoomAboutCenter keeps the middle of the viewport fixed", () => {
    render(<ViewProbe />);
    measure(screen.getByTestId("pad"), 800, 400);
    fireEvent.click(screen.getByText("Zoom about center"));
    expect(view()).toEqual({ x: -400, y: -200, k: 2 });
  });

  it("reuses the geometry across renders when the collapsed default is omitted", () => {
    const seen: unknown[] = [];
    function GeometryProbe() {
      const { geometry } = useFlowGeometry(model, { x: 0, y: 0, k: 1 });
      seen.push(geometry);
      return null;
    }
    const rendered = render(<GeometryProbe />);
    rendered.rerender(<GeometryProbe />);
    rendered.rerender(<GeometryProbe />);
    expect(seen[1]).toBe(seen[0]);
    expect(seen[2]).toBe(seen[0]);
  });
});

describe("native flow canvas", () => {
  it("selects a node, traces its link, and closes the inspector with Escape", () => {
    render(<FlowCanvas model={model} renderNode={node => <span>{node.title}</span>} />);
    fireEvent.click(screen.getByRole("button", { name: "Alpha" }));
    expect(screen.getByRole("dialog").textContent).toContain("Alpha");
    expect(document.querySelector("#n_b button")?.getAttribute("data-connected")).toBe("true");
    expect(screen.getByRole("button", { name: "0 upstream nodes" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "1 downstream nodes" })).toBeTruthy();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("hides contained nodes while their group is collapsed", () => {
    const grouped: Model = { ...model, nodes: [
      { id: "g", kind: "group", lane: "lane", col: 0, row: 0, state: "good", title: "Group", contains: ["a"] },
      { ...model.nodes[0]!, row: 1 }, model.nodes[1]!,
    ] };
    render(<FlowCanvas model={grouped} renderNode={node => <span>{node.title}</span>} />);
    expect(screen.queryByRole("button", { name: "Alpha" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Expand Group" }));
    expect(screen.getByRole("button", { name: "Alpha" })).toBeTruthy();
  });

  it("zooms the tool buttons about the viewport center, not a fixed point", () => {
    render(<FlowCanvas model={model} renderNode={node => <span>{node.title}</span>} />);
    measure(document.getElementById("viewport")!, 800, 400);
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(document.getElementById("world")!.style.transform).toMatch(/translate\(-80px, -40px\) scale\(1\.2\)/);
    expect(screen.getByText("120%")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Zoom out" }));
    expect(screen.getByText("100%")).toBeTruthy();
  });
});
