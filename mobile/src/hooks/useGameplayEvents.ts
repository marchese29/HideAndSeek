import { router } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { Alert, AppState } from 'react-native';
import EventSource, { type EventSourceEvent } from 'react-native-sse';

import { API_BASE_URL } from '@/api/client';
import { queryClient } from '@/api/queryClient';
import { useAppStore } from '@/store';
import { useGameplayStore } from '@/stores/gameplayStore';
import { useToastStore } from '@/stores/toastStore';
import type {
  FoundClaimDelta,
  GameDissolvedDelta,
  GameEndedDelta,
  GameInfo,
  HiderGameState,
  HiderQuestionAnsweredDelta,
  HidingZoneExpandedDelta,
  HostChangedDelta,
  PhaseChangedDelta,
  PhotoRejectedDelta,
  PhotoSubmittedDelta,
  PlayerLeftDelta,
  PlayerLocationDelta,
  ProximityDeescalatedDelta,
  ProximityEscalatedDelta,
  QuestionAbandonedDelta,
  QuestionAnswerableDelta,
  QuestionAskedDelta,
  QuestionVetoedDelta,
  SeekerGameState,
  SeekerQuestionAnsweredDelta,
  StationElectionDelta,
} from '@/types/gameplay';
import { createSequenceTracker } from '@/utils/sseSequencing';

function resolvePlayerName(playerId: string): string | undefined {
  const gameplay = useGameplayStore.getState();
  if (gameplay.status !== 'connected') return undefined;
  const fromHiders = gameplay.state.hiders.find((p) => p.id === playerId);
  if (fromHiders) return fromHiders.name;
  return gameplay.state.seekers.find((p) => p.id === playerId)?.name;
}

function formatRadius(radius: number, convention: string | undefined): string {
  const rounded = Math.round(radius * 10) / 10;
  const unit = convention === 'metric' ? 'km' : convention === 'imperial' ? 'mi' : '';
  return unit ? `${rounded} ${unit}` : `${rounded}`;
}

type GameplayEventType =
  | 'game_state'
  | 'phase_changed'
  | 'player_location'
  | 'station_election'
  | 'question_asked'
  | 'question_answerable'
  | 'question_answered'
  | 'question_vetoed'
  | 'question_abandoned'
  | 'player_left'
  | 'host_changed'
  | 'game_dissolved'
  | 'game_ended'
  | 'hiding_zone_expanded'
  | 'proximity_escalated'
  | 'proximity_deescalated'
  | 'found_claim'
  | 'found_claim_rejected'
  | 'found_claim_expired'
  | 'photo_submitted'
  | 'photo_rejected';

type SSEEvent = EventSourceEvent<GameplayEventType, GameplayEventType>;

function parseData<T>(event: SSEEvent): T | null {
  if (!event.data) return null;
  return JSON.parse(event.data) as T;
}

type ProximityTier = ProximityEscalatedDelta['proximity_tier'];

function proximityEscalationMessage(tier: ProximityTier): string | null {
  switch (tier) {
    case 'approaching':
      return 'A seeker is heading your way.';
    case 'near':
      return 'A seeker is getting close!';
    case 'entered':
      return 'A seeker entered your hiding zone — freeze!';
    default:
      return null;
  }
}

function proximityDeescalationMessage(tier: ProximityTier): string | null {
  switch (tier) {
    case 'near':
      return 'Seekers moved back but are still close.';
    case 'approaching':
      return 'Seekers are pulling away.';
    case 'none':
      return 'All seekers are far away.';
    default:
      return null;
  }
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

      const seq = createSequenceTracker({
        onGap: ({ expected, got }) => {
          console.warn('[gameplay SSE] gap detected', { expected, got });
          useGameplayStore.getState().reset();
          scheduleReconnect();
        },
        onInvalid: ({ lastEventId }) => {
          console.warn('[gameplay SSE] missing/invalid lastEventId', { lastEventId });
          useGameplayStore.getState().reset();
          scheduleReconnect();
        },
        onStale: ({ last, got }) => {
          console.warn('[gameplay SSE] stale event dropped', { last, got });
        },
      });

      es.addEventListener('open', () => {
        setConnected(true);
        seq.reset();
        retriesRef.current = 0;
      });

      es.addEventListener('error', () => {
        setConnected(false);
        seq.reset();
        useGameplayStore.getState().reset();
        if (closedRef.current) return;
        scheduleReconnect();
      });

      es.addEventListener(
        'game_state',
        seq.wrap((event) => {
          const data = parseData<HiderGameState | SeekerGameState>(event);
          if (data) {
            useGameplayStore.getState().hydrate(role!, data);
          }
        }),
      );

      es.addEventListener(
        'phase_changed',
        seq.wrap((event) => {
          const data = parseData<PhaseChangedDelta>(event);
          if (data) {
            useGameplayStore.getState().applyPhaseChanged(data);
          }
        }),
      );

      es.addEventListener(
        'player_location',
        seq.wrap((event) => {
          const data = parseData<PlayerLocationDelta>(event);
          if (data) {
            const store = useGameplayStore.getState();
            store.updatePlayerLocation(data.player_id, data.coordinates, data.timestamp);
            if (data.candidate_stations !== undefined) {
              store.updateCandidateStations(data.candidate_stations);
            }
            if (data.not_in_zone !== undefined) {
              store.updateNotInZone(data.not_in_zone);
            }
            if (data.computed_answer !== undefined) {
              store.updateComputedAnswer(data.computed_answer);
            }
            if (data.freeze_departed !== undefined) {
              store.updateFreezeDeparted(data.freeze_departed);
            }
          }
        }),
      );

      es.addEventListener(
        'proximity_escalated',
        seq.wrap((event) => {
          const data = parseData<ProximityEscalatedDelta>(event);
          if (data) {
            useGameplayStore.getState().updateProximityTier(data.proximity_tier);
            const message = proximityEscalationMessage(data.proximity_tier);
            if (message) useToastStore.getState().push({ message, severity: 'warning' });
          }
        }),
      );

      es.addEventListener(
        'proximity_deescalated',
        seq.wrap((event) => {
          const data = parseData<ProximityDeescalatedDelta>(event);
          if (data) {
            useGameplayStore.getState().updateProximityTier(data.proximity_tier);
            const message = proximityDeescalationMessage(data.proximity_tier);
            if (message) useToastStore.getState().push({ message, severity: 'info' });
          }
        }),
      );

      es.addEventListener(
        'station_election',
        seq.wrap((event) => {
          const data = parseData<StationElectionDelta>(event);
          if (data) {
            useGameplayStore.getState().applyStationElection(data);
          }
        }),
      );

      es.addEventListener(
        'question_asked',
        seq.wrap((event) => {
          const data = parseData<QuestionAskedDelta>(event);
          if (data) {
            useGameplayStore.getState().setActiveQuestion(data);
          }
        }),
      );

      es.addEventListener(
        'question_answerable',
        seq.wrap((event) => {
          const data = parseData<QuestionAnswerableDelta>(event);
          if (data) {
            useGameplayStore.getState().updateQuestionAnswerable(data);
          }
        }),
      );

      es.addEventListener(
        'question_answered',
        seq.wrap((event) => {
          if (role === 'hider') {
            const data = parseData<HiderQuestionAnsweredDelta>(event);
            if (data) {
              useGameplayStore.getState().applyQuestionAnswered(data);
            }
          } else {
            const data = parseData<SeekerQuestionAnsweredDelta>(event);
            if (data) {
              useGameplayStore.getState().applyQuestionAnswered(data);
              // Re-fetch endgame exclusions if endgame view is active
              if (useGameplayStore.getState().endgameView) {
                void queryClient.invalidateQueries({ queryKey: ['endgame-exclusions'] });
              }
            }
          }
        }),
      );

      es.addEventListener(
        'photo_submitted',
        seq.wrap((event) => {
          const data = parseData<PhotoSubmittedDelta>(event);
          if (data) useGameplayStore.getState().applyPhotoSubmitted(data);
        }),
      );

      es.addEventListener(
        'photo_rejected',
        seq.wrap((event) => {
          const data = parseData<PhotoRejectedDelta>(event);
          if (data) useGameplayStore.getState().applyPhotoRejected(data);
        }),
      );

      es.addEventListener(
        'question_vetoed',
        seq.wrap((event) => {
          const data = parseData<QuestionVetoedDelta>(event);
          if (data) {
            useGameplayStore.getState().clearActiveQuestion();
          }
        }),
      );

      es.addEventListener(
        'question_abandoned',
        seq.wrap((event) => {
          const data = parseData<QuestionAbandonedDelta>(event);
          if (data) {
            useGameplayStore.getState().clearActiveQuestion();
          }
        }),
      );

      es.addEventListener(
        'player_left',
        seq.wrap((event) => {
          const data = parseData<PlayerLeftDelta>(event);
          if (!data) return;
          if (data.player_id === playerId) {
            // Kicked by host — blocking Alert gates navigation away from the game.
            Alert.alert('Removed', 'You were removed from the game.');
            useAppStore.getState().clearSession();
            closedRef.current = true;
            es.close();
            if (router.canDismiss()) router.dismissAll();
            router.replace('/');
          } else {
            // Resolve name BEFORE removePlayer() strips the player from the roster.
            const name = resolvePlayerName(data.player_id);
            useGameplayStore.getState().removePlayer(data.player_id);
            if (name) {
              useToastStore
                .getState()
                .push({ message: `${name} has left the game`, severity: 'info' });
            }
          }
        }),
      );

      es.addEventListener(
        'host_changed',
        seq.wrap((event) => {
          const data = parseData<HostChangedDelta>(event);
          if (!data) return;
          if (data.new_host_player_id === playerId) {
            useToastStore.getState().push({ message: 'You are the new host', severity: 'info' });
          } else {
            const name = resolvePlayerName(data.new_host_player_id);
            if (name) {
              useToastStore
                .getState()
                .push({ message: `${name} has been made the new host`, severity: 'info' });
            }
          }
          useGameplayStore.getState().setHostPlayerId(data.new_host_player_id);
        }),
      );

      es.addEventListener(
        'game_dissolved',
        seq.wrap((event) => {
          const data = parseData<GameDissolvedDelta>(event);
          if (data) {
            closedRef.current = true;
            es.close();
            if (router.canDismiss()) router.dismissAll();
            router.replace({
              pathname: '/recap',
              params: { reason: data.reason, role: role ?? 'hider' },
            });
          }
        }),
      );

      es.addEventListener(
        'game_ended',
        seq.wrap((event) => {
          const data = parseData<GameEndedDelta>(event);
          if (data) {
            closedRef.current = true;
            es.close();
            if (router.canDismiss()) router.dismissAll();
            router.replace({
              pathname: '/recap',
              params: { reason: data.reason, role: role ?? 'hider' },
            });
          }
        }),
      );

      es.addEventListener(
        'hiding_zone_expanded',
        seq.wrap((event) => {
          const data = parseData<HidingZoneExpandedDelta>(event);
          if (!data) return;
          useGameplayStore.getState().applyHidingZoneExpanded();
          void queryClient.invalidateQueries({ queryKey: ['hiding-zone'] });
          const gameInfo = queryClient.getQueryData<GameInfo>(['game-info', gameId]);
          const radius = formatRadius(data.effective_radius, gameInfo?.distance_convention);
          useToastStore.getState().push({
            message: `The hiding zone has been expanded to ${radius}`,
            severity: 'info',
          });
        }),
      );

      es.addEventListener(
        'found_claim',
        seq.wrap((event) => {
          const data = parseData<FoundClaimDelta>(event);
          if (data) {
            useGameplayStore
              .getState()
              .setFoundClaimPending(data.seeker_player_id, data.deadline_utc);
          }
        }),
      );

      es.addEventListener(
        'found_claim_rejected',
        seq.wrap(() => {
          if (role === 'seeker') {
            useGameplayStore.getState().clearFoundClaim();
            useToastStore.getState().push({
              message: 'The hiders rejected your found claim',
              severity: 'warning',
            });
          }
        }),
      );

      es.addEventListener(
        'found_claim_expired',
        seq.wrap(() => {
          useGameplayStore.getState().clearFoundClaim();
          useToastStore.getState().push({
            message: 'The found claim timed out',
            severity: 'warning',
          });
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
      useToastStore.getState().clear();
    };
  }, [gameId, playerId, playerSecret, role]);

  return { connected };
}
