import { Clock, Monitor, Moon, Sun } from 'lucide-react';
import type { HubState } from '../types';
import { dataAgeText, clockText, quotaLow, spendView } from './format';
import { THEME_CHOICES, type ThemeChoice } from './theme';

const ICON = { dark: Moon, light: Sun, system: Monitor } as const;

interface Props {
  state: HubState | null;
  nowMs: number;
  theme: ThemeChoice;
  onTheme: (t: ThemeChoice) => void;
}

export function Footer({ state, nowMs, theme, onTheme }: Props): JSX.Element {
  const spend = spendView(state?.spend);
  const v = state?.versions;
  const quota = quotaLow(state);
  return (
    <footer className="sidebar-footer">
      <div className="footer-meta">
        <div className="updated-line">
          <Clock size={14} aria-hidden="true" />
          <span data-testid="data-age">{state ? dataAgeText(state.generated_at, nowMs) : 'Waiting for data'}</span>
        </div>
        <div className="spend-box">
          <div className="spend-row">
            <span>agy spend (24 h)</span>
            <span className="mono">
              {spend.configured ? `${spend.committedEur.toFixed(2)} / ${spend.capEur.toFixed(0)} EUR` : 'no cap set'}
            </span>
          </div>
          <div
            className="meter-track"
            role="progressbar"
            aria-label="agy spend"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(spend.pct)}
          >
            <div className={`meter-fill${spend.pct >= 80 ? ' hot' : ''}`} style={{ width: `${spend.pct}%` }} />
          </div>
        </div>
        {quota && (
          <div className="quota-low" data-testid="quota-low" role="status">
            GitHub quota low: {quota.remaining} left ({quota.account})
            {quota.resetAt ? `, resets ${clockText(quota.resetAt)}` : ''}. Polling slows.
          </div>
        )}
        {v && (
          <div className="versions mono">
            hub {v.hub} | pool {v.pool ?? '-'} | plugin {v.plugin ?? '-'}
          </div>
        )}
      </div>
      <div className="theme-switch" role="group" aria-label="Theme">
        {THEME_CHOICES.map((c) => {
          const Icon = ICON[c];
          return (
            <button key={c} type="button" className={`theme-btn${theme === c ? ' active' : ''}`} aria-pressed={theme === c} title={c} onClick={() => onTheme(c)}>
              <Icon size={15} aria-hidden="true" />
              <span>{c}</span>
            </button>
          );
        })}
      </div>
    </footer>
  );
}
