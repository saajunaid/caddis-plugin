import { useMemo, useState } from 'react';
import { guideHref } from '../shell/route';
import type { Guide } from './model';
import { mapMatch, mapMatchCount, mapModel, type MapStage } from './map';

const dimClass = (base: string, query: string, search: string): string =>
  mapMatch(query, search) ? base : `${base} gm-dim`;

function Stage({ stage, query, arrow }: { stage: MapStage; query: string; arrow: boolean }): JSX.Element {
  return (
    <section className={`gm-stage gm-s-${stage.id}${arrow ? ' has-arrow' : ''}`} aria-label={stage.label}>
      <h3>
        {stage.label} <small>{stage.sub}</small>
        <span className="gm-count">{stage.count}</span>
      </h3>
      <ul className="gm-list">
        {stage.commands.map((c) => (
          <li key={c.name} className={dimClass('gm-item', query, c.search)}>
            <a className={c.daily ? 'gm-name is-daily' : 'gm-name'} href={guideHref('details', c.anchor)}>
              /{c.name}
            </a>
            <span className="gm-blurb">{c.blurb}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function PluginMap({ guide }: { guide: Guide }): JSX.Element {
  const m = useMemo(() => mapModel(guide), [guide]);
  const [query, setQuery] = useState('');
  const filtered = query.trim() !== '';
  const matches = useMemo(() => mapMatchCount(m, query), [m, query]);
  const stats: [string | number, string][] = [
    [m.counts.commands, 'commands'],
    [m.counts.agents, 'agents'],
    [m.counts.skills, 'skills'],
    [m.counts.hookEvents, 'hook events'],
    [m.counts.hookScripts, 'hook scripts'],
    [m.counts.runtimes, 'runtimes'],
  ];
  return (
    <div className="gm" data-testid="guide-map">
      <div className="gm-bar">
        <label className="gm-filter">
          <span className="guide-filter-label">Filter the map</span>
          <input
            className="guide-filter-input"
            type="search"
            value={query}
            placeholder="name, word or model"
            data-testid="guide-map-filter"
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <p className="gm-matches" aria-live="polite" data-testid="guide-map-matches">
          {filtered ? `${matches} ${matches === 1 ? 'match' : 'matches'}` : ''}
        </p>
        <button type="button" className="gm-print" onClick={() => window.print()}>
          Print
        </button>
      </div>
      <div className="gm-sheet" data-testid="guide-map-sheet">
        <header className="gm-head">
          <div>
            <p className="gm-eyebrow">
              caddis {m.version} · generated {m.generated}
            </p>
            <h2 className="gm-title">caddis plugin map</h2>
            <p className="gm-lede">
              What the plugin puts into a session: the commands you type, the hooks that run by themselves, the agents, the
              skills, and where it is installed. Click any name for its details.
            </p>
          </div>
          <dl className="gm-stats">
            {stats.map(([value, label]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
        </header>

        {m.loop.length > 0 && (
          <section className="gm-section" aria-label="The daily loop">
            <h2 className="gm-h">
              The daily loop <small>★ = a daily command</small>
            </h2>
            <div className="gm-loop">
              {m.loop.map((s, i) => (
                <Stage key={s.id} stage={s} query={query} arrow={i < m.loop.length - 1} />
              ))}
            </div>
          </section>
        )}

        {m.support.length > 0 && (
          <section className="gm-section" aria-label="Support lanes">
            <h2 className="gm-h">
              Support lanes <small>around the loop</small>
            </h2>
            <div className="gm-lanes">
              {m.support.map((s) => (
                <Stage key={s.id} stage={s} query={query} arrow={false} />
              ))}
            </div>
          </section>
        )}

        {m.hooks.length > 0 && (
          <section className="gm-section" aria-label="Hooks across a session">
            <h2 className="gm-h">
              Hooks across a session <small>run by themselves, in the order a session fires them</small>
            </h2>
            <ol className="gm-timeline">
              {m.hooks.map((h) => (
                <li key={h.event} className={dimClass('gm-event', query, h.search)}>
                  <a className="gm-name" href={guideHref('details', h.anchor)}>
                    {h.event}
                  </a>
                  <span className="gm-matcher">{h.matchers.join(' · ')}</span>
                  <ul className="gm-handlers">
                    {h.handlers.map((name) => (
                      <li key={name}>{name}</li>
                    ))}
                  </ul>
                </li>
              ))}
            </ol>
          </section>
        )}

        {m.agents.length > 0 && (
          <section className="gm-section" aria-label="Agents">
            <h2 className="gm-h">
              Agents <small>say &quot;use the … agent&quot;</small>
            </h2>
            <div className="gm-agents">
              {m.agents.map((a) => (
                <div key={a.name} className={dimClass('gm-agent', query, a.search)}>
                  <div className="gm-agent-head">
                    <a className="gm-name" href={guideHref('details', a.anchor)}>
                      {a.name}
                    </a>
                    {a.model && <span className="gm-badge gm-model">{a.model}</span>}
                    {a.writes && <span className="gm-badge gm-writes">writes files</span>}
                  </div>
                  <span className="gm-blurb">{a.blurb}</span>
                </div>
              ))}
            </div>
          </section>
        )}

        {m.skills.length > 0 && (
          <section className="gm-section" aria-label="Skills">
            <h2 className="gm-h">
              Skills <small>by family · core skills first</small>
            </h2>
            <div className="gm-families">
              {m.skills.map((f) => (
                <div key={f.id} className="gm-family">
                  <h3>
                    <a href={guideHref('details', f.anchor)}>{f.id}</a>
                    <span className="gm-count">{f.count}</span>
                  </h3>
                  <div className="gm-chips">
                    {f.skills.map((s) => (
                      <a
                        key={s.name}
                        className={dimClass(s.core ? 'gm-chip is-core' : 'gm-chip', query, s.search)}
                        href={guideHref('details', s.anchor)}
                      >
                        {s.name}
                      </a>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {m.runtimes.length > 0 && (
          <section className="gm-section" aria-label="Runtimes">
            <h2 className="gm-h">
              Runtimes <small>where caddis is installed</small>
            </h2>
            <div className="gm-runtimes">
              {m.runtimes.map((r) => (
                <a key={r.name} className={dimClass('gm-runtime', query, r.search)} href={guideHref('details', 'guide-runtimes')}>
                  <b>{r.name}</b>
                  <span>{r.kinds.join(' · ')}</span>
                </a>
              ))}
            </div>
          </section>
        )}

        <footer className="gm-foot">
          Built from caddis {m.version} · generated {m.generated}. It updates when caddis updates.
        </footer>
      </div>
    </div>
  );
}
