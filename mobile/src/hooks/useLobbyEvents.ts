import { useQueryClient } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useEffect, useRef } from 'react';
import { Alert } from 'react-native';
import EventSource, { type EventSourceEvent } from 'react-native-sse';

import { API_BASE_URL } from '@/api/client';
import type { components } from '@/api/schema';
import { useAppStore } from '@/store';

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

/**
 * Opens an SSE connection to the lobby event stream and keeps the
 * TanStack Query cache in sync with real-time server events.
 */
export function useLobbyEvents(gameId: string) {
  const queryClient = useQueryClient();
  const playerId = useAppStore((s) => s.playerId);
  const clientId = useAppStore((s) => s.clientId);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    const url = `${API_BASE_URL}/games/${gameId}/lobby/events?client_id=${clientId}`;
    const es = new EventSource<LobbyEventType>(url);
    esRef.current = es;

    const queryKey = ['game', gameId];

    es.addEventListener('game_state', (event) => {
      const game = parseData<GameResponse>(event);
      if (game) queryClient.setQueryData(queryKey, game);
    });

    es.addEventListener('player_joined', (event) => {
      const player = parseData<PlayerResponse>(event);
      if (!player) return;
      queryClient.setQueryData<GameResponse>(queryKey, (old) => {
        if (!old) return old;
        const exists = old.players.some((p) => p.id === player.id);
        if (exists) return old;
        return { ...old, players: [...old.players, player] };
      });
    });

    es.addEventListener('player_updated', (event) => {
      const player = parseData<PlayerResponse>(event);
      if (!player) return;
      queryClient.setQueryData<GameResponse>(queryKey, (old) => {
        if (!old) return old;
        return {
          ...old,
          players: old.players.map((p) => (p.id === player.id ? player : p)),
        };
      });
    });

    es.addEventListener('player_left', (event) => {
      const data = parseData<{ player_id: string }>(event);
      if (!data) return;
      if (data.player_id === playerId) {
        Alert.alert('Removed', 'You were removed from the game.');
        useAppStore.getState().clearSession();
        es.close();
        router.dismissAll();
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
    });

    es.addEventListener('host_changed', (event) => {
      const data = parseData<{ new_host_player_id: string }>(event);
      if (!data) return;
      queryClient.setQueryData<GameResponse>(queryKey, (old) => {
        if (!old) return old;
        return { ...old, host_player_id: data.new_host_player_id };
      });
    });

    es.addEventListener('game_started', (event) => {
      const game = parseData<GameResponse>(event);
      if (game) queryClient.setQueryData(queryKey, game);
      // Future: navigate to gameplay screen
      Alert.alert('Game Started', 'The game has begun!');
    });

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [gameId, clientId, playerId, queryClient]);
}
