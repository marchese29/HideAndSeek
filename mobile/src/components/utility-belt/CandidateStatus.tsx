import { memo, useMemo } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import type { StopResponse } from '@/types/gameplay';

interface CandidateStatusProps {
  candidateStationIds: string[] | null;
  stops: StopResponse[];
  highlightedStopId: string | null;
}

export const CandidateStatus = memo(function CandidateStatus({
  candidateStationIds,
  stops,
  highlightedStopId,
}: CandidateStatusProps) {
  const label = useMemo(() => {
    // Show highlighted stop name when one is selected
    if (highlightedStopId) {
      const stop = stops.find((s) => s.id === highlightedStopId);
      return stop?.name ?? 'Selected stop';
    }
    if (!candidateStationIds || candidateStationIds.length === 0) {
      return 'No stops in range';
    }
    if (candidateStationIds.length === 1) {
      const stop = stops.find((s) => s.id === candidateStationIds[0]);
      return stop?.name ?? '1 stop in range';
    }
    return 'Tap a stop to select';
  }, [candidateStationIds, stops, highlightedStopId]);

  const hasCandidates = candidateStationIds && candidateStationIds.length > 0;
  const hasSelection = highlightedStopId !== null;

  return (
    <View style={styles.container}>
      <Text
        style={[
          styles.text,
          !hasCandidates && styles.textDimmed,
          hasSelection && styles.textActive,
        ]}
        numberOfLines={1}
      >
        {label}
      </Text>
    </View>
  );
});

const styles = StyleSheet.create({
  container: {
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 8,
  },
  text: {
    color: '#2C3E50',
    fontSize: 13,
    fontWeight: '600',
    textAlign: 'center',
  },
  textDimmed: {
    color: '#95A5A6',
  },
  textActive: {
    color: '#2C3E50',
    fontWeight: '700',
  },
});
