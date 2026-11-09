import { useEffect, useMemo, useRef } from 'react';
import { guideHref } from '../shell/route';
import type { Guide } from './model';
import { wallModel, type WallRow } from './wall';

function Row({ row }: { row: WallRow }): JSX.Element {
  const label = row.kind === 'command' ? `/${row.name}` : row.name;
  return (
    <div className="gw-row">
      <a className={row.daily ? 'gw-name is-daily' : 'gw-name'} href={guideHref('details', row.anchor)}>
        {label}
      </a>
      {' '}
      <span className="gw-blurb">{row.blurb}</span>
    </div>
  );
}

const MIN_SCALE = 0.6;
const SCALE_STEP = 0.04;

/** Shrink the card text until no column spills past the sheet, so a growing guide never clips on the printout. */
function fitCards(cards: HTMLElement): void {
  let scale = 1;
  cards.style.setProperty('--gw-scale', '1');
  while (cards.scrollWidth > cards.clientWidth + 1 && scale > MIN_SCALE) {
    scale = Math.round((scale - SCALE_STEP) * 100) / 100;
    cards.style.setProperty('--gw-scale', String(scale));
  }
}

export function WallPoster({ guide }: { guide: Guide }): JSX.Element {
  const m = useMemo(() => wallModel(guide), [guide]);
  const cardsRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const fit = (): void => {
      if (cardsRef.current) fitCards(cardsRef.current);
    };
    fit();
    // The bundled faces swap in after the first fit and change the text width: fit again once they load.
    let live = true;
    void document.fonts?.ready.then(() => {
      if (live) fit();
    });
    return () => {
      live = false;
    };
  }, [m]);
  const stats: [string | number, string][] = [
    [m.counts.commands, 'commands'],
    [m.counts.agents, 'agents'],
    [m.counts.skills, 'skills'],
    [m.counts.hooks, 'hooks'],
    [m.version, 'version'],
  ];
  return (
    <div className="gw" data-testid="guide-wall">
      <div className="gw-bar">
        <p>One A4 landscape sheet, built from the installed guide data. It updates when caddis updates.</p>
        <button type="button" className="gw-print" onClick={() => window.print()}>
          Print
        </button>
      </div>
      <div className="gw-sheet" data-testid="guide-wall-sheet">
        <header className="gw-head">
          <div>
            <span className="gw-brand">
              cad<span>dis</span>
            </span>
            <span className="gw-tag">
              the dev harness — type <b>/name</b> in a session · full name <b>/caddis:name</b> · ★ = daily
            </span>
          </div>
          <div className="gw-stats">
            {stats.map(([value, label]) => (
              <div key={label}>
                <b>{value}</b>
                {label}
              </div>
            ))}
          </div>
        </header>
        <div className="gw-loop">
          {m.loop.map((r) => (
            <a key={r.name} className="gw-step" href={guideHref('details', r.anchor)}>
              <b>/{r.name}</b>
              <span>{r.blurb}</span>
            </a>
          ))}
        </div>
        <div className="gw-cards" ref={cardsRef}>
          {m.cards.map((card) => (
            <section key={card.id} className={`gw-card gw-${card.id}`}>
              <h2>
                {card.label} <small>{card.sub}</small>
              </h2>
              {card.rows.map((r) => (
                <Row key={`${r.kind}-${r.name}`} row={r} />
              ))}
            </section>
          ))}
        </div>
        <footer className="gw-foot">
          <span>
            Built from caddis {m.version} · generated {m.generated}. Click any name for its details.
          </span>
          <span>
            Day: <b>/catchup</b> → work → <b>/handoff</b>
          </span>
        </footer>
      </div>
    </div>
  );
}
