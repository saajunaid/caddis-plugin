import type { ReactNode } from "react";
import type { Model, NodeDef } from "../../src/model.ts";
import { defaultView } from "../../src/rules.ts";
import { elbow, loopBack } from "../../src/routing.ts";
import { useFlowGeometry } from "./useFlowGeometry.ts";
import { useTrace } from "./useTrace.ts";
import { useViewport } from "./useViewport.ts";
import { Inspector } from "./Inspector.tsx";
import "./native.css";

export interface FlowCanvasProps {
  model: Model;
  renderNode: (node: NodeDef, context: { selected: boolean; connected: boolean }) => ReactNode;
  mode?: string;
  className?: string;
}

/** Small native example. Apps can replace every element while retaining the hooks. */
export function FlowCanvas({ model: input, renderNode, mode, className }: FlowCanvasProps) {
  const activeMode = mode ?? defaultView(input);
  const trace = useTrace(input, activeMode);
  const { model, geometry } = useFlowGeometry(input, { x: 0, y: 0, k: 1 }, trace.collapsed, activeMode);
  const viewport = useViewport(geometry.bounds);
  const selected = model.nodes.find(node => node.id === trace.selected) ?? null;
  const path = (link: typeof model.links[number]) => {
    const from = geometry.nodes[link.from], to = geometry.nodes[link.to];
    if (!from || !to) return "";
    if (link.kind === "loop-back") return loopBack(from.x + from.w / 2, from.y + from.h, to.x + to.w / 2, to.y + to.h, geometry.loops[link.id]?.channelY ?? Math.max(from.y + from.h, to.y + to.h) + 20);
    return elbow(from.x + from.w, from.y + from.h / 2, to.x, to.y + to.h / 2, (from.x + from.w + to.x) / 2);
  };
  return <section id="workspace" className={`flow-native ${className ?? ""}`}>
    <div id="tools" className="flow-native-tools">
      <button type="button" onClick={() => viewport.fit()} aria-label="Fit graph">Fit</button>
      <button type="button" onClick={() => viewport.zoomAboutCenter(1.2)} aria-label="Zoom in">+</button>
      <button type="button" onClick={() => viewport.zoomAboutCenter(1 / 1.2)} aria-label="Zoom out">−</button>
      <span id="zoomLabel">{Math.round(viewport.view.k * 100)}%</span>
    </div>
    <div id="cols" className="flow-native-cols" aria-label="Columns">{model.columns.map((column, i) => <span key={column.id} style={{ left: (geometry.xs[i] ?? 0) * viewport.view.k + viewport.view.x, width: column.width * viewport.view.k }}>{column.title}</span>)}</div>
    <div id="viewport" className="flow-native-viewport" {...viewport.bind}>
      <div id="world" className="flow-native-world" style={{ width: geometry.world.w, height: geometry.world.h, transform: `translate(${viewport.view.x}px, ${viewport.view.y}px) scale(${viewport.view.k})` }}>
        {model.lanes.map(lane => { const rect = geometry.lanes[lane.id]; return rect && <div key={lane.id} className="flow-native-lane" style={{ left: rect.x, top: rect.y, width: rect.w, height: rect.h }}><strong>{lane.title}</strong></div>; })}
        <svg id="edges" className="flow-native-edges" width={geometry.world.w} height={geometry.world.h} aria-label="Links"><g id="edgeLayer">{trace.links.map(link => <path key={link.id} data-link-id={link.id} d={path(link)} fill="none" stroke="currentColor" strokeWidth="2" />)}</g></svg>
        {model.nodes.filter(node => trace.visible.has(node.id)).map(node => {
          const rect = geometry.nodes[node.id]; if (!rect) return null;
          return <div key={node.id} id={`n_${node.id}`} className="flow-native-node" style={{ left: rect.x, top: rect.y, width: rect.w, height: rect.h }}>
            <button type="button" className="flow-native-node-main" aria-label={node.title} aria-pressed={trace.selected === node.id} data-connected={trace.connected.has(node.id)}
              onMouseEnter={() => trace.setHover(node.id)} onMouseLeave={() => trace.setHover(null)} onFocus={() => trace.setHover(node.id)} onBlur={() => trace.setHover(null)}
              onClick={() => trace.setSelected(node.id)}>{renderNode(node, { selected: trace.selected === node.id, connected: trace.connected.has(node.id) })}</button>
            {node.kind === "group" && node.contains?.length ? <button type="button" className="flow-native-toggle" aria-label={`${trace.collapsed.has(node.id) ? "Expand" : "Collapse"} ${node.title}`}
              onClick={() => trace.toggleGroup(node.id)}>{trace.collapsed.has(node.id) ? "+" : "−"}</button> : null}
          </div>;
        })}
      </div>
    </div>
    <div id="live" className="flow-native-live" aria-live="polite">{selected ? `${selected.title} selected` : ""}</div>
    <Inspector model={model} node={selected} mode={activeMode} upstream={trace.upstream} downstream={trace.downstream} onClose={() => trace.setSelected(null)} onSelect={trace.setSelected} />
  </section>;
}
