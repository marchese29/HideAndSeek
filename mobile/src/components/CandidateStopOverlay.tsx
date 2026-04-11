import React, { useMemo } from 'react';
import { StyleSheet, View } from 'react-native';
import { Marker } from 'react-native-maps';

import type { StopResponse } from '@/types/gameplay';
import { toLatLng } from '@/utils/geo';

interface CandidateStopOverlayProps {
  candidateStationIds: string[];
  stops: StopResponse[];
  highlightedStopId: string | null;
  onStopPress: (stopId: string) => void;
}

export const CandidateStopOverlay = React.memo(function CandidateStopOverlay({
  candidateStationIds,
  stops,
  highlightedStopId,
  onStopPress,
}: CandidateStopOverlayProps) {
  const candidateStops = useMemo(() => {
    const idSet = new Set(candidateStationIds);
    return stops.filter((s) => idSet.has(s.id));
  }, [candidateStationIds, stops]);

  if (candidateStops.length === 0) return null;

  return (
    <>
      {candidateStops.map((stop) => {
        const highlighted = stop.id === highlightedStopId;
        return (
          <Marker
            key={`candidate-${stop.id}`}
            coordinate={toLatLng(stop.coordinates)}
            tracksViewChanges={false}
            tappable
            onPress={() => onStopPress(stop.id)}
            anchor={{ x: 0.5, y: 0.5 }}
            zIndex={500}
          >
            <View style={[styles.dot, highlighted && styles.highlighted]} />
          </Marker>
        );
      })}
    </>
  );
});

const styles = StyleSheet.create({
  dot: {
    width: 12,
    height: 12,
    borderRadius: 6,
    backgroundColor: '#3498DB',
    borderWidth: 2,
    borderColor: '#FFFFFF',
  },
  highlighted: {
    width: 16,
    height: 16,
    borderRadius: 8,
    backgroundColor: '#2ECC71',
    borderWidth: 2.5,
    borderColor: '#FFFFFF',
  },
});
