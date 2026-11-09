import type { ReactNode } from 'react';
import type { Headline } from '../inbox/headline';

/**
 * The sentence header of the Inbox and the Overview (D8): the page name as a small eyebrow `h1` (screen readers and
 * tests find the page by it), the sentence, and one line of context. `stale` marks it while a source is down.
 */
export function PageHead({
  page,
  head,
  stale,
  children,
}: {
  page: string;
  head: Headline;
  stale: boolean;
  children?: ReactNode;
}): JSX.Element {
  return (
    <header className={`page-head${stale ? ' stale' : ''}`} data-testid="page-head" data-stale={stale ? 'true' : undefined}>
      <div className="page-head-text">
        <h1 className="page-title page-eyebrow">{page}</h1>
        <p className="headline" data-testid="headline">
          {head.title}
        </p>
        <p className="headline-sub" data-testid="headline-sub">
          {head.sub}
        </p>
      </div>
      {children}
    </header>
  );
}
