import AsyncStorage from '@react-native-async-storage/async-storage';
import type * as Location from 'expo-location';
import * as TaskManager from 'expo-task-manager';

import { API_BASE_URL } from '@/api/client';

export const LOCATION_TASK_NAME = 'hideandseek-location';

interface ActiveSession {
  gameId: string;
  playerId: string;
  playerSecret: string;
}

interface PersistedStore {
  state?: {
    gameId?: string | null;
    playerId?: string | null;
    playerSecret?: string | null;
  };
}

interface LocationTaskPayload {
  locations?: Location.LocationObject[];
}

async function readSession(): Promise<ActiveSession | null> {
  try {
    const raw = await AsyncStorage.getItem('app-store');
    if (!raw) return null;
    const parsed = JSON.parse(raw) as PersistedStore;
    const s = parsed.state;
    if (!s?.gameId || !s.playerId || !s.playerSecret) return null;
    return { gameId: s.gameId, playerId: s.playerId, playerSecret: s.playerSecret };
  } catch {
    return null;
  }
}

TaskManager.defineTask<LocationTaskPayload>(LOCATION_TASK_NAME, async ({ data, error }) => {
  if (error) return;
  const locations = data?.locations;
  if (!locations || locations.length === 0) return;

  const session = await readSession();
  if (!session) return;

  const latest = locations[locations.length - 1];
  if (!latest) return;

  const body = {
    coordinates: {
      type: 'Point' as const,
      coordinates: [latest.coords.longitude, latest.coords.latitude],
    },
    timestamp: new Date().toISOString(),
  };

  try {
    await fetch(`${API_BASE_URL}/games/${session.gameId}/location`, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-player-id': session.playerId,
        'x-player-secret': session.playerSecret,
      },
      body: JSON.stringify(body),
    });
  } catch {
    // Background posts are best-effort — the OS will retry on the next fix.
  }
});
