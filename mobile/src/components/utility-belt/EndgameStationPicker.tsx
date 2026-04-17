import { MaterialCommunityIcons } from '@expo/vector-icons';
import { memo, useMemo } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import type { StopResponse } from '@/types/gameplay';

interface EndgameStationPickerProps {
  highlightedStopId: string | null;
  stops: StopResponse[];
  disabled?: boolean;
  onSelect: () => void;
  onCancel: () => void;
}

export const EndgameStationPicker = memo(function EndgameStationPicker({
  highlightedStopId,
  stops,
  disabled,
  onSelect,
  onCancel,
}: EndgameStationPickerProps) {
  const label = useMemo(() => {
    if (!highlightedStopId) return 'Tap a station';
    const stop = stops.find((s) => s.id === highlightedStopId);
    return stop?.name ?? 'Selected station';
  }, [highlightedStopId, stops]);

  const hasSelection = highlightedStopId !== null;

  return (
    <View style={styles.row}>
      <Pressable
        style={[styles.action, styles.actionBorder]}
        onPress={onSelect}
        disabled={disabled || !hasSelection}
      >
        <MaterialCommunityIcons
          name="check"
          size={24}
          color={!hasSelection || disabled ? '#999' : '#2ECC71'}
        />
      </Pressable>

      <View style={styles.center}>
        <Text style={[styles.label, hasSelection && styles.labelActive]} numberOfLines={1}>
          {label}
        </Text>
      </View>

      <Pressable
        style={[styles.action, styles.actionBorderLeft]}
        onPress={onCancel}
        disabled={disabled}
      >
        <MaterialCommunityIcons name="close" size={24} color={disabled ? '#999' : '#E74C3C'} />
      </Pressable>
    </View>
  );
});

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'stretch',
  },
  action: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  actionBorder: {
    borderRightWidth: StyleSheet.hairlineWidth,
    borderRightColor: 'rgba(0, 0, 0, 0.2)',
  },
  actionBorderLeft: {
    borderLeftWidth: StyleSheet.hairlineWidth,
    borderLeftColor: 'rgba(0, 0, 0, 0.2)',
  },
  center: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 8,
  },
  label: {
    color: '#95A5A6',
    fontSize: 13,
    fontWeight: '600',
    textAlign: 'center',
  },
  labelActive: {
    color: '#2C3E50',
    fontWeight: '700',
  },
});
