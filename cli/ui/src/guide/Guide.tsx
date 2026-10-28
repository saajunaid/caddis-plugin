import markSvg from '../brand/mark.svg?raw';
import { guideHref } from '../shell/route';
import type { HubState } from '../types';
import { Details } from './Details';
import { Poster } from './Poster.jsx';
import { guideStatus } from './model';
import './guide.css';

export const MISSING_TEXT = 'Guide data is not ready yet. The hub collects it in the first minute.';
export const UPDATE_HINT = 'npm i -g @caddis/cli@latest';

// The mark is our own static file, imported at build time. It holds no script.
const MARK_HTML = markSvg.replace('<svg ', '<svg class="caddis-mark-build" ');

function State({ title, children }: { title: string; children: JSX.Element | string }): JSX.Element {
  return (
    <div className="notice" data-testid="guide-state" aria-live="polite">
      <h2 className="guide-state-title">{title}</h2>
      <p>{children}</p>
    </div>
  );
}

export interface GuideProps {
  guide: unknown;
  versions: HubState['versions'];
  tab?: 'poster' | 'details';
  item?: string | null;
  initialFilter?: string;
}

export function Guide({
  guide,
  versions,
  tab = 'poster',
  item = null,
  initialFilter,
}: GuideProps): JSX.Element {
  const status = guideStatus(guide);

  let body: JSX.Element;
  if (status.kind === 'missing') {
    body = <State title="Guide data missing">{MISSING_TEXT}</State>;
  } else if (status.kind === 'error') {
    body = (
      <State title="The guide could not be read">
        <>
          {status.message} Run <code className="cmd">caddis doctor</code> to check the install.
        </>
      </State>
    );
  } else if (status.kind === 'newer') {
    body = (
      <State title="The guide is newer than this hub">
        <>
          The data has schema {status.schema}. Update the hub: <code className="cmd">{UPDATE_HINT}</code>
        </>
      </State>
    );
  } else if (tab === 'poster') {
    body = <Poster guide={status.guide} />;
  } else {
    body = <Details guide={status.guide} item={item} initialFilter={initialFilter} />;
  }

  const g = status.kind === 'ok' ? status.guide : null;
  return (
    <>
      <div className="guide-hero">
        <span className="guide-mark" aria-hidden="true" dangerouslySetInnerHTML={{ __html: MARK_HTML }} />
        <div>
          <h1 className="page-title">caddis guide</h1>
          <p className="page-subtitle" data-testid="guide-version">
            {g ? `caddis ${g.version} (installed pool) · generated ${g.generated} · hub ${versions.hub}` : `hub ${versions.hub}`}
          </p>
        </div>
      </div>
      <div className="guide-tabs" role="tablist">
        <a role="tab" href={guideHref('poster')} aria-selected={tab === 'poster'}>
          Poster
        </a>
        <a role="tab" href={guideHref('details')} aria-selected={tab === 'details'}>
          Details
        </a>
      </div>
      {body}
    </>
  );
}
