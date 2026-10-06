# Implement a flow in an application

Use an approved flow model as input. Validate it against `model.schema.json` before connecting live data. The demo page shows the intended interaction. Keep this guide with the skill when copying files into an application.

In the commands, `<skill>` is the path to the flow-studio skill folder in your checkout. Your app has no copy of the skill's scripts, so commands that run them always name the `<skill>` path.

## 1. Pick the route

| Requirement | Route | Implementation |
|---|---|---|
| The app may use the flow engine's own styling and controls | Fast wrapper / library embed | `templates/flow-studio.lib.mjs` provides the full self-contained engine. |
| The app must use its own design tokens, buttons, and drawer | Native components & hooks | Pure modules (`src/`) supply geometry, layout, and trace logic to app components. |

The files are copyable source, not a published npm package. Both routes need a caller that supplies a valid `Model`; neither fetches app data for you.

---

## 2. Lock the model and data contract

1. Save the approved model as JSON. Run `node --experimental-strip-types <skill>/scripts/validate.mjs <model.json>`. Fix any reported errors.
2. Define a typed state for the app's data source: `loading`, `ready` with a `Model`, `empty`, or `error` with a user-facing message and retry action.
3. Map node IDs from immutable business keys (e.g. `order-service-uuid`). Map link IDs from immutable relation keys. Never use array indices or volatile titles.
4. Keep absent values absent. Do not turn a missing measurement into `0`. Use state words and timestamps (`asOf`) to distinguish measured data from declarations.
5. On refresh error, keep the last valid model visible and show a notification banner. On a valid refresh, pass the new model with stable IDs so `engine.update(model)` preserves pan, zoom, and active selection.
6. Render all model strings as plain text. Never use raw `innerHTML` for titles, subtitles, or labels.

---

## 3. Test-first workflow in the target app

1. **Verify skill tests:** Run the test suite:
   ```bash
   node --experimental-strip-types --no-warnings --test "src/*.test.ts" "scripts/lib/*.test.mjs"
   ```
2. **Author mapping test:** Write an app test verifying the data-to-model mapper produces stable IDs, preserves absent fields, and handles loading/error states. See the test fail before implementing the mapper.
3. **Author component test:** Write a test verifying component mount, node selection callback, and update behavior.
4. **Implement iteratively:** Implement mapping and component wiring, re-running the focused test after each step until green.

---

## 4. Integration guides by framework

### A. React

Copy `templates/flow-studio.lib.mjs`, `templates/flow-studio.lib.d.mts`, `templates/flow-studio.css`, `react/`, and `src/` into the app, keeping the relative layout.

```tsx
import React, { useEffect, useRef } from "react";
import { FlowStudioView, FlowLoading, FlowError } from "./react/index";
import type { Model } from "./src/model";
import "./templates/flow-studio.css";

export function FlowContainer({ model, status, error, onRetry }: { model?: Model; status: string; error?: string; onRetry: () => void }) {
  const [selectedId, setSelectedId] = React.useState<string | null>(null);

  if (status === "loading") return <FlowLoading />;
  if (status === "error") return <FlowError message={error!} onRetry={onRetry} />;
  if (!model || model.nodes.length === 0) return <div>No data available</div>;

  return (
    <div style={{ height: "80vh", width: "100%" }}>
      <FlowStudioView
        model={model}
        onSelect={(id) => setSelectedId(id)}
      />
    </div>
  );
}
```

### B. Vue (Vue 3 / Vite)

Copy `templates/flow-studio.lib.mjs`, `templates/flow-studio.lib.d.mts`, and `templates/flow-studio.css` to your application assets directory.

```vue
<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch } from "vue";
import { mount } from "../assets/flow-studio.lib.mjs";
import "../assets/flow-studio.css";

const props = defineProps<{ model: any }>();
const emit = defineEmits(["select"]);
const containerRef = ref<HTMLDivElement | null>(null);
let engineInstance: any = null;

onMounted(() => {
  if (containerRef.value && props.model) {
    engineInstance = mount(containerRef.value, props.model, {
      onSelect: (id: string | null) => emit("select", id)
    });
  }
});

watch(() => props.model, (newModel) => {
  if (engineInstance && newModel) {
    engineInstance.update(newModel);
  }
});

onBeforeUnmount(() => {
  if (engineInstance) {
    engineInstance.destroy();
    engineInstance = null;
  }
});
</script>

<template>
  <div ref="containerRef" class="flow-container"></div>
</template>

<style scoped>
.flow-container { width: 100%; height: 80vh; position: relative; }
</style>
```

### C. Svelte (Svelte 4 / 5)

Copy the same library files as for Vue. The import is aliased because Svelte 5 exports its own `mount`.

```svelte
<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { mount as mountFlow } from "./flow-studio.lib.mjs";
  import "./flow-studio.css";

  export let model: any;
  export let onSelect: (id: string | null) => void = () => {};

  let container: HTMLDivElement;
  let engine: any;

  onMount(() => {
    engine = mountFlow(container, model, { onSelect });
  });

  $: if (engine && model) {
    engine.update(model);
  }

  onDestroy(() => {
    if (engine) engine.destroy();
  });
</script>

<div bind:this={container} class="flow-container"></div>

<style>
  .flow-container { width: 100%; height: 80vh; position: relative; }
</style>
```

### D. Vanilla HTML & JavaScript

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <link rel="stylesheet" href="./templates/flow-studio.css">
  <style>
    #flowHost { width: 100vw; height: 100vh; }
  </style>
</head>
<body>
  <div id="flowHost"></div>
  <script type="module">
    import { mount } from "./templates/flow-studio.lib.mjs";

    const response = await fetch("/api/lineage-model");
    const model = await response.json();

    const engine = mount(document.getElementById("flowHost"), model, {
      onSelect: (selectedId) => {
        console.log("Selected node:", selectedId);
      }
    });

    // Expose for external live event updates
    window.updateFlow = (newModel) => engine.update(newModel);
  </script>
</body>
</html>
```

---

## 5. State synchronization and host events

`mount()` returns the engine API, and every mount also publishes the same API object on `window.FlowStudio`. Hold the value that `mount()` returns in a variable named `engine` in the examples below:

1. **Selection listening:** pass `onSelect(nodeId: string | null)` as a mount option to receive updates when a user selects a card or chip, or clears the selection.
2. **Programmatic selection:** call `engine.select(nodeId)` (or `window.FlowStudio.select(nodeId)`) to focus and inspect a node from outside the canvas, for example from an app table row.
3. **Reading active state:** call `engine.selected()`, `engine.view()`, or `engine.mode()` to read the current canvas state.
4. **Live topology updates:** call `engine.update(newModel)` to refresh node metrics, statuses, or structure without losing the user's pan and zoom. A model that fails validation is rejected, the last good graph stays, and the engine shows a banner.

In the React wrapper route the engine instance is private to `FlowStudioView`: use the `onSelect` prop for selection changes and drive new data through the `model` prop (the wrapper calls `update` itself). Use `window.FlowStudio` for a direct call only while exactly one view is mounted.

---

## 6. Verifying the app in browser check harness

Run the skill's check harness against your local dev server:

```bash
node <skill>/scripts/check.mjs http://127.0.0.1:5173/flow --out shots --channel msedge --skip hostile
```

The harness is not copied into your app, so the command always names the `<skill>` path. Run it from a folder whose `node_modules` resolves `playwright`.

- When tests fail, inspect the screenshot in `shots/` and read the error detail.
- Ensure the app container provides at least 540px height for desktop viewports.
- `--skip` takes a comma-separated list of groups (`notes`, `playback`, `update`, `hostile`). Skip a group only when the app intentionally omits that feature. Record every skipped group in your verification notes. Never treat a skipped check as a pass.
