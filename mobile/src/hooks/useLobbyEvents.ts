import { useQueryClient } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Alert, AppState } from 'react-native';
import EventSource, { type EventSourceEvent } from 'react-native-sse';

import { API_BASE_URL } from '@/api/client';
import type { components } from '@/api/schema';
import { useAppStore } from '@/store';
import { createSequenceTracker } from '@/utils/sseSequencing';

type GameResponse = components['schemas']['GameResponse'];
type PlayerResponse = components['schemas']['PlayerResponse'];

type LobbyEventType =
  | 'game_state'
  | 'player_joined'
  | 'player_updated'
  | 'player_left'
  | 'host_changed'
  | 'game_started';

type SSEEvent = EventSourceEvent<LobbyEventType, LobbyEventType>;

function parseData<T>(event: SSEEvent): T | null {
  if (!event.data) return null;
  return JSON.parse(event.data) as T;
}

const BASE_RECONNECT_MS = 1_000;
const MAX_RECONNECT_MS = 30_000;

/**
 * Opens an SSE connection to the lobby event stream and keeps the
 * TanStack Query cache in sync with real-time server events.
 *
 * Returns whether the connection is currently live.
 */
export function useLobbyEvents(gameId: string): { connected: boolean } {
  const queryClient = useQueryClient();
  const playerId = useAppStore((s) => s.playerId);
  const playerSecret = useAppStore((s) => s.playerSecret);
  const [connected, setConnected] = useState(false);
  const esRef = useRef<EventSource<LobbyEventType> | null>(null);
  const retriesRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const closedRef = useRef(false);

  const refetchGame = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: ['game', gameId] });
  }, [queryClient, gameId]);

  useEffect(() => {
    closedRef.current = false;

    function connect() {
      if (closedRef.current) return;

      // Clean up previous connection if any
      esRef.current?.close();

      const url = `${API_BASE_URL}/games/${gameId}/lobby/events`;
      const es = new EventSource<LobbyEventType>(url, {
        headers: { 'x-player-id': playerId!, 'x-player-secret': playerSecret! },
      });
      esRef.current = es;

      const queryKey = ['game', gameId];
      const seq = createSequenceTracker({
        onGap: ({ expected, got }) => {
          console.warn('[lobby SSE] gap detected', { expected, got });
          scheduleReconnect();
        },
        onInvalid: ({ lastEventId }) => {
          console.warn('[lobby SSE] missing/invalid lastEventId', { lastEventId });
          scheduleReconnect();
        },
        onStale: ({ last, got }) => {
          console.warn('[lobby SSE] stale event dropped', { last, got });
        },
      });

      es.addEventListener('open', () => {
        setConnected(true);
        seq.reset();
        // If this was a reconnect, re-fetch to catch any missed events
        if (retriesRef.current > 0) {
          void refetchGame();
        }
        retriesRef.current = 0;
      });

      es.addEventListener('error', () => {
        setConnected(false);
        seq.reset();
        if (closedRef.current) return;
        scheduleReconnect();
      });

      es.addEventListener(
        'game_state',
        seq.wrap((event) => {
          const game = parseData<GameResponse>(event);
          if (game) queryClient.setQueryData(queryKey, game);
        }),
      );

      es.addEventListener(
        'player_joined',
        seq.wrap((event) => {
          const player = parseData<PlayerResponse>(event);
          if (!player) return;
          queryClient.setQueryData<GameResponse>(queryKey, (old) => {
            if (!old) return old;
            const exists = old.players.some((p) => p.id === player.id);
            if (exists) return old;
            return { ...old, players: [...old.players, player] };
          });
        }),
      );

      es.addEventListener(
        'player_updated',
        seq.wrap((event) => {
          const player = parseData<PlayerResponse>(event);
          if (!player) return;
          queryClient.setQueryData<GameResponse>(queryKey, (old) => {
            if (!old) return old;
            return {
              ...old,
              players: old.players.map((p) => (p.id === player.id ? player : p)),
            };
          });
        }),
      );

      es.addEventListener(
        'player_left',
        seq.wrap((event) => {
          const data = parseData<{ player_id: string }>(event);
          if (!data) return;
          if (data.player_id === playerId) {
            Alert.alert('Removed', 'You were removed from the game.');
            useAppStore.getState().clearSession();
            es.close();
            if (router.canDismiss()) router.dismissAll();
            router.replace('/');
            return;
          }
          queryClient.setQueryData<GameResponse>(queryKey, (old) => {
            if (!old) return old;
            return {
              ...old,
              players: old.players.filter((p) => p.id !== data.player_id),
            };
          });
        }),
      );

      es.addEventListener(
        'host_changed',
        seq.wrap((event) => {
          const data = parseData<{ new_host_player_id: string }>(event);
          if (!data) return;
          queryClient.setQueryData<GameResponse>(queryKey, (old) => {
            if (!old) return old;
            return { ...old, host_player_id: data.new_host_player_id };
          });
        }),
      );

      es.addEventListener(
        'game_started',
        seq.wrap((event) => {
          const game = parseData<GameResponse>(event);
          if (!game) return;
          queryClient.setQueryData(queryKey, game);

          // Persist role before navigating to gameplay
          const myId = useAppStore.getState().playerId;
          const me = game.players.find((p) => p.id === myId);
          if (me?.role) {
            useAppStore.getState().setRole(me.role);
          }
          router.replace(`/game/${gameId}`);
        }),
      );
    }

    function scheduleReconnect() {
      if (closedRef.current) return;
      esRef.current?.close();
      const delay = Math.min(BASE_RECONNECT_MS * 2 ** retriesRef.current, MAX_RECONNECT_MS);
      retriesRef.current += 1;
      reconnectTimerRef.current = setTimeout(connect, delay);
    }

    connect();

    // Reconnect when the app returns to the foreground
    const subscription = AppState.addEventListener('change', (state) => {
      if (state === 'active' && !closedRef.current) {
        // Force a fresh connection — stale XHR may not fire errors on resume
        retriesRef.current = 1; // signals reconnect so refetch fires
        scheduleReconnect();
      }
    });

    return () => {
      closedRef.current = true;
      subscription.remove();
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      esRef.current?.close();
      esRef.current = null;
    };
  }, [gameId, playerId, playerSecret, queryClient, refetchGame]);

  return { connected };
}
