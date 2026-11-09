// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createElement } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Nav } from '../../ui/src/shell/Nav';
import { trapIndex } from '../../ui/src/shell/useDrawer';
import type { HubState } from '../../ui/src/types';

// jsdom has its own URL class, so the path is built with node:path.
const full = JSON.parse(
  readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '../fixtures/hub-state/full.json'), 'utf8'),
) as HubState;

const nav = (open: boolean, onToggle = vi.fn()) =>
  render(createElement(Nav, { route: { page: 'inbox' }, state: full, inbox: 3, open, onToggle }));

describe('trapIndex', () => {
  it('wraps forward and back, else steps by one', () => {
    expect(trapIndex(3, 2, false)).toBe(0);
    expect(trapIndex(3, 0, true)).toBe(2);
    expect(trapIndex(3, 1, false)).toBe(2);
  });
});

describe('phone drawer', () => {
  afterEach(cleanup);

  it('open: a modal dialog, focus on the first link, Escape closes', () => {
    const onToggle = vi.fn();
    nav(true, onToggle);
    const aside = document.getElementById('app-sidebar')!;
    expect(aside.getAttribute('role')).toBe('dialog');
    expect(aside.getAttribute('aria-modal')).toBe('true');
    expect(screen.getByRole('button', { name: 'Close navigation menu' })).toBeTruthy();
    expect(document.activeElement).toBe(aside.querySelector('a[href]'));
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onToggle).toHaveBeenCalledWith(false);
  });

  it('Tab from the last control wraps to the first', () => {
    nav(true);
    const aside = document.getElementById('app-sidebar')!;
    const all = [...aside.querySelectorAll<HTMLElement>('a[href], button')];
    all[all.length - 1]!.focus();
    fireEvent.keyDown(document, { key: 'Tab' });
    expect(document.activeElement).toBe(all[0]);
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true });
    expect(document.activeElement).toBe(all[all.length - 1]);
  });

  it('closed: no dialog role, the button opens', () => {
    nav(false);
    expect(document.getElementById('app-sidebar')!.getAttribute('role')).toBeNull();
    expect(screen.getByRole('button', { name: 'Open navigation menu' })).toBeTruthy();
  });

  it('focus goes back to the menu button when the drawer closes', () => {
    const view = nav(true);
    view.rerender(createElement(Nav, { route: { page: 'inbox' }, state: full, inbox: 3, open: false, onToggle: vi.fn() }));
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Open navigation menu' }));
  });
});

describe('Jump to anything button', () => {
  afterEach(cleanup);

  it('only with onJump; on the desktop it passes itself as the focus to give back', () => {
    nav(false);
    expect(screen.queryByRole('button', { name: /Jump to anything/ })).toBeNull();
    cleanup();
    const onJump = vi.fn();
    render(createElement(Nav, { route: { page: 'inbox' }, state: full, inbox: 3, open: false, onToggle: vi.fn(), onJump }));
    const btn = screen.getByRole('button', { name: /Jump to anything/ });
    expect(btn.getAttribute('aria-keyshortcuts')).toBe('Control+K Meta+K');
    expect(btn.textContent).toContain('Ctrl K');
    fireEvent.click(btn);
    expect(onJump).toHaveBeenCalledWith(btn);
  });

  it('in the open drawer it closes the drawer and gives focus back to the menu button', () => {
    const onJump = vi.fn();
    const onToggle = vi.fn();
    render(createElement(Nav, { route: { page: 'inbox' }, state: full, inbox: 3, open: true, onToggle, onJump }));
    fireEvent.click(screen.getByRole('button', { name: /Jump to anything/ }));
    expect(onToggle).toHaveBeenCalledWith(false);
    expect(onJump).toHaveBeenCalledWith(screen.getByRole('button', { name: 'Close navigation menu' }));
  });
});
