import { useEffect, useMemo, useState } from "react";
import type { Model } from "../../src/model.ts";
import { canonOf, defaultView, effectiveLinks, initialCollapsed, nodeVisible, toggleGroupState } from "../../src/rules.ts";
import { connected, relatives } from "../../src/trace.ts";

export function useTrace(model: Model, mode = defaultView(model)) {
  const [selected, setSelected] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState<Set<string>>(() => initialCollapsed(model));
  const nodes = useMemo(() => new Map(model.nodes.map(node => [node.id, node])), [model]);
  const links = useMemo(() => effectiveLinks(model, mode, collapsed, nodes), [model, mode, collapsed, nodes]);
  const visible = useMemo(() => new Set(model.nodes.filter(node => nodeVisible(model, mode, node, collapsed)).map(node => node.id)), [model, mode, collapsed]);
  const focus = selected ?? hover;
  const canonical = (id: string) => canonOf(nodes, id);
  const upstream = useMemo(() => focus ? relatives(links, canonical, focus, "up") : new Set<string>(), [links, focus, nodes]);
  const downstream = useMemo(() => focus ? relatives(links, canonical, focus, "down") : new Set<string>(), [links, focus, nodes]);
  const connectedNodes = useMemo(() => focus ? connected(links, canonical, focus) : new Set<string>(), [links, focus, nodes]);
  const toggleGroup = (id: string) => {
    const next = toggleGroupState(model, mode, collapsed, id);
    if (next) { setCollapsed(next.collapsed); setSelected(next.selected); }
  };
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") setSelected(null); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);
  useEffect(() => { if (selected && !visible.has(selected)) setSelected(null); }, [visible, selected]);
  return { selected, setSelected, hover, setHover, collapsed, toggleGroup, links, visible, connected: connectedNodes, upstream, downstream };
}
