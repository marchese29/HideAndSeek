import * as Location from 'expo-location';
import { useEffect, useRef, useState } from 'react';
import { AppState } from 'react-native';

import { authHeader } from '@/api/auth';
import { api } from '@/api/client';
import { LOCATION_TASK_NAME } from '@/background/locationTask';
import { useGameplayStore } from '@/stores/gameplayStore';
import type { GeoJSONPoint } from '@/types/gameplay';

const HEARTBEAT_INTERVAL_MS = 30_000;
const DISTANCE_INTERVAL_M = 25;

/**
 * GPS tracking + POST /location, foreground and background.
 *
 * Foreground: subscribes via `watchPositionAsync` on >=25m movement and runs a
 * trailing 30s heartbeat for liveness — every successful POST schedules a single
 * `setTimeout` that fires 30s later, so a steadily-moving player never sends a
 * redundant heartbeat.
 *
 * Background: a TaskManager-registered location subscription
 * (`startLocationUpdatesAsync`) takes over while the app is backgrounded/locked,
 * with a fixed `timeInterval` for liveness (JS timers are suspended in
 * background, and TaskManager has no reschedule hook). Gated on background
 * permission and on game state requiring continuous reporting (hider always,
 * seeker only during seeking phase).
 *
 * The two subscriptions are mutually exclusive — running both at once produces
 * duplicate (and often stale) fixes because TaskManager keeps a separate
 * CLLocationManager that serves cached coordinates. AppState transitions toggle
 * which one is active.
 */
export function useLocationTracking(gameId: string): { permissionDenied: boolean } {
  const [permissionDenied, setPermissionDenied] = useState(false);
  const lastKnownRef = useRef<Location.LocationObject | null>(null);

  useEffect(() => {
    let cancelled = false;
    let subscription: Location.LocationSubscription | null = null;
    let heartbeatTimer: ReturnType<typeof setTimeout> | null = null;

    async function postLocation(coordinates: GeoJSONPoint, timestamp: string): Promise<boolean> {
      const { status, role, state } = useGameplayStore.getState();
      // Don't post until SSE has hydrated — before that, role/phase are unknown
      // and a seeker would POST during hiding phase and get 409'd.
      if (status !== 'connected') return false;
      if (role === 'seeker' && state.phase === 'hiding') return false;

      try {
        const { error } = await api.POST('/games/{game_id}/location', {
          params: { path: { game_id: gameId }, header: authHeader() },
          body: { coordinates, timestamp },
        });
        if (error) return false;
        useGameplayStore.getState().updateSelfLocation(coordinates, timestamp);
        return true;
      } catch {
        return false;
      }
    }

    function scheduleHeartbeat() {
      if (cancelled) return;
      if (heartbeatTimer) clearTimeout(heartbeatTimer);
      heartbeatTimer = setTimeout(() => void tickHeartbeat(), HEARTBEAT_INTERVAL_MS);
    }

    async function handleFix(location: Location.LocationObject) {
      lastKnownRef.current = location;
      const coordinates: GeoJSONPoint = {
        type: 'Point',
        coordinates: [location.coords.longitude, location.coords.latitude],
      };
      const timestamp = new Date(location.timestamp).toISOString();
      if (await postLocation(coordinates, timestamp)) {
        scheduleHeartbeat();
      }
    }

    async function tickHeartbeat() {
      const location = lastKnownRef.current;
      if (location) {
        const coordinates: GeoJSONPoint = {
          type: 'Point',
          coordinates: [location.coords.longitude, location.coords.latitude],
        };
        await postLocation(coordinates, new Date().toISOString());
      }
      // Always reschedule — even if we had no fix or the post failed, the next
      // tick is still our liveness signal.
      scheduleHeartbeat();
    }

    function shouldRunBackground(): boolean {
      // The TaskManager subscription is a second CLLocationManager. If we run it
      // alongside watchPositionAsync in the foreground, both deliver fixes — and
      // the TaskManager one tends to serve stale cached fixes, causing the self
      // pin to bounce between old and new coordinates. Only run it when we're
      // actually backgrounded.
      if (AppState.currentState === 'active') return false;
      const s = useGameplayStore.getState();
      if (s.status !== 'connected') return false;
      if (s.role === 'hider') return true;
      return s.state.phase === 'seeking';
    }

    async function startBackground() {
      const { status } = await Location.getBackgroundPermissionsAsync();
      if (status !== 'granted') return;
      try {
        const running = await Location.hasStartedLocationUpdatesAsync(LOCATION_TASK_NAME);
        if (running) return;
        await Location.startLocationUpdatesAsync(LOCATION_TASK_NAME, {
          accuracy: Location.Accuracy.High,
          distanceInterval: DISTANCE_INTERVAL_M,
          timeInterval: HEARTBEAT_INTERVAL_MS,
          pausesUpdatesAutomatically: false,
          showsBackgroundLocationIndicator: false,
          foregroundService: {
            notificationTitle: 'HideAndSeek',
            notificationBody: 'Reporting your location for the game.',
          },
        });
      } catch {
        // If the task isn't registered yet or the OS rejects, fall back to foreground-only.
      }
    }

    async function stopBackground() {
      // Always consult the OS — the task registration survives hook remounts and
      // JS reloads, so a stale subscription from a previous lifecycle can still
      // be firing even though this hook instance never started one.
      try {
        const running = await Location.hasStartedLocationUpdatesAsync(LOCATION_TASK_NAME);
        if (running) await Location.stopLocationUpdatesAsync(LOCATION_TASK_NAME);
      } catch {
        // ignore
      }
    }

    async function syncBackground() {
      if (cancelled) return;
      if (shouldRunBackground()) await startBackground();
      else await stopBackground();
    }

    async function stopAll() {
      if (subscription) {
        subscription.remove();
        subscription = null;
      }
      if (heartbeatTimer) {
        clearTimeout(heartbeatTimer);
        heartbeatTimer = null;
      }
      await stopBackground();
    }

    async function checkAndStart() {
      const { status } = await Location.getForegroundPermissionsAsync();
      if (cancelled) return;

      if (status !== 'granted') {
        setPermissionDenied(true);
        await stopAll();
        return;
      }

      setPermissionDenied(false);

      if (!subscription) {
        subscription = await Location.watchPositionAsync(
          {
            accuracy: Location.Accuracy.High,
            distanceInterval: DISTANCE_INTERVAL_M,
          },
          (location) => {
            void handleFix(location);
          },
        );
      }

      if (!heartbeatTimer) {
        scheduleHeartbeat();
      }

      await syncBackground();
    }

    void checkAndStart();

    const appSubscription = AppState.addEventListener('change', (state) => {
      if (cancelled) return;
      if (state === 'active') {
        // Returning to foreground: re-check perms, restart watch if needed, and
        // syncBackground (called by checkAndStart) will stop the TaskManager.
        void checkAndStart();
      } else {
        // Going to background: start TaskManager so we keep reporting.
        void syncBackground();
      }
    });

    // Re-evaluate background eligibility on role/phase changes (e.g. hiding→seeking).
    const unsubscribeGameplay = useGameplayStore.subscribe(() => {
      void syncBackground();
    });

    return () => {
      cancelled = true;
      appSubscription.remove();
      unsubscribeGameplay();
      void stopAll();
    };
  }, [gameId]);

  return { permissionDenied };
}
