import { useEffect, useRef } from "react";
import { mount, SHELL_BODY_HTML, type FlowStudio } from "../templates/flow-studio.lib.mjs";
import type { Model, NoteDef } from "../src/model.ts";

export interface FlowStudioViewProps {
  model: Model;
  /** Read once at mount; later changes to this prop are ignored. For notes that change with the data, put them on `model.notes` — `update` forwards them. */
  notes?: NoteDef[];
  onSelect?: (id: string | null) => void;
  /** The bar key under the pointer (a node's `bars`), or null when it leaves. The latest function is always called. */
  onHoverKey?: (key: string | null) => void;
  className?: string;
}

// The engine publishes its mount helper on a shared global. Count mounted instances so the first
// mount claims the global and the last unmount releases it; unmounting one of several views must
// not clear the global while the others still run.
let mountedViews = 0;
let previousGlobalMount: typeof mount | undefined;

/** Mounts the finished engine in React. The shell stays outside React's child tree. */
export function FlowStudioView({ model, notes, onSelect, onHoverKey, className }: FlowStudioViewProps) {
  const root = useRef<HTMLDivElement>(null);
  const api = useRef<FlowStudio | null>(null);
  const currentModel = useRef(model);
  const currentNotes = useRef(notes);
  const currentSelect = useRef(onSelect);
  const currentHoverKey = useRef(onHoverKey);
  const lastModel = useRef<string | null>(null);
  currentModel.current = model;
  currentNotes.current = notes;
  currentSelect.current = onSelect;
  currentHoverKey.current = onHoverKey;
  const modelJson = JSON.stringify(model);

  useEffect(() => {
    const container = root.current;
    if (!container) return;
    container.innerHTML = SHELL_BODY_HTML;
    const instance = mount(container, currentModel.current, {
      notes: currentNotes.current,
      onSelect: id => currentSelect.current?.(id),
      onHoverKey: key => currentHoverKey.current?.(key),
    });
    if (mountedViews === 0) {
      previousGlobalMount = window.flowStudioMount;
      window.flowStudioMount = mount;
    }
    mountedViews++;
    api.current = instance;
    lastModel.current = JSON.stringify(currentModel.current);
    return () => {
      instance.destroy();
      if (api.current === instance) api.current = null;
      lastModel.current = null;
      mountedViews--;
      if (mountedViews === 0) {
        if (previousGlobalMount) window.flowStudioMount = previousGlobalMount;
        else delete window.flowStudioMount;
        previousGlobalMount = undefined;
      }
    };
  }, []);

  useEffect(() => {
    if (!api.current || lastModel.current === modelJson) return;
    api.current.update(model);
    lastModel.current = modelJson;
  }, [modelJson, model]);

  return <div ref={root} className={className} />;
}
