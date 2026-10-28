import { useEffect, useState } from 'react';
import { loadMotion, saveMotion, type MotionChoice } from './motion';

/** The Motion choice, applied as `data-motion` on <html> so the CSS picks the moving or the still logo. */
export function useMotion(): [MotionChoice, (m: MotionChoice) => void] {
  const [choice, setChoice] = useState<MotionChoice>(() => loadMotion());
  useEffect(() => {
    document.documentElement.dataset.motion = choice;
  }, [choice]);
  return [
    choice,
    (m) => {
      saveMotion(m);
      setChoice(m);
    },
  ];
}
