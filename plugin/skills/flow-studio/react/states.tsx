import type { Model } from "../src/model.ts";

export function FlowLoading() {
  return <p role="status">Loading flow…</p>;
}

export function FlowEmpty({ model }: { model: Model }) {
  return model.nodes.length === 0 ? <p role="status">No flow items to show.</p> : null;
}

export function FlowError({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return <div role="alert"><p>{message}</p>{onRetry && <button type="button" onClick={onRetry}>Retry</button>}</div>;
}
