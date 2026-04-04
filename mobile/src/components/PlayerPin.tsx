import React, { useEffect, useRef, useState } from 'react';
import { Animated, StyleSheet, Text, View } from 'react-native';
import { AnimatedRegion, Marker } from 'react-native-maps';

import { COLOR_HEX, type PlayerColor } from '@/constants/colors';
import type { GamePlayer } from '@/types/gameplay';
import { toLatLng } from '@/utils/geo';

const ANIMATE_DURATION_MS = 500;

interface PlayerPinProps {
  player: GamePlayer;
  isSelf: boolean;
  isHider: boolean;
  isStale: boolean;
  zIndex: number;
  stackCount: number;
}

export const PlayerPin = React.memo(function PlayerPin({
  player,
  isSelf,
  isHider,
  isStale,
  zIndex,
  stackCount,
}: PlayerPinProps) {
  const { latitude, longitude } = toLatLng(player.coordinates!);

  const animatedCoord = useRef(
    new AnimatedRegion({ latitude, longitude, latitudeDelta: 0, longitudeDelta: 0 }),
  ).current;

  useEffect(() => {
    animatedCoord
      .timing({
        latitude,
        longitude,
        latitudeDelta: 0,
        longitudeDelta: 0,
        duration: ANIMATE_DURATION_MS,
        useNativeDriver: false,
        toValue: 0,
      })
      .start();
  }, [latitude, longitude, animatedCoord]);

  // Animate the color transition when staleness changes. Pulse
  // tracksViewChanges for the duration so the native map re-snapshots
  // each frame of the color interpolation.
  const staleAnim = useRef(new Animated.Value(isStale ? 1 : 0)).current;
  const [trackChanges, setTrackChanges] = useState(false);
  const prevStaleRef = useRef(isStale);
  useEffect(() => {
    if (prevStaleRef.current !== isStale) {
      prevStaleRef.current = isStale;
      setTrackChanges(true);
      Animated.timing(staleAnim, {
        toValue: isStale ? 1 : 0,
        duration: ANIMATE_DURATION_MS,
        useNativeDriver: false,
      }).start(() => setTrackChanges(false));
    }
  }, [isStale, staleAnim]);

  const playerColor = COLOR_HEX[player.color as PlayerColor] ?? '#999';
  const bgColor = staleAnim.interpolate({
    inputRange: [0, 1],
    outputRange: [playerColor, '#95A5A6'],
  });
  const initial = player.name.charAt(0).toUpperCase();

  return (
    <Marker.Animated
      // AnimatedRegion is structurally compatible at runtime but the TS types
      // for Marker.Animated expect WithAnimatedObject<LatLng>, not AnimatedMapRegion.
      coordinate={animatedCoord as unknown as { latitude: number; longitude: number }}
      anchor={{ x: 0.5, y: 0.5 }}
      tracksViewChanges={trackChanges}
      zIndex={zIndex}
    >
      <View style={{ opacity: isHider ? 0.4 : 1 }}>
        <Animated.View
          style={[styles.circle, { backgroundColor: bgColor }, isSelf && styles.selfRing]}
        >
          <Text style={[styles.initial, isHider && styles.initialHider]}>{initial}</Text>
        </Animated.View>
        {stackCount > 0 && (
          <View style={styles.stackBadge}>
            <Text style={styles.stackBadgeText}>+{stackCount - 1}</Text>
          </View>
        )}
      </View>
    </Marker.Animated>
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
  initialHider: {
    fontStyle: 'italic',
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
