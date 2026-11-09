// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createElement } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { deriveInbox } from '../../ui/src/inbox/derive';
import { isPaletteKey, PaletteHost, usePalette } from '../../ui/src/palette/PaletteHost';
import type { HubState } from '../../ui/src/types';

// jsdom replaces the global URL, so build the path with node:path, not `new URL(..., import.meta.url)`.
const full = JSON.parse(
  readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '../fixtures/hub-state/full.json'), 'utf8'),
) as HubState;
const now = Date.parse(full.generated_at);

function Harness(): JSX.Element {
  const pal = usePalette();
  return createElement(
    'div',
    null,
    createElement('button', { type: 'button', 'data-testid': 'before' }, 'before'),
    createElement('input', { 'data-testid': 'field', 'aria-label': 'field' }),
    createElement('button', { type: 'button', 'data-testid': 'jump', onClick: (e: { currentTarget: HTMLElement }) => pal.show(e.currentTarget) }, 'Jump'),
    createElement(PaletteHost, { pal, state: full, inbox: deriveInbox(full, now).items, nowMs: now }),
  );
}

const input = (): HTMLInputElement => screen.getByRole('combobox') as HTMLInputElement;
const options = (): HTMLElement[] => screen.queryAllByRole('option');
const selected = (): HTMLElement | undefined => options().find((o) => o.getAttribute('aria-selected') === 'true');
const ctrlK = (target: Element = document.body): boolean => fireEvent.keyDown(target, { key: 'k', ctrlKey: true });
async function openPalette(): Promise<HTMLElement> {
  act(() => {
    ctrlK();
  });
  return screen.findByRole('dialog', { name: 'Jump to anything' });
}

beforeEach(() => {
  window.location.hash = '#/inbox';
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe('isPaletteKey', () => {
  it('Ctrl+K and Meta+K only', () => {
    const k = (o: Partial<KeyboardEvent>): boolean => isPaletteKey({ key: 'k', ctrlKey: false, metaKey: false, altKey: false, ...o } as KeyboardEvent);
    expect(k({ ctrlKey: true })).toBe(true);
    expect(k({ metaKey: true })).toBe(true);
    expect(k({ key: 'K', ctrlKey: true })).toBe(true);
    expect(k({})).toBe(false);
    expect(k({ ctrlKey: true, altKey: true })).toBe(false);
    expect(k({ key: 'j', ctrlKey: true })).toBe(false);
  });
});

describe('command palette in the DOM', () => {
  it('Ctrl+K opens a modal dialog, prevents the browser default, focuses the input', async () => {
    render(createElement(Harness));
    expect(screen.queryByRole('dialog')).toBeNull();
    let notPrevented = true;
    act(() => {
      notPrevented = ctrlK();
    });
    expect(notPrevented).toBe(false);
    const dialog = await screen.findByRole('dialog', { name: 'Jump to anything' });
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    expect(document.activeElement).toBe(input());
    expect(input().getAttribute('aria-expanded')).toBe('true');
    expect(input().getAttribute('aria-controls')).toBe(screen.getByRole('listbox').id);
    // Empty query: pages first.
    expect(options()[0]!.textContent).toContain('Inbox');
    expect(input().getAttribute('aria-activedescendant')).toBe(options()[0]!.id);
    expect(screen.getByTestId('palette-status').textContent).toBe('38 results');
  });

  it('Ctrl+K works while focus is in a text field', async () => {
    render(createElement(Harness));
    screen.getByTestId('field').focus();
    act(() => {
      ctrlK(screen.getByTestId('field'));
    });
    await screen.findByRole('dialog', { name: 'Jump to anything' });
  });

  it('typing filters; no match shows "No match"', async () => {
    render(createElement(Harness));
    await openPalette();
    fireEvent.change(input(), { target: { value: 'shop sess' } });
    expect(options()[0]!.textContent).toContain('shop · Sessions');
    fireEvent.change(input(), { target: { value: 'zzqxw' } });
    expect(options()).toHaveLength(0);
    expect(screen.getByText('No match')).toBeTruthy();
    expect(screen.getByTestId('palette-status').textContent).toBe('0 results');
  });

  it('ArrowDown + Enter goes to the route and closes', async () => {
    render(createElement(Harness));
    await openPalette();
    fireEvent.change(input(), { target: { value: 'billing' } });
    expect(options().slice(0, 3).map((o) => o.querySelector('.pal-label')!.textContent)).toEqual([
      'billing · Flow',
      'billing · Roadmap',
      'billing · Sessions',
    ]);
    fireEvent.keyDown(input(), { key: 'ArrowDown' });
    expect(selected()!.textContent).toContain('billing · Roadmap');
    expect(input().getAttribute('aria-activedescendant')).toBe(selected()!.id);
    fireEvent.keyDown(input(), { key: 'Enter' });
    expect(window.location.hash).toBe('#/repo/acme__billing/roadmap');
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('ArrowUp wraps to the last row, Home and End jump', async () => {
    render(createElement(Harness));
    await openPalette();
    fireEvent.change(input(), { target: { value: 'billing' } });
    const n = options().length;
    fireEvent.keyDown(input(), { key: 'ArrowUp' });
    expect(selected()).toBe(options()[n - 1]);
    fireEvent.keyDown(input(), { key: 'ArrowDown' });
    expect(selected()).toBe(options()[0]);
    fireEvent.keyDown(input(), { key: 'End' });
    expect(selected()).toBe(options()[n - 1]);
    fireEvent.keyDown(input(), { key: 'Home' });
    expect(selected()).toBe(options()[0]);
  });

  it('mouse hover moves the selection, a click runs the row', async () => {
    render(createElement(Harness));
    await openPalette();
    fireEvent.change(input(), { target: { value: 'docs' } });
    const row = options().find((o) => o.textContent!.includes('docs · Sessions'))!;
    fireEvent.mouseMove(row);
    expect(selected()).toBe(row);
    fireEvent.click(row);
    expect(window.location.hash).toBe('#/repo/acme__docs/sessions');
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('Escape closes and focus goes back to the element that had it', async () => {
    render(createElement(Harness));
    const before = screen.getByTestId('before');
    before.focus();
    await openPalette();
    fireEvent.keyDown(input(), { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(before);
  });

  it('a backdrop click closes; focus goes back to the opener button', async () => {
    render(createElement(Harness));
    const jump = screen.getByTestId('jump');
    jump.focus();
    fireEvent.click(jump);
    await screen.findByRole('dialog', { name: 'Jump to anything' });
    fireEvent.click(screen.getByTestId('palette-backdrop'));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(jump);
  });

  it('copy: "Copied", then the palette closes', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    render(createElement(Harness));
    await openPalette();
    fireEvent.change(input(), { target: { value: 'demo-session-export' } });
    fireEvent.keyDown(input(), { key: 'Enter' });
    expect(writeText).toHaveBeenCalledWith('demo-session-export');
    expect(await screen.findByText('Copied')).toBeTruthy();
    await vi.waitFor(() => expect(screen.queryByRole('dialog')).toBeNull(), { timeout: 2000 });
  });

  it('copy denied: "Copy failed", no unhandled rejection, the palette stays open', async () => {
    const writeText = vi.fn().mockRejectedValue(new Error('NotAllowedError'));
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    render(createElement(Harness));
    await openPalette();
    fireEvent.change(input(), { target: { value: 'demo-session-export' } });
    fireEvent.keyDown(input(), { key: 'Enter' });
    expect(await screen.findByText('Copy failed')).toBeTruthy();
    expect(screen.getByRole('dialog')).toBeTruthy();
  });

  it('a pull request opens in a new tab without an opener', async () => {
    const open = vi.spyOn(window, 'open').mockReturnValue(null);
    render(createElement(Harness));
    await openPalette();
    fireEvent.change(input(), { target: { value: '#212' } });
    fireEvent.keyDown(input(), { key: 'Enter' });
    expect(open).toHaveBeenCalledWith('https://example.invalid/pull/212', '_blank', 'noopener,noreferrer');
    expect(screen.queryByRole('dialog')).toBeNull();
    open.mockRestore();
  });
});
