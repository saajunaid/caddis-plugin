import { useMemo } from "react";
import { autoLayout } from "../../src/autolayout.ts";
import { computeGeometry } from "../../src/layout.ts";
import type { Model } from "../../src/model.ts";
import { defaultView, nodeVisible } from "../../src/rules.ts";
import type { View } from "../../src/viewport.ts";

// Shared default. A fresh Set() per render would change the memo identity below and recompute
// the geometry on every render. Never mutate it.
const EMPTY_COLLAPSED = new Set<string>();

/** Layout is world-space; the returned view is applied as a transform by the canvas. */
export function useFlowGeometry(model: Model, view: View, collapsed: Set<string> = EMPTY_COLLAPSED, mode = defaultView(model)) {
  const laidOut = useMemo(() => model.layout === "auto" ? autoLayout(model) : model, [model]);
  const geometry = useMemo(() => computeGeometry(laidOut, {
    visible: id => {
      const node = laidOut.nodes.find(item => item.id === id);
      return !!node && nodeVisible(laidOut, mode, node, collapsed);
    },
  }), [laidOut, collapsed, mode]);
  return { model: laidOut, geometry, view };
}
