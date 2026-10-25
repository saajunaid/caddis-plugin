import { useEffect, useState } from 'react';
import { loadTheme, resolveTheme, saveTheme, type ThemeChoice } from './theme';

const systemDark = (): boolean => window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? true;

export function useTheme(): [ThemeChoice, (t: ThemeChoice) => void] {
  const [choice, setChoice] = useState<ThemeChoice>(() => loadTheme());
  useEffect(() => {
    const apply = (): void => {
      document.documentElement.dataset.theme = resolveTheme(choice, systemDark());
    };
    apply();
    if (choice !== 'system' || !window.matchMedia) return;
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    mq.addEventListener('change', apply);
    return () => mq.removeEventListener('change', apply);
  }, [choice]);
  return [
    choice,
    (t) => {
      saveTheme(t);
      setChoice(t);
    },
  ];
}
