import { router } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { Alert, AppState } from 'react-native';
import EventSource, { type EventSourceEvent } from 'react-native-sse';

import { API_BASE_URL } from '@/api/client';
import { useAppStore } from '@/store';
import { useGameplayStore } from '@/stores/gameplayStore';
import type {
  GameDissolvedDelta,
  HiderGameState,
  HiderQuestionAnsweredDelta,
  HostChangedDelta,
  PhaseChangedDelta,
  PlayerLeftDelta,
  PlayerLocationDelta,
  QuestionAbandonedDelta,
  QuestionAnswerableDelta,
  QuestionAskedDelta,
  QuestionVetoedDelta,
  SeekerGameState,
  SeekerQuestionAnsweredDelta,
} from '@/types/gameplay';

type GameplayEventType =
  | 'game_state'
  | 'phase_changed'
  | 'player_location'
  | 'question_asked'
  | 'question_answerable'
  | 'question_answered'
  | 'question_vetoed'
  | 'question_abandoned'
  | 'player_left'
  | 'host_changed'
  | 'game_dissolved';

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

      es.addEventListener('phase_changed', (event) => {
        const data = parseData<PhaseChangedDelta>(event);
        if (data) {
          useGameplayStore.getState().applyPhaseChanged(data);
        }
      });

      es.addEventListener('player_location', (event) => {
        const data = parseData<PlayerLocationDelta>(event);
        if (data) {
          useGameplayStore
            .getState()
            .updatePlayerLocation(data.player_id, data.coordinates, data.timestamp);
        }
      });

      es.addEventListener('question_asked', (event) => {
        const data = parseData<QuestionAskedDelta>(event);
        if (data) {
          useGameplayStore.getState().setActiveQuestion(data);
        }
      });

      es.addEventListener('question_answerable', (event) => {
        const data = parseData<QuestionAnswerableDelta>(event);
        if (data) {
          useGameplayStore.getState().updateQuestionAnswerable(data);
        }
      });

      es.addEventListener('question_answered', (event) => {
        if (role === 'hider') {
          const data = parseData<HiderQuestionAnsweredDelta>(event);
          if (data) {
            useGameplayStore.getState().applyQuestionAnswered(data);
          }
        } else {
          const data = parseData<SeekerQuestionAnsweredDelta>(event);
          if (data) {
            useGameplayStore.getState().applyQuestionAnswered(data);
          }
        }
      });

      es.addEventListener('question_vetoed', (event) => {
        const data = parseData<QuestionVetoedDelta>(event);
        if (data) {
          useGameplayStore.getState().clearActiveQuestion();
        }
      });

      es.addEventListener('question_abandoned', (event) => {
        const data = parseData<QuestionAbandonedDelta>(event);
        if (data) {
          useGameplayStore.getState().clearActiveQuestion();
        }
      });

      es.addEventListener('player_left', (event) => {
        const data = parseData<PlayerLeftDelta>(event);
        if (!data) return;
        if (data.player_id === playerId) {
          // Kicked by host
          Alert.alert('Removed', 'You were removed from the game.');
          useAppStore.getState().clearSession();
          closedRef.current = true;
          es.close();
          if (router.canDismiss()) router.dismissAll();
          router.replace('/');
        } else {
          useGameplayStore.getState().removePlayer(data.player_id);
        }
      });

      es.addEventListener('host_changed', (event) => {
        const data = parseData<HostChangedDelta>(event);
        if (data) {
          useGameplayStore.getState().setHostPlayerId(data.new_host_player_id);
        }
      });

      es.addEventListener('game_dissolved', (event) => {
        const data = parseData<GameDissolvedDelta>(event);
        if (data) {
          Alert.alert('Game Over', 'The game has ended.');
          useAppStore.getState().clearSession();
          closedRef.current = true;
          es.close();
          if (router.canDismiss()) router.dismissAll();
          router.replace('/');
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
