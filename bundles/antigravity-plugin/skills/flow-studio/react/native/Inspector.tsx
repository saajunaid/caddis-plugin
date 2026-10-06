import type { Model, NodeDef } from "../../src/model.ts";
import { bucketOf, nodeStateId } from "../../src/rules.ts";

export function Inspector({ model, node, mode, upstream, downstream, onClose, onSelect }: {
  model: Model; node: NodeDef | null; mode: string; upstream: Set<string>; downstream: Set<string>;
  onClose: () => void; onSelect?: (id: string) => void;
}) {
  if (!node) return null;
  const state = model.states[nodeStateId(model, mode, node)];
  return <aside id="inspector" className="insp open" role="dialog" aria-label={`${node.title} details`} aria-modal="false">
    <div className="insp-h"><div><h2>{node.title}</h2><small>{state?.word ?? "Unknown state"}</small></div><button type="button" onClick={onClose} aria-label="Close inspector">×</button></div>
    <div className="insp-b">
      {node.subtitle && <p>{node.subtitle}</p>}
      <p>State: {bucketOf(model, nodeStateId(model, mode, node))}</p>
      <div className="counts">
        <button type="button" className="cbtn" aria-label={`${Math.max(0, upstream.size - 1)} upstream nodes`}>Upstream {Math.max(0, upstream.size - 1)}</button>
        <button type="button" className="cbtn" aria-label={`${Math.max(0, downstream.size - 1)} downstream nodes`}>Downstream {Math.max(0, downstream.size - 1)}</button>
      </div>
      <div className="drill" aria-label="Connected nodes">
        {[...new Set([...upstream, ...downstream])].filter(id => id !== node.id).map(id => {
          const related = model.nodes.find(item => item.id === id);
          return related && <button type="button" key={id} onClick={() => onSelect?.(id)}>{related.title}</button>;
        })}
      </div>
    </div>
  </aside>;
}
