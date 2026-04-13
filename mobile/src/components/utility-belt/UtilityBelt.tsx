import { memo, useCallback, useEffect, useMemo } from 'react';
import { Alert, StyleSheet, View } from 'react-native';

import { authHeader } from '@/api/auth';
import { api } from '@/api/client';
import { expandHidingZone } from '@/api/powers';
import { useQuestionSelection } from '@/hooks/useQuestionSelection';
import { useGameplayStore } from '@/stores/gameplayStore';
import type { GameInfo, HiderGameState, SeekerGameState } from '@/types/gameplay';

import { BeltActions } from './BeltActions';
import { CandidateStatus } from './CandidateStatus';
import { CustomDistanceInput } from './CustomDistanceInput';
import { GameTimer } from './GameTimer';
import { ParamPicker } from './ParamPicker';
import { QuestionTypeBar } from './QuestionTypeBar';
import { StateAction } from './StateAction';

interface UtilityBeltProps {
  role: 'hider' | 'seeker';
  state: HiderGameState | SeekerGameState;
  gameInfo: GameInfo;
  connected: boolean;
  gameId: string;
  highlightedStopId: string | null;
  onHighlightStop: (stopId: string | null) => void;
}

export const UtilityBelt = memo(function UtilityBelt({
  role,
  state,
  gameInfo,
  connected,
  gameId,
  highlightedStopId,
  onHighlightStop,
}: UtilityBeltProps) {
  const stationElectionStatus =
    role === 'hider' ? (state as HiderGameState).station_election_status : undefined;
  const candidateStations = role === 'hider' ? (state as HiderGameState).candidate_stations : null;
  const disabled = !connected;

  const isSeekerSeeking = role === 'seeker' && state.phase === 'seeking';
  const isHiderSeeking = role === 'hider' && state.phase === 'seeking';
  const seekerState = isSeekerSeeking ? (state as SeekerGameState) : null;
  const hiderState = isHiderSeeking ? (state as HiderGameState) : null;

  const hasActiveQuestion =
    seekerState?.active_question !== null && seekerState?.active_question !== undefined;

  const selection = useQuestionSelection(
    seekerState?.inventory ?? EMPTY_INVENTORY,
    hasActiveQuestion,
  );

  const selectedType =
    selection.state.step === 'param' || selection.state.step === 'custom'
      ? selection.state.questionType
      : null;

  const availableTypes = useMemo(
    () => new Set((seekerState?.inventory ?? []).map((s) => s.question_type)),
    [seekerState?.inventory],
  );

  // ── Stop selection logic ──────────────────────────────────────────────────
  const isHiderHiding =
    role === 'hider' &&
    state.phase === 'hiding' &&
    stationElectionStatus !== 'elected' &&
    stationElectionStatus !== 'auto_assigned';

  // Auto-highlight when there's exactly one candidate
  useEffect(() => {
    if (!isHiderHiding || !candidateStations) return;
    if (candidateStations.length === 1) {
      onHighlightStop(candidateStations[0]);
    }
  }, [isHiderHiding, candidateStations, onHighlightStop]);

  // Resolve highlighted stop name for the confirmation dialog
  const highlightedStopName = useMemo(() => {
    if (!highlightedStopId) return null;
    return gameInfo.stops.find((s) => s.id === highlightedStopId)?.name ?? 'Selected stop';
  }, [highlightedStopId, gameInfo.stops]);

  const handleSetStop = useCallback(() => {
    if (!highlightedStopId || !highlightedStopName) return;

    Alert.alert(
      'Set Stop',
      `Set ${highlightedStopName} as your hiding station? This can't be changed later.`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Confirm',
          onPress: () => {
            const selfLocation = useGameplayStore.getState().selfLocation;
            if (!selfLocation) {
              Alert.alert('Location unavailable', 'Waiting for a GPS fix. Try again in a moment.');
              return;
            }
            void (async () => {
              const { error } = await api.POST('/games/{game_id}/hider-station', {
                params: { path: { game_id: gameId }, header: authHeader() },
                body: { station_id: highlightedStopId, location: selfLocation.coordinates },
              });
              if (error) {
                const detail = (error as { detail?: string }).detail;
                Alert.alert(
                  'Election failed',
                  detail ?? 'Not all hiders are in range. Move closer and try again.',
                );
              }
            })();
          },
        },
      ],
    );
  }, [highlightedStopId, highlightedStopName, gameId]);

  const handlePowers = useCallback(() => {
    if (hiderState?.hiding_zone_expanded) {
      Alert.alert('Powers', 'You have already expanded the hiding zone.');
      return;
    }
    Alert.alert('Powers', 'Double the hiding zone radius?', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Expand',
        onPress: () => {
          void (async () => {
            const success = await expandHidingZone(gameId);
            if (!success) {
              Alert.alert('Expand Failed', 'Unable to expand the hiding zone.');
            }
          })();
        },
      },
    ]);
  }, [gameId, hiderState?.hiding_zone_expanded]);

  // "Set Stop" is pressable only when a candidate is highlighted
  const canSetStop = isHiderHiding && highlightedStopId !== null;

  return (
    <View style={styles.container}>
      {/* Left: State action + Timer */}
      <View style={styles.left}>
        <View style={styles.leftItem}>
          <StateAction
            role={role}
            phase={state.phase}
            stationElectionStatus={stationElectionStatus}
            hasActiveQuestion={isSeekerSeeking && hasActiveQuestion}
            disabled={disabled || (isHiderHiding && !canSetStop)}
            onPress={
              isSeekerSeeking
                ? selection.toggle
                : isHiderSeeking
                  ? handlePowers
                  : canSetStop
                    ? handleSetStop
                    : undefined
            }
            active={isSeekerSeeking && selection.isOpen}
          />
        </View>
        <GameTimer
          phase={state.phase}
          hidingStartedAt={state.hiding_started_at}
          hidingTimeMin={gameInfo.hiding_time_min}
          seekingStartedAt={state.seeking_started_at}
          connected={connected}
        />
      </View>

      {/* Center: Question selection (seeker seeking) or candidate status (hider hiding) */}
      <View style={styles.center}>
        {isHiderHiding && (
          <CandidateStatus
            candidateStationIds={candidateStations}
            stops={gameInfo.stops}
            highlightedStopId={highlightedStopId}
          />
        )}
        {isSeekerSeeking && selection.state.step === 'type' && (
          <QuestionTypeBar
            onSelectType={selection.selectType}
            selectedType={selectedType}
            disabled={disabled}
            availableTypes={availableTypes}
          />
        )}
        {isSeekerSeeking && selection.state.step === 'param' && (
          <ParamPicker
            slots={selection.slotsForType}
            convention={gameInfo.distance_convention}
            questionType={selection.state.questionType}
            selectedSlotIndex={selection.selectedSlotIndex}
            onSelectSlot={selection.selectSlot}
            onCustomPress={selection.openCustom}
            disabled={disabled}
          />
        )}
        {isSeekerSeeking && selection.state.step === 'custom' && (
          <CustomDistanceInput
            onSubmit={selection.submitCustom}
            onCancel={() =>
              selection.selectType(
                selection.state.step === 'custom' ? selection.state.questionType : '',
              )
            }
            convention={gameInfo.distance_convention}
          />
        )}
      </View>

      {/* Right: Info + Leave */}
      <BeltActions disabled={disabled} />
    </View>
  );
});

const EMPTY_INVENTORY: never[] = [];

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    backgroundColor: '#C5D4DE',
  },
  left: {
    width: 120,
    alignItems: 'stretch',
    justifyContent: 'center',
    gap: 4,
    backgroundColor: '#2C3E50',
    padding: 8,
    borderTopRightRadius: 10,
    borderBottomRightRadius: 10,
  },
  leftItem: {
    alignItems: 'stretch',
  },
  center: {
    flex: 1,
    justifyContent: 'center',
    paddingVertical: 4,
  },
});
