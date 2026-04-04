import { useEffect, useRef, useState } from 'react';
import { AppState } from 'react-native';
import EventSource, { type EventSourceEvent } from 'react-native-sse';

import { API_BASE_URL } from '@/api/client';
import { useAppStore } from '@/store';
import { useGameplayStore } from '@/stores/gameplayStore';
import type { HiderGameState, PlayerLocationDelta, SeekerGameState } from '@/types/gameplay';

type GameplayEventType = 'game_state' | 'player_location';

type SSEEvent = EventSourceEvent<GameplayEventType, GameplayEventType>;

function parseData<T>(event: SSEEvent): T | null {
  if (!event.data) return null;
  return JSON.parse(event.data) as T;
}

const BASE_RECONNECT_MS = 1_000;
const MAX_RECONNECT_MS = 30_000;

/**
 * Opens a role-aware SSE connection to the gameplay state stream and
 * hydrates the GameplayStore from the server snapshot.
 *
 * Returns whether the connection is currently live.
 */
export function useGameplayEvents(gameId: string): { connected: boolean } {
  const playerId = useAppStore((s) => s.playerId);
  const playerSecret = useAppStore((s) => s.playerSecret);
  const role = useAppStore((s) => s.role);
  const [connected, setConnected] = useState(false);
  const esRef = useRef<EventSource<GameplayEventType> | null>(null);
  const retriesRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const closedRef = useRef(false);

  useEffect(() => {
    if (!role) return;

    closedRef.current = false;

    function connect() {
      if (closedRef.current) return;

      esRef.current?.close();

      const endpoint = role === 'hider' ? 'hider-state' : 'seeker-state';
      const url = `${API_BASE_URL}/games/${gameId}/${endpoint}`;
      const es = new EventSource<GameplayEventType>(url, {
        headers: { 'x-player-id': playerId!, 'x-player-secret': playerSecret! },
      });
      esRef.current = es;

      es.addEventListener('open', () => {
        setConnected(true);
        retriesRef.current = 0;
      });

      es.addEventListener('error', () => {
        setConnected(false);
        useGameplayStore.getState().reset();
        if (closedRef.current) return;
        scheduleReconnect();
      });

      es.addEventListener('game_state', (event) => {
        const data = parseData<HiderGameState | SeekerGameState>(event);
        if (data) {
          useGameplayStore.getState().hydrate(role!, data);
        }
      });

      es.addEventListener('player_location', (event) => {
        const data = parseData<PlayerLocationDelta>(event);
        if (data) {
          useGameplayStore
            .getState()
            .updatePlayerLocation(data.id, data.coordinates, data.timestamp);
        }
      });
    }

    function scheduleReconnect() {
      if (closedRef.current) return;
      esRef.current?.close();
      const delay = Math.min(BASE_RECONNECT_MS * 2 ** retriesRef.current, MAX_RECONNECT_MS);
      retriesRef.current += 1;
      reconnectTimerRef.current = setTimeout(connect, delay);
    }

    connect();

    const subscription = AppState.addEventListener('change', (state) => {
      if (state === 'active' && !closedRef.current) {
        retriesRef.current = 1;
        scheduleReconnect();
      }
    });

    return () => {
      closedRef.current = true;
      subscription.remove();
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      esRef.current?.close();
      esRef.current = null;
      useGameplayStore.getState().reset();
    };
  }, [gameId, playerId, playerSecret, role]);

  return { connected };
}
