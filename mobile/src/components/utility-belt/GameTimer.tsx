import { memo } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { useGameTimer } from '@/hooks/useGameTimer';

interface GameTimerProps {
  phase: string;
  hidingStartedAt: string | null;
  hidingTimeMin: number;
  seekingStartedAt: string | null;
  connected: boolean;
}

function timerBackground(connected: boolean, phase: string): string {
  if (!connected) return '#7F8C8D';
  if (phase === 'hiding') return '#F39C12';
  if (phase === 'seeking') return '#2ECC71';
  return '#7F8C8D';
}

export const GameTimer = memo(function GameTimer({
  phase,
  hidingStartedAt,
  hidingTimeMin,
  seekingStartedAt,
  connected,
}: GameTimerProps) {
  const timeDisplay = useGameTimer(phase, hidingStartedAt, hidingTimeMin, seekingStartedAt);
  const backgroundColor = timerBackground(connected, phase);

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
