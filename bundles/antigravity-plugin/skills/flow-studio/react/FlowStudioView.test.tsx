import React, { StrictMode } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render } from '@testing-library/react';
import type { Model, NoteDef } from '../src/model.ts';

const lifecycle = vi.hoisted(() => ({
  alive: 0, updates: [] as Model[], mounts: 0, listenerCount: 0,
  notes: [] as (NoteDef[] | undefined)[],
  onSelect: undefined as ((id: string | null) => void) | undefined,
  onHoverKey: undefined as ((key: string | null) => void) | undefined,
}));
vi.mock('../templates/flow-studio.lib.mjs', () => ({
  SHELL_BODY_HTML: '<div id="viewport"></div>',
  mount: (_root: ParentNode, _model: Model, options: { notes?: NoteDef[]; onSelect?: (id: string | null) => void; onHoverKey?: (key: string | null) => void }) => {
    lifecycle.mounts++;
    lifecycle.alive++;
    lifecycle.listenerCount++;
    lifecycle.notes.push(options.notes);
    lifecycle.onSelect = options.onSelect;
    lifecycle.onHoverKey = options.onHoverKey;
    return {
      update: (model: Model) => { lifecycle.updates.push(model); return { ok: true, issues: [] }; },
      destroy: () => { lifecycle.alive--; lifecycle.listenerCount--; },
    };
  },
}));

import { FlowStudioView } from './FlowStudioView.tsx';

const model = { version: 1, columns: [], lanes: [], nodes: [], links: [], states: {} } as unknown as Model;

describe('FlowStudioView', () => {
  it('keeps one instance and listener set through StrictMode, updates once, and cleans up', () => {
    const globals = window as Window & { flowStudioMount?: unknown };
    const previousMount = globals.flowStudioMount;
    lifecycle.alive = 0;
    lifecycle.mounts = 0;
    lifecycle.listenerCount = 0;
    lifecycle.updates = [];
    lifecycle.notes = [];
    const select = vi.fn();
    const rendered = render(<StrictMode><FlowStudioView model={model} onSelect={select} /></StrictMode>);
    expect(lifecycle.mounts).toBe(2);
    expect(lifecycle.alive).toBe(1);
    expect(lifecycle.listenerCount).toBe(1);
    expect(globals.flowStudioMount).toBeTypeOf('function');
    lifecycle.onSelect?.('sample');
    expect(select).toHaveBeenCalledWith('sample');
    rendered.rerender(<StrictMode><FlowStudioView model={structuredClone(model)} onSelect={select} /></StrictMode>);
    expect(lifecycle.updates).toHaveLength(0);
    const changed = { ...model, meta: { title: 'Updated', help: '', asOf: '', source: '' } } as Model;
    rendered.rerender(<StrictMode><FlowStudioView model={changed} onSelect={select} /></StrictMode>);
    expect(lifecycle.updates).toEqual([changed]);
    expect(lifecycle.alive).toBe(1);
    rendered.unmount();
    expect(lifecycle.alive).toBe(0);
    expect(lifecycle.listenerCount).toBe(0);
    expect(globals.flowStudioMount).toBe(previousMount);
  });

  it('forwards the hovered bar key to the latest onHoverKey, without remounting', () => {
    lifecycle.mounts = 0;
    const first = vi.fn();
    const second = vi.fn();
    const rendered = render(<FlowStudioView model={model} onHoverKey={first} />);
    lifecycle.onHoverKey?.('2026-09-02');
    expect(first).toHaveBeenCalledWith('2026-09-02');
    rendered.rerender(<FlowStudioView model={model} onHoverKey={second} />);
    expect(lifecycle.mounts).toBe(1);
    lifecycle.onHoverKey?.(null);
    expect(second).toHaveBeenCalledWith(null);
    expect(first).toHaveBeenCalledTimes(1);
    rendered.unmount();
  });

  it('passes notes at mount and ignores later notes-only changes', () => {
    lifecycle.updates = [];
    lifecycle.notes = [];
    const first = [{ anchor: 'a', title: 'First', text: 'Mount-time note' }] satisfies NoteDef[];
    const second = [{ anchor: 'b', title: 'Second', text: 'Changed note' }] satisfies NoteDef[];
    const rendered = render(<FlowStudioView model={model} notes={first} />);
    expect(lifecycle.notes).toEqual([first]);
    rendered.rerender(<FlowStudioView model={model} notes={second} />);
    expect(lifecycle.updates).toHaveLength(0);
    expect(lifecycle.notes).toEqual([first]);
  });

  it('keeps window.flowStudioMount while any instance is mounted', () => {
    const globals = window as Window & { flowStudioMount?: unknown };
    const previous = globals.flowStudioMount;
    const first = render(<FlowStudioView model={model} />);
    const second = render(<FlowStudioView model={model} />);
    expect(globals.flowStudioMount).toBeTypeOf('function');
    first.unmount();
    expect(globals.flowStudioMount).toBeTypeOf('function');
    second.unmount();
    expect(globals.flowStudioMount).toBe(previous);
  });
});
