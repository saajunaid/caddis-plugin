/** The first load: grey shapes where the page will be, so the layout does not jump when the data comes. */
export function LoadingSkeleton(): JSX.Element {
  return (
    <div className="skeleton" data-testid="loading" aria-busy="true" aria-label="Loading">
      <div className="sk-line sk-title" />
      <div className="sk-block" />
      <div className="sk-block" />
    </div>
  );
}

/** The hub did not answer the first load. Polling retries by itself; the button retries now. */
export function LoadError({ onRetry }: { onRetry: () => void }): JSX.Element {
  return (
    <div className="notice" data-testid="load-error" role="status">
      <p>The hub did not answer. Retrying.</p>
      <button type="button" className="btn" onClick={onRetry}>
        Retry now
      </button>
    </div>
  );
}
