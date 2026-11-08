// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { createElement } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Tooltip, tipPosition } from '../../ui/src/shell/Tooltip';

const view = { width: 1000, height: 800 };
const rect = (top: number, left: number, w = 100, h = 20) => ({ top, left, right: left + w, bottom: top + h, width: w, height: h });

describe('tipPosition', () => {
  it('puts the bubble below the trigger when it fits', () => {
    const p = tipPosition(rect(100, 100), { width: 200, height: 50 }, view);
    expect(p.placement).toBe('below');
    expect(p.top).toBeGreaterThanOrEqual(120);
  });

  it('flips above when there is no room below', () => {
    const p = tipPosition(rect(760, 100), { width: 200, height: 50 }, view);
    expect(p.placement).toBe('above');
    expect(p.top + 50).toBeLessThanOrEqual(760);
  });

  it('keeps the bubble inside the viewport on the right and the left', () => {
    const r = tipPosition(rect(100, 950), { width: 200, height: 50 }, view);
    expect(r.left + 200).toBeLessThanOrEqual(view.width);
    const l = tipPosition(rect(100, -40), { width: 200, height: 50 }, view);
    expect(l.left).toBeGreaterThanOrEqual(0);
  });
});

const trigger = (content: string | null) =>
  render(createElement(Tooltip, { content, children: createElement('button', { type: 'button', 'data-testid': 'trg' }, 'Trigger') }));
const tip = (): HTMLElement | null => screen.queryByTestId('tip');
const tick = (ms: number): void => {
  act(() => {
    vi.advanceTimersByTime(ms);
  });
};

describe('Tooltip', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('shows after 150 ms of hover, with role tooltip and aria-describedby', () => {
    trigger('Hello tip');
    const t = screen.getByTestId('trg');
    fireEvent.pointerEnter(t);
    tick(149);
    expect(tip()).toBeNull();
    tick(1);
    const bubble = tip()!;
    expect(bubble.textContent).toBe('Hello tip');
    expect(bubble.getAttribute('role')).toBe('tooltip');
    expect(bubble.className).toBe('tip');
    expect(bubble.parentElement).toBe(document.body);
    expect(t.getAttribute('aria-describedby')).toBe(bubble.id);
  });

  it('shows on keyboard focus after 150 ms and hides on blur after 100 ms', () => {
    trigger('Focus tip');
    const t = screen.getByTestId('trg');
    fireEvent.focus(t);
    tick(150);
    expect(tip()).not.toBeNull();
    fireEvent.blur(t);
    tick(99);
    expect(tip()).not.toBeNull();
    tick(1);
    expect(tip()).toBeNull();
    expect(t.getAttribute('aria-describedby')).toBeNull();
  });

  it('stays while the pointer moves from the trigger to the bubble', () => {
    trigger('Stay tip');
    const t = screen.getByTestId('trg');
    fireEvent.pointerEnter(t);
    tick(150);
    fireEvent.pointerLeave(t);
    tick(50);
    fireEvent.pointerEnter(tip()!);
    tick(500);
    expect(tip()).not.toBeNull();
    fireEvent.pointerLeave(tip()!);
    tick(100);
    expect(tip()).toBeNull();
  });

  it('Escape hides it', () => {
    trigger('Esc tip');
    fireEvent.pointerEnter(screen.getByTestId('trg'));
    tick(150);
    expect(tip()).not.toBeNull();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(tip()).toBeNull();
  });

  it('empty content renders the child only and never a bubble', () => {
    trigger(null);
    const t = screen.getByTestId('trg');
    fireEvent.pointerEnter(t);
    tick(500);
    expect(tip()).toBeNull();
    expect(t.getAttribute('aria-describedby')).toBeNull();
  });

  it('keeps the handlers of the child', () => {
    const onFocus = vi.fn();
    render(createElement(Tooltip, { content: 'x', children: createElement('button', { type: 'button', 'data-testid': 'trg', onFocus }, 'T') }));
    fireEvent.focus(screen.getByTestId('trg'));
    expect(onFocus).toHaveBeenCalledTimes(1);
  });
});
