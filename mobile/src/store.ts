import AsyncStorage from '@react-native-async-storage/async-storage';
import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';

interface AppState {
  gameId: string | null;
  playerId: string | null;
  playerSecret: string | null;

  setSession: (gameId: string, playerId: string, playerSecret: string) => void;
  clearSession: () => void;
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      gameId: null,
      playerId: null,
      playerSecret: null,

      setSession: (gameId, playerId, playerSecret) => set({ gameId, playerId, playerSecret }),
      clearSession: () => set({ gameId: null, playerId: null, playerSecret: null }),
    }),
    {
      name: 'app-store',
      version: 1,
      storage: createJSONStorage(() => AsyncStorage),
      partialize: (state) => ({
        gameId: state.gameId,
        playerId: state.playerId,
        playerSecret: state.playerSecret,
      }),
      migrate: () => ({ gameId: null, playerId: null, playerSecret: null }),
    },
  ),
);
