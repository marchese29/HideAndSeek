import { create } from 'zustand';

import type { HiderGameState, SeekerGameState } from '@/types/gameplay';

type GameplayData =
  | { status: 'connecting'; role?: undefined; state?: undefined }
  | { status: 'connected'; role: 'hider'; state: HiderGameState }
  | { status: 'connected'; role: 'seeker'; state: SeekerGameState };

interface GameplayActions {
  hydrate: (role: 'hider' | 'seeker', data: HiderGameState | SeekerGameState) => void;
  reset: () => void;
}

type GameplayStore = GameplayData & GameplayActions;

const initialState: GameplayData = { status: 'connecting' };

export const useGameplayStore = create<GameplayStore>()((set) => ({
  ...initialState,

  hydrate: (role, data) => {
    if (role === 'hider') {
      set({ status: 'connected', role: 'hider', state: data as HiderGameState });
    } else {
      set({ status: 'connected', role: 'seeker', state: data as SeekerGameState });
    }
  },

  reset: () => set({ ...initialState }),
}));
