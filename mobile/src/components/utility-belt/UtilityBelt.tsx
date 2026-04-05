import { memo } from 'react';
import { StyleSheet, View } from 'react-native';

import type { HiderGameState, SeekerGameState } from '@/types/gameplay';

import { BeltActions } from './BeltActions';
import { GameTimer } from './GameTimer';
import { StateAction } from './StateAction';

interface UtilityBeltProps {
  role: 'hider' | 'seeker';
  state: HiderGameState | SeekerGameState;
  connected: boolean;
}

export const UtilityBelt = memo(function UtilityBelt({ role, state, connected }: UtilityBeltProps) {
  const stationElectionStatus =
    role === 'hider' ? (state as HiderGameState).station_election_status : undefined;
  const disabled = !connected;
  return (
    <View style={styles.container}>
      {/* Left: State action + Timer */}
      <View style={styles.left}>
        <View style={styles.leftItem}>
          <StateAction
            role={role}
            phase={state.phase}
            stationElectionStatus={stationElectionStatus}
            disabled={disabled}
          />
        </View>
        <GameTimer
          phase={state.phase}
          hidingStartedAt={state.hiding_started_at}
          hidingTimeMin={state.hiding_time_min}
          seekingStartedAt={state.seeking_started_at}
          connected={connected}
        />
      </View>

      {/* Center: Toolbelt placeholder */}
      <View style={styles.center} />

      {/* Right: Info + Leave */}
      <BeltActions disabled={disabled} />
    </View>
  );
});

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
    paddingVertical: 8,
  },
});
