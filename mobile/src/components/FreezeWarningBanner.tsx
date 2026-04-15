import React from 'react';
import { StyleSheet, Text, View } from 'react-native';

import type { GamePlayer } from '@/types/gameplay';

interface FreezeWarningBannerProps {
  freezeDeparted: string[];
  hiders: GamePlayer[];
}

export const FreezeWarningBanner = React.memo(function FreezeWarningBanner({
  freezeDeparted,
  hiders,
}: FreezeWarningBannerProps) {
  const names = freezeDeparted
    .map((id) => hiders.find((h) => h.id === id)?.name)
    .filter((name): name is string => name !== undefined);

  if (names.length === 0) return null;

  const message =
    names.length === 1
      ? `${names[0]} moved during freeze!`
      : `${names.join(', ')} moved during freeze!`;

  return (
    <View style={styles.container}>
      <Text style={styles.text}>{message}</Text>
    </View>
  );
});

const styles = StyleSheet.create({
  container: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    paddingHorizontal: 16,
    paddingVertical: 10,
    backgroundColor: '#E74C3C',
  },
  text: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '600',
    textAlign: 'center',
  },
});
