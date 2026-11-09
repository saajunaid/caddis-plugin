// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createElement } from 'react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { Inbox } from '../../ui/src/inbox/Inbox';
import { useInbox } from '../../ui/src/inbox/useInbox';
import type { ActApi } from '../../ui/src/actions/useActions';
import type { HubState } from '../../ui/src/types';

// jsdom replaces the global URL, so build the path with node:path.
const full = JSON.parse(
  readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '../fixtures/hub-state/full.json'), 'utf8'),
) as HubState;
const now = Date.parse(full.generated_at);
const act0: ActApi = { local: {}, run: () => undefined };

const BLOCKED_ID = 'merge:/srv/demo/docs:88';
const BLOCKED_TITLE = 'PR #88: required check lint failed';

function Harness({ item }: { item: string | null }): JSX.Element {
  const api = useInbox(full, now);
  return createElement(Inbox, { state: full, nowMs: now, api, act: act0, item });
}

beforeEach(() => localStorage.clear());
afterEach(cleanup);

describe('Inbox with a route item (palette link)', () => {
  it('selects the item folder, the row and the detail', () => {
    render(createElement(Harness, { item: BLOCKED_ID }));
    expect(screen.getByTestId('folder-blocked').getAttribute('aria-selected')).toBe('true');
    expect(screen.getByTestId('folder-needs').getAttribute('aria-selected')).toBe('false');
    const rows = screen.getAllByTestId('inbox-item');
    const on = rows.filter((r) => r.getAttribute('aria-current') === 'true');
    expect(on).toHaveLength(1);
    expect(on[0]!.textContent).toContain(BLOCKED_TITLE);
    expect(screen.getByTestId('inbox-detail').textContent).toContain(BLOCKED_TITLE);
    expect(screen.queryByTestId('inbox-notice')).toBeNull();
  });

  it('marks the item read', () => {
    render(createElement(Harness, { item: BLOCKED_ID }));
    const on = screen.getAllByTestId('inbox-item').find((r) => r.getAttribute('aria-current') === 'true')!;
    expect(on.querySelector('.unread-dot')!.getAttribute('aria-label')).toBe('Read');
  });

  it('an unknown id shows the Inbox as usual and a notice, until the user picks a folder', () => {
    render(createElement(Harness, { item: 'merge:/srv/gone:1' }));
    expect(screen.getByTestId('inbox-notice').textContent).toBe('That item is no longer in the Inbox.');
    expect(screen.getByTestId('folder-needs').getAttribute('aria-selected')).toBe('true');
    expect(screen.getAllByTestId('inbox-item').length).toBeGreaterThan(0);
    fireEvent.click(screen.getByTestId('folder-blocked'));
    expect(screen.queryByTestId('inbox-notice')).toBeNull();
  });

  it('applies once: a later manual folder change is kept across re-renders', () => {
    const view = render(createElement(Harness, { item: BLOCKED_ID }));
    fireEvent.click(screen.getByTestId('folder-approvals'));
    view.rerender(createElement(Harness, { item: BLOCKED_ID }));
    expect(screen.getByTestId('folder-approvals').getAttribute('aria-selected')).toBe('true');
  });

  it('a new route item is applied again', () => {
    const view = render(createElement(Harness, { item: BLOCKED_ID }));
    act(() => {
      view.rerender(createElement(Harness, { item: 'waiting:demo-session-export' }));
    });
    expect(screen.getByTestId('folder-needs').getAttribute('aria-selected')).toBe('true');
    expect(screen.getByTestId('inbox-detail').textContent).toContain('demo-session-export');
  });
});
