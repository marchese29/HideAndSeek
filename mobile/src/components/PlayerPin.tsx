import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { Marker } from 'react-native-maps';

import { COLOR_HEX, type PlayerColor } from '@/constants/colors';
import type { GamePlayer } from '@/types/gameplay';
import { toLatLng } from '@/utils/geo';

const STALE_THRESHOLD_MS = 60_000;

interface PlayerPinProps {
  player: GamePlayer;
  isSelf: boolean;
  isHider: boolean;
  zIndex: number;
  stackCount: number;
}

export const PlayerPin = React.memo(function PlayerPin({
  player,
  isSelf,
  isHider,
  zIndex,
  stackCount,
}: PlayerPinProps) {
  const isStale = player.timestamp
    ? Date.now() - new Date(player.timestamp).getTime() > STALE_THRESHOLD_MS
    : false;

  const bgColor = COLOR_HEX[player.color as PlayerColor] ?? '#999';
  const initial = player.name.charAt(0).toUpperCase();

  return (
    <Marker
      coordinate={toLatLng(player.coordinates!)}
      anchor={{ x: 0.5, y: 0.5 }}
      tracksViewChanges={false}
      zIndex={zIndex}
    >
      <View style={{ opacity: isStale ? 0.4 : 1 }}>
        <View style={[styles.circle, { backgroundColor: bgColor }, isSelf && styles.selfRing]}>
          <Text style={styles.initial}>{initial}</Text>
        </View>
        {isHider && (
          <View style={styles.badge}>
            <Text style={styles.badgeText}>?</Text>
          </View>
        )}
        {stackCount > 0 && (
          <View style={styles.stackBadge}>
            <Text style={styles.stackBadgeText}>+{stackCount - 1}</Text>
          </View>
        )}
      </View>
    </Marker>
  );
});

const styles = StyleSheet.create({
  circle: {
    width: 22,
    height: 22,
    borderRadius: 11,
    justifyContent: 'center',
    alignItems: 'center',
  },
  selfRing: {
    borderWidth: 2,
    borderColor: '#fff',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.3,
    shadowRadius: 2,
    elevation: 4,
  },
  initial: {
    fontSize: 10,
    fontWeight: '700',
    color: '#fff',
  },
  badge: {
    position: 'absolute',
    top: -4,
    right: -4,
    width: 12,
    height: 12,
    borderRadius: 6,
    backgroundColor: '#2C3E50',
    justifyContent: 'center',
    alignItems: 'center',
  },
  badgeText: {
    fontSize: 8,
    fontWeight: '700',
    color: '#fff',
  },
  stackBadge: {
    position: 'absolute',
    bottom: -4,
    right: -6,
    minWidth: 14,
    height: 14,
    borderRadius: 7,
    backgroundColor: '#7F8C8D',
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 2,
  },
  stackBadgeText: {
    fontSize: 8,
    fontWeight: '700',
    color: '#fff',
  },
});
