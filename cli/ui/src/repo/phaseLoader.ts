import { createContext } from 'react';

export type PhaseLoader = (repoPath: string, planPath: string, key: string) => Promise<{ text: string }>;

export const PhaseLoaderContext = createContext<PhaseLoader | null>(null);
