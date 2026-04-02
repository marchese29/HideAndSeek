import AsyncStorage from '@react-native-async-storage/async-storage';
import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';

type TokenProvider = 'apns' | 'fcm';

type PlayerRole = 'hider' | 'seeker';

interface AppState {
  gameId: string | null;
  playerId: string | null;
  playerSecret: string | null;
  role: PlayerRole | null;
  pushToken: string | null;
  pushProvider: TokenProvider | null;

  setSession: (gameId: string, playerId: string, playerSecret: string) => void;
  clearSession: () => void;
  setRole: (role: PlayerRole) => void;
  setPushToken: (token: string, provider: TokenProvider) => void;
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      gameId: null,
      playerId: null,
      playerSecret: null,
      role: null,
      pushToken: null,
      pushProvider: null,

      setSession: (gameId, playerId, playerSecret) => set({ gameId, playerId, playerSecret }),
      clearSession: () => set({ gameId: null, playerId: null, playerSecret: null, role: null }),
      setRole: (role) => set({ role }),
      setPushToken: (token, provider) => set({ pushToken: token, pushProvider: provider }),
    }),
    {
      name: 'app-store',
      version: 2,
      storage: createJSONStorage(() => AsyncStorage),
      partialize: (state) => ({
        gameId: state.gameId,
        playerId: state.playerId,
        playerSecret: state.playerSecret,
        role: state.role,
      }),
      migrate: () => ({ gameId: null, playerId: null, playerSecret: null, role: null }),
    },
  ),
);
