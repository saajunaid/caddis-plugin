# Flow studio in a React app

## Choose a route

Use `FlowStudioView` when the page may use the engine's own look. It includes the complete canvas, inspector, notes, playback, search, and live update behavior. Use `native/` when the page must use the app's own components and design system. The native files are small examples built from the same pure source modules.

## Install

Copy `react/`, `src/`, `templates/flow-studio.lib.mjs`, `templates/flow-studio.lib.d.mts`, and `templates/flow-studio.css` into the same relative layout in your app. Install React 18 or later. The native route needs only the pure modules under `src/`; the fast route uses the bundled library. Import `flow-studio.css` once for the fast route. Import `react/native/native.css` for the native example only.

```tsx
import { FlowStudioView, FlowLoading, FlowEmpty, FlowError, type Model } from './react/index.ts';
import './templates/flow-studio.css';

type State = { kind: 'loading' } | { kind: 'ready'; model: Model; refreshError?: string } | { kind: 'error'; message: string };
function FlowPage({ state, onRetry, onSelect }: { state: State; onRetry: () => void; onSelect: (id: string | null) => void }) {
  if (state.kind === 'loading') return <FlowLoading />;
  if (state.kind === 'error') return <FlowError message={state.message} onRetry={onRetry} />;
  if (state.model.nodes.length === 0) return <FlowEmpty model={state.model} />;
  return <>{state.refreshError && <FlowError message={state.refreshError} onRetry={onRetry} />}
    <FlowStudioView model={state.model} onSelect={onSelect} /></>;
}
```

`FlowStudioView` takes a required `model` and optional `notes`, `onSelect`, `onHoverKey`, and `className`. `notes` is read once at mount; later changes to the prop are ignored. For notes that change with the data, put them on the model (`model.notes`) — `update` forwards them. `onSelect` receives a stable node id or `null` when selection clears. `onHoverKey` receives the key of the bar under the pointer (see `bars` on a node) or `null`; call `window.FlowStudio?.highlightKey(key)` to mark a key from outside. The component mounts the engine once, sends changed models to `update`, and destroys its listeners on unmount. React StrictMode's development mount cycle is supported. Several views may be mounted at once; the engine's global mount helper stays available until the last one unmounts.

## Live data contract

Map source rows to `Model` with stable node and link ids. Derive each id from a durable business key. Never derive ids from array positions or current sort order. Keep missing metrics typed as missing. Do not turn them into zero. Show `FlowLoading` before the first model, `FlowEmpty` when the model has no nodes, and `FlowError` for a request failure.

An update that fails model validation keeps the last good graph and shows a message in the engine's `#banner`. Keep the last good model in app state when a data request fails. The engine preserves the view and surviving selection on a valid model update.

## Verify

From this skill folder, run `node scripts/react-proof.mjs`. It creates a disposable Vite app in the system temp folder, installs its test tools, runs Vitest and TypeScript, builds the app, starts a preview server, and runs the browser checks. It removes the app afterward. On Windows it uses the installed Edge browser; elsewhere it lets npm download Playwright's own browser. Your app can run the same browser checks with `node scripts/check.mjs http://localhost:5173/ --skip hostile`. Omit `--skip hostile` when you also provide a hostile test page.

For step by step integration and failure handling, see [`implement-in-app.md`](../references/implement-in-app.md).
