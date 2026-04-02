import React from 'react';
import { StyleSheet, View } from 'react-native';
import { Marker } from 'react-native-maps';

import type { StopResponse } from '@/types/gameplay';
import { toLatLng } from '@/utils/geo';

interface StopMarkerProps {
  stop: StopResponse;
}

export const StopMarker = React.memo(function StopMarker({ stop }: StopMarkerProps) {
  return (
    <Marker
      coordinate={toLatLng(stop.coordinates)}
      tracksViewChanges={false}
      tappable={false}
      anchor={{ x: 0.5, y: 0.5 }}
    >
      <View style={styles.dot} />
    </Marker>
  );
});

const styles = StyleSheet.create({
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: '#7F8C8D',
  },
});
