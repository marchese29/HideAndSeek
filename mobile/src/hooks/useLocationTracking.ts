import * as Location from 'expo-location';
import { useEffect, useRef, useState } from 'react';
import { AppState } from 'react-native';

import { authHeader } from '@/api/auth';
import { api } from '@/api/client';
import { useGameplayStore } from '@/stores/gameplayStore';
import type { GeoJSONPoint } from '@/types/gameplay';

const POLL_INTERVAL_MS = 10_000;
const JITTER_STDDEV_MS = 250;

/** Normal-distributed jitter via Box-Muller transform (mean 0, stddev ±250ms). */
function jitter(): number {
  const u1 = Math.random();
  const u2 = Math.random();
  return Math.sqrt(-2 * Math.log(u1)) * Math.cos(2 * Math.PI * u2) * JITTER_STDDEV_MS;
}

/**
 * Polls the device's foreground location and reports it to the server.
 *
 * Uses `getCurrentPositionAsync` on a jittered interval rather than
 * `watchPositionAsync`, because iOS ignores `timeInterval` — it only
 * triggers on `distanceInterval`, which means a stationary player would
 * stop reporting entirely.
 *
 * Each tick adds normal-distributed jitter (±0.5s at ~2σ) to prevent
 * synchronized traffic bursts across players.
 *
 * Each fix triggers an optimistic store update (selfLocation) and a
 * fire-and-forget POST /location so the server broadcasts to other players.
 */
export function useLocationTracking(gameId: string): { permissionDenied: boolean } {
  const [permissionDenied, setPermissionDenied] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function pollLocation() {
      // Seekers don't report location during the hiding phase — no need to
      // burn GPS/battery on requests the server will reject.
      const { role, state } = useGameplayStore.getState();
      if (role === 'seeker' && state?.phase === 'hiding') {
        scheduleNext();
        return;
      }

      try {
        const location = await Location.getCurrentPositionAsync({
          accuracy: Location.Accuracy.High,
        });

        const coordinates: GeoJSONPoint = {
          type: 'Point',
          coordinates: [location.coords.longitude, location.coords.latitude],
        };
        const timestamp = new Date(location.timestamp).toISOString();

        // Update self pin only after server confirms — if the POST fails,
        // the old timestamp ages and the pin correctly turns gray.
        const { error } = await api.POST('/games/{game_id}/location', {
          params: { path: { game_id: gameId }, header: authHeader() },
          body: { coordinates, timestamp },
        });
        if (!error) {
          useGameplayStore.getState().updateSelfLocation(coordinates, timestamp);
        }
      } catch {
        // Location unavailable — skip this cycle
      }

      scheduleNext();
    }

    function scheduleNext() {
      if (cancelled) return;
      const delay = Math.max(POLL_INTERVAL_MS + jitter(), POLL_INTERVAL_MS / 2);
      timerRef.current = setTimeout(() => void pollLocation(), delay);
    }

    async function checkAndStart() {
      const { status } = await Location.getForegroundPermissionsAsync();
      if (cancelled) return;

      if (status !== 'granted') {
        setPermissionDenied(true);
        stopPolling();
        return;
      }

      setPermissionDenied(false);

      // Don't start a second poller if one is already running
      if (timerRef.current) return;

      // Fire immediately, then schedule the next with jitter
      void pollLocation();
    }

    function stopPolling() {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    }

    void checkAndStart();

    // Re-check permission on foreground resume (user may have toggled in Settings)
    const subscription = AppState.addEventListener('change', (state) => {
      if (state === 'active' && !cancelled) {
        void checkAndStart();
      }
    });

    return () => {
      cancelled = true;
      subscription.remove();
      stopPolling();
    };
  }, [gameId]);

  return { permissionDenied };
}
