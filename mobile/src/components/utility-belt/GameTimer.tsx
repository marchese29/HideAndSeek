import { memo } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { useGameTimer } from '@/hooks/useGameTimer';

interface GameTimerProps {
  phase: string;
  hidingEndsAt: string | null;
  seekingStartedAt: string | null;
  seekingPauseAccumulatedSec: number;
  paused: boolean;
  pausedAt: string | null;
  connected: boolean;
}

function timerBackground(connected: boolean, phase: string, paused: boolean): string {
  if (!connected || paused) return '#7F8C8D';
  if (phase === 'hiding') return '#F39C12';
  if (phase === 'seeking') return '#2ECC71';
  return '#7F8C8D';
}

export const GameTimer = memo(function GameTimer({
  phase,
  hidingEndsAt,
  seekingStartedAt,
  seekingPauseAccumulatedSec,
  paused,
  pausedAt,
  connected,
}: GameTimerProps) {
  const timeDisplay = useGameTimer(
    phase,
    hidingEndsAt,
    seekingStartedAt,
    seekingPauseAccumulatedSec,
    paused,
    pausedAt,
  );
  const backgroundColor = timerBackground(connected, phase, paused);

  return (
    <View style={[styles.container, { backgroundColor }]}>
      <Text style={styles.time}>{timeDisplay}</Text>
    </View>
  );
});

const styles = StyleSheet.create({
  container: {
    borderRadius: 6,
    paddingVertical: 4,
    paddingHorizontal: 8,
    alignItems: 'center',
    justifyContent: 'center',
  },
  time: {
    color: '#fff',
    fontSize: 16,
    fontFamily: 'DSEG7',
  },
});
