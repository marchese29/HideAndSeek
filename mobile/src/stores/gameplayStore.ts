import { create } from 'zustand';

import type { GamePlayer, GeoJSONPoint, HiderGameState, SeekerGameState } from '@/types/gameplay';

interface SelfLocation {
  coordinates: GeoJSONPoint;
  timestamp: string;
}

type GameplayData =
  | { status: 'connecting'; role?: undefined; state?: undefined }
  | { status: 'connected'; role: 'hider'; state: HiderGameState }
  | { status: 'connected'; role: 'seeker'; state: SeekerGameState };

interface GameplayActions {
  hydrate: (role: 'hider' | 'seeker', data: HiderGameState | SeekerGameState) => void;
  reset: () => void;
  updateSelfLocation: (coordinates: GeoJSONPoint, timestamp: string) => void;
  updatePlayerLocation: (playerId: string, coordinates: GeoJSONPoint, timestamp: string) => void;
}

type GameplayStore = GameplayData & { selfLocation: SelfLocation | null } & GameplayActions;

const initialState: GameplayData & { selfLocation: SelfLocation | null } = {
  status: 'connecting',
  selfLocation: null,
};

/** Patch a single player's coordinates in a GamePlayer array. */
function patchPlayer(
  players: GamePlayer[],
  playerId: string,
  coordinates: GeoJSONPoint,
  timestamp: string,
): GamePlayer[] {
  let changed = false;
  const result = players.map((p) => {
    if (p.id !== playerId) return p;
    changed = true;
    return { ...p, coordinates, timestamp };
  });
  return changed ? result : players;
}

/**
 * Find the self player's timestamp from a freshly hydrated state snapshot.
 * Searches both hiders and seekers arrays for the self_player_id.
 */
function findSelfTimestamp(
  role: 'hider' | 'seeker',
  data: HiderGameState | SeekerGameState,
): string | null {
  const allPlayers: GamePlayer[] =
    role === 'hider' ? [...(data as HiderGameState).hiders, ...data.seekers] : data.seekers;

  const self = allPlayers.find((p) => p.id === data.self_player_id);
  return self?.timestamp ?? null;
}

export const useGameplayStore = create<GameplayStore>()((set) => ({
  ...initialState,

  hydrate: (role, data) => {
    set((prev) => {
      // Clear selfLocation if SSE has caught up
      let selfLocation = prev.selfLocation;
      if (selfLocation) {
        const sseTimestamp = findSelfTimestamp(role, data);
        if (sseTimestamp && sseTimestamp >= selfLocation.timestamp) {
          selfLocation = null;
        }
      }

      if (role === 'hider') {
        return { status: 'connected', role: 'hider', state: data as HiderGameState, selfLocation };
      }
      return { status: 'connected', role: 'seeker', state: data as SeekerGameState, selfLocation };
    });
  },

  reset: () => set({ ...initialState }),

  updateSelfLocation: (coordinates, timestamp) => {
    set({ selfLocation: { coordinates, timestamp } });
  },

  updatePlayerLocation: (playerId, coordinates, timestamp) => {
    set((prev) => {
      if (prev.status !== 'connected') return prev;

      if (prev.role === 'hider') {
        const state = prev.state;
        const hiders = patchPlayer(state.hiders, playerId, coordinates, timestamp);
        const seekers = patchPlayer(state.seekers, playerId, coordinates, timestamp);
        if (hiders === state.hiders && seekers === state.seekers) return prev;
        return { ...prev, state: { ...state, hiders, seekers } };
      }

      // Seeker state: hiders is RosterPlayer[] (no coordinates), only patch seekers
      const state = prev.state;
      const seekers = patchPlayer(state.seekers, playerId, coordinates, timestamp);
      if (seekers === state.seekers) return prev;
      return { ...prev, state: { ...state, seekers } };
    });
  },
}));
