import { Clock, Monitor, Moon, Pause, Play, Sun } from 'lucide-react';
import type { HubState } from '../types';
import { dataAgeText, clockText, quotaLow, quotaLowest, spendView } from './format';
import { MOTION_CHOICES, type MotionChoice } from './motion';
import { THEME_CHOICES, type ThemeChoice } from './theme';

const ICON = { dark: Moon, light: Sun, system: Monitor } as const;
const MOTION_ICON = { on: Play, off: Pause } as const;
const MOTION_LABEL = { on: 'motion', off: 'still' } as const;

interface Props {
  state: HubState | null;
  nowMs: number;
  theme: ThemeChoice;
  onTheme: (t: ThemeChoice) => void;
  motion: MotionChoice;
  onMotion: (m: MotionChoice) => void;
}

export function Footer({ state, nowMs, theme, onTheme, motion, onMotion }: Props): JSX.Element {
  const spend = spendView(state?.spend);
  const v = state?.versions;
  const quota = quotaLow(state);
  const left = quotaLowest(state);
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
        {left && !quota && (
          <div className="quota-line mono" data-testid="quota">
            GitHub quota {left.remaining} left ({left.account})
          </div>
        )}
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
      <div className="theme-switch" role="group" aria-label="Logo animation">
        {MOTION_CHOICES.map((m) => {
          const Icon = MOTION_ICON[m];
          return (
            <button
              key={m}
              type="button"
              className={`theme-btn${motion === m ? ' active' : ''}`}
              aria-pressed={motion === m}
              title={m === 'on' ? 'Animate the logo' : 'Stop the logo animation'}
              onClick={() => onMotion(m)}
            >
              <Icon size={15} aria-hidden="true" />
              <span>{MOTION_LABEL[m]}</span>
            </button>
          );
        })}
      </div>
    </footer>
  );
}
