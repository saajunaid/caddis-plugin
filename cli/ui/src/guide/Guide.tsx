import { useState } from 'react';
import markSvg from '../brand/mark.svg?raw';
import type { HubState } from '../types';
import {
  buildGuide,
  guideStatus,
  invokeText,
  SECTION_IDS,
  SECTION_TITLES,
  type Group,
  type GuideView,
  type Section,
  type SectionId,
} from './model';
import './guide.css';

export const MISSING_TEXT = 'Guide data is not ready yet. The hub collects it in the first minute.';
export const UPDATE_HINT = 'npm i -g @caddis/cli@latest';

// The mark is our own static file, imported at build time. It holds no script.
const MARK_HTML = markSvg.replace('<svg ', '<svg class="caddis-mark-build" ');

function Chip({ children, tone }: { children: string; tone?: string }): JSX.Element {
  return <span className={`guide-chip${tone ? ` ${tone}` : ''}`}>{children}</span>;
}

function Entry({ name, purpose, invoke, chips }: { name: string; purpose: string; invoke: string; chips: JSX.Element[] }): JSX.Element {
  return (
    <li className="guide-entry" data-testid="guide-entry">
      <div className="guide-entry-head">
        <span className="guide-entry-name">{name}</span>
        {chips}
      </div>
      {purpose && <p className="guide-entry-purpose">{purpose}</p>}
      {invoke && <code className="guide-entry-invoke">{invoke}</code>}
    </li>
  );
}

function Groups<T>({ section, showTitle, render }: { section: Section<T>; showTitle: boolean; render: (e: T) => JSX.Element }): JSX.Element {
  return (
    <>
      {section.groups.map((g: Group<T>) => (
        <div className="guide-group" key={g.id}>
          {showTitle && <h3 className="guide-group-title">{g.title}</h3>}
          <ul className="guide-list">{g.entries.map(render)}</ul>
        </div>
      ))}
    </>
  );
}

function Block({ id, section, filtered, children }: { id: SectionId; section: Section<unknown>; filtered: boolean; children: JSX.Element }): JSX.Element {
  return (
    <section className="guide-section" id={`guide-${id}`} aria-labelledby={`guide-h-${id}`} data-testid={`guide-section-${id}`}>
      <h2 className="guide-section-title" id={`guide-h-${id}`}>
        {SECTION_TITLES[id]} <span className="guide-count" data-testid={`guide-count-${id}`}>{section.total}</span>
        {filtered && (
          <span className="guide-shown" data-testid={`guide-shown-${id}`}>
            {section.shown} of {section.total}
          </span>
        )}
      </h2>
      {id === 'runtimes' && <p className="guide-note">caddis install and caddis update put these on each runtime.</p>}
      {section.shown === 0 && filtered ? <p className="guide-none">No match in this section.</p> : children}
    </section>
  );
}

function Sections({ view, filter }: { view: GuideView; filter: string }): JSX.Element {
  const filtered = filter.trim() !== '';
  const shown = SECTION_IDS.reduce((n, id) => n + view[id].shown, 0);
  return (
    <>
      {filtered && shown === 0 && (
        <p className="notice" data-testid="guide-nomatch">
          Nothing matches <code className="cmd">{filter.trim()}</code>.
        </p>
      )}
      <Block id="commands" section={view.commands} filtered={filtered}>
        <Groups
          section={view.commands}
          showTitle
          render={(c) => (
            <Entry
              key={c.name}
              name={c.name}
              purpose={c.description}
              invoke={invokeText('command', c)}
              chips={c.daily ? [<Chip key="d" tone="good">daily</Chip>] : []}
            />
          )}
        />
      </Block>
      <Block id="agents" section={view.agents} filtered={filtered}>
        <Groups
          section={view.agents}
          showTitle={false}
          render={(a) => (
            <Entry
              key={a.name}
              name={a.name}
              purpose={a.description}
              invoke={invokeText('agent', a)}
              chips={[
                a.writes ? <Chip key="w" tone="warn">writes files</Chip> : <Chip key="r">read only</Chip>,
                ...(a.model ? [<Chip key="m">{a.model}</Chip>] : []),
              ]}
            />
          )}
        />
      </Block>
      <Block id="skills" section={view.skills} filtered={filtered}>
        <Groups
          section={view.skills}
          showTitle
          render={(s) => (
            <Entry key={s.name} name={s.name} purpose={s.description} invoke={invokeText('skill', s)} chips={s.core ? [<Chip key="c" tone="good">core</Chip>] : []} />
          )}
        />
      </Block>
      <Block id="hooks" section={view.hooks} filtered={filtered}>
        <Groups
          section={view.hooks}
          showTitle
          render={(h) => (
            <Entry key={`${h.event}${h.matcher}${h.handler}`} name={h.handler} purpose={`Matcher: ${h.matcher}`} invoke={invokeText('hook', h)} chips={[]} />
          )}
        />
      </Block>
      <Block id="runtimes" section={view.runtimes} filtered={filtered}>
        <Groups
          section={view.runtimes}
          showTitle={false}
          render={(r) => (
            <Entry key={r.name} name={r.name} purpose={`Receives: ${r.kinds.join(', ')}`} invoke="" chips={[]} />
          )}
        />
      </Block>
    </>
  );
}

function State({ title, children }: { title: string; children: JSX.Element | string }): JSX.Element {
  return (
    <div className="notice" data-testid="guide-state" aria-live="polite">
      <h2 className="guide-state-title">{title}</h2>
      <p>{children}</p>
    </div>
  );
}

export function Guide({ guide, versions }: { guide: unknown; versions: HubState['versions'] }): JSX.Element {
  const [filter, setFilter] = useState('');
  const status = guideStatus(guide);
  const view = status.kind === 'ok' ? buildGuide(status.guide, filter) : null;

  const jump = (id: SectionId): void => {
    document.getElementById(`guide-${id}`)?.scrollIntoView({ block: 'start', behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  };

  let body: JSX.Element;
  if (status.kind === 'missing') body = <State title="Guide data missing">{MISSING_TEXT}</State>;
  else if (status.kind === 'error') {
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
  } else {
    body = <Sections view={view!} filter={filter} />;
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
      {g && (
        <div className="guide-tools">
          <label className="guide-filter">
            <span className="guide-filter-label">Filter the guide</span>
            <input
              type="search"
              className="guide-filter-input"
              value={filter}
              placeholder="Name, purpose, stage or hook"
              onChange={(e) => setFilter(e.target.value)}
              data-testid="guide-filter"
            />
          </label>
          <nav className="guide-chips" aria-label="Guide sections">
            {SECTION_IDS.map((id) => (
              <button type="button" className="guide-jump" key={id} onClick={() => jump(id)}>
                {SECTION_TITLES[id]}
              </button>
            ))}
          </nav>
          <p className="guide-note">Invoke forms are for Claude Code. Other runtimes list the same names in their own way.</p>
        </div>
      )}
      {body}
    </>
  );
}
