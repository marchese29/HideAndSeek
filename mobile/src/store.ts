import AsyncStorage from '@react-native-async-storage/async-storage';
import { randomUUID } from 'expo-crypto';
import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';

interface AppState {
  clientId: string;
  gameId: string | null;
  playerId: string | null;

  setSession: (gameId: string, playerId: string) => void;
  clearSession: () => void;
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      clientId: randomUUID(),
      gameId: null,
      playerId: null,

      setSession: (gameId, playerId) => set({ gameId, playerId }),
      clearSession: () => set({ gameId: null, playerId: null }),
    }),
    {
      name: 'app-store',
      storage: createJSONStorage(() => AsyncStorage),
      partialize: (state) => ({ clientId: state.clientId }),
    },
  ),
);
