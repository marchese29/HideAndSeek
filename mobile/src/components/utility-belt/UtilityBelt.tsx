import { memo, useMemo } from 'react';
import { StyleSheet, View } from 'react-native';

import { useQuestionSelection } from '@/hooks/useQuestionSelection';
import type { GameInfo, HiderGameState, SeekerGameState } from '@/types/gameplay';

import { BeltActions } from './BeltActions';
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
}

export const UtilityBelt = memo(function UtilityBelt({
  role,
  state,
  gameInfo,
  connected,
}: UtilityBeltProps) {
  const stationElectionStatus =
    role === 'hider' ? (state as HiderGameState).station_election_status : undefined;
  const disabled = !connected;

  const isSeekerSeeking = role === 'seeker' && state.phase === 'seeking';
  const seekerState = isSeekerSeeking ? (state as SeekerGameState) : null;

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
            disabled={disabled}
            onPress={isSeekerSeeking ? selection.toggle : undefined}
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

      {/* Center: Question selection (seeker seeking) or empty placeholder */}
      <View style={styles.center}>
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
