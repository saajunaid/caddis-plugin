// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createElement } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PhaseLoaderContext, type PhaseLoader } from '../../ui/src/repo/phaseLoader';
import RoadmapTab from '../../ui/src/repo/RoadmapTab';
import type { HubState, RepoState } from '../../ui/src/types';

// jsdom replaces the global URL, so build the path with node:path, not `new URL(..., import.meta.url)`.
const load = (name: string): HubState =>
  JSON.parse(readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), `../fixtures/hub-state/${name}.json`), 'utf8')) as HubState;
const repoOf = (s: HubState, name: string): RepoState => s.repos.find((r) => r.name === name)!;

function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((a, b) => {
    resolve = a;
    reject = b;
  });
  return { promise, resolve, reject };
}

// Titles only (no text): the panel must fetch the section.
const docsRepo = (): RepoState => {
  const repo = structuredClone(repoOf(load('full'), 'docs'));
  (repo.plans as { plans: Array<{ phases?: unknown }> }).plans[0]!.phases = { '1': { title: 'Login' }, '2': { title: 'Fonts' } };
  return repo;
};
const shopRepo = (): RepoState => structuredClone(repoOf(load('full'), 'shop'));

const renderDocs = (loader: PhaseLoader) =>
  render(
    createElement(
      PhaseLoaderContext.Provider,
      { value: loader },
      createElement(RoadmapTab, { repo: docsRepo(), slug: null, initialOpenAll: true }),
    ),
  );
const tiles = (): HTMLElement[] => Array.from(document.querySelectorAll<HTMLElement>('[data-testid="rm-timeline"] .rm-tile'));
const note = (): string | null => screen.getByTestId('rm-panel-note').textContent;

afterEach(cleanup);

describe('phase panel in the DOM', () => {
  it('a tile click shows Loading, then the section text', async () => {
    const loader = vi.fn<PhaseLoader>().mockResolvedValue({ text: 'Section one text' });
    renderDocs(loader);
    fireEvent.click(tiles()[0]!);
    expect(note()).toBe('Loading the plan section…');
    await screen.findByText('Section one text');
    expect(loader).toHaveBeenCalledTimes(1);
    expect(loader).toHaveBeenCalledWith('/srv/demo/docs', '.caddis/plans/p-docs.md', '1');
  });

  it('after an error, reopening the phase shows Loading, not the old error', async () => {
    const loader = vi
      .fn<PhaseLoader>()
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValueOnce({ text: 'Second try' });
    renderDocs(loader);
    fireEvent.click(tiles()[0]!);
    await screen.findByText('Could not load the plan section.');
    fireEvent.click(screen.getByTestId('rm-panel-close'));
    fireEvent.click(tiles()[0]!);
    expect(note()).toBe('Loading the plan section…');
    await screen.findByText('Second try');
    expect(loader).toHaveBeenCalledTimes(2);
  });

  it('text loaded once is not shown again before the new load returns', async () => {
    const second = deferred<{ text: string }>();
    const loader = vi.fn<PhaseLoader>().mockResolvedValueOnce({ text: 'v1' }).mockReturnValueOnce(second.promise);
    renderDocs(loader);
    fireEvent.click(tiles()[0]!);
    await screen.findByText('v1');
    fireEvent.click(screen.getByTestId('rm-panel-close'));
    fireEvent.click(tiles()[0]!);
    expect(screen.queryByText('v1')).toBeNull();
    await act(async () => {
      second.resolve({ text: 'v2' });
    });
    await screen.findByText('v2');
  });

  it('a slow first load does not overwrite the second phase', async () => {
    const first = deferred<{ text: string }>();
    const second = deferred<{ text: string }>();
    const loader = vi.fn<PhaseLoader>().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    renderDocs(loader);
    fireEvent.click(tiles()[0]!);
    fireEvent.keyDown(window, { key: 'Escape' });
    fireEvent.click(tiles()[1]!);
    await act(async () => {
      second.resolve({ text: 'two' });
    });
    await act(async () => {
      first.resolve({ text: 'one' });
    });
    expect(screen.getByTestId('rm-panel-title').textContent).toContain('Fonts');
    expect(screen.queryByText('one')).toBeNull();
    expect(screen.getByText('two')).toBeTruthy();
  });

  it('clicking the already-open tile keeps the loaded text', async () => {
    const loader = vi.fn<PhaseLoader>().mockResolvedValue({ text: 'Section one text' });
    renderDocs(loader);
    fireEvent.click(tiles()[0]!);
    await screen.findByText('Section one text');
    fireEvent.click(tiles()[0]!);
    expect(screen.getByText('Section one text')).toBeTruthy();
    expect(screen.queryByTestId('rm-panel-note')).toBeNull();
    expect(loader).toHaveBeenCalledTimes(1);
  });

  it('after an error, clicking the already-open tile retries the load', async () => {
    const loader = vi
      .fn<PhaseLoader>()
      .mockRejectedValueOnce(new Error('boom'))
      .mockResolvedValueOnce({ text: 'Second try' });
    renderDocs(loader);
    fireEvent.click(tiles()[0]!);
    await screen.findByText('Could not load the plan section.');
    fireEvent.click(tiles()[0]!);
    await screen.findByText('Second try');
    expect(loader).toHaveBeenCalledTimes(2);
  });

  it('Escape in the search box clears it and keeps the panel open', () => {
    const loader = vi.fn<PhaseLoader>().mockResolvedValue({ text: 'x' });
    render(
      createElement(
        PhaseLoaderContext.Provider,
        { value: loader },
        createElement(RoadmapTab, { repo: shopRepo(), slug: 'launch' }),
      ),
    );
    fireEvent.click(tiles()[0]!);
    const box = screen.getByTestId('rm-search') as HTMLInputElement;
    fireEvent.change(box, { target: { value: 'login' } });
    fireEvent.keyDown(box, { key: 'Escape' });
    expect(box.value).toBe('');
    expect(screen.getByTestId('rm-panel')).toBeTruthy();
  });

  it('Escape outside an input closes the panel and returns focus to the tile', () => {
    const loader = vi.fn<PhaseLoader>().mockResolvedValue({ text: 'x' });
    renderDocs(loader);
    const tile = tiles()[0]!;
    fireEvent.click(tile);
    fireEvent.keyDown(document.body, { key: 'Escape' });
    expect(screen.queryByTestId('rm-panel')).toBeNull();
    expect(document.activeElement).toBe(tile);
  });
});
