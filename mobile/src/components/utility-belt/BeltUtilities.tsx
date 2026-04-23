import { MaterialCommunityIcons } from '@expo/vector-icons';
import { memo } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

interface BeltUtilitiesProps {
  disabled?: boolean;
  onEndgame: () => void;
  onHistory: () => void;
}

export const BeltUtilities = memo(function BeltUtilities({
  disabled,
  onEndgame,
  onHistory,
}: BeltUtilitiesProps) {
  return (
    <View style={styles.row}>
      <Pressable style={styles.cell} onPress={onHistory} disabled={disabled}>
        <MaterialCommunityIcons name="history" size={28} color={disabled ? '#999' : '#000'} />
        <Text style={[styles.label, disabled && styles.labelDisabled]}>History</Text>
      </Pressable>
      <Pressable style={styles.cell} onPress={onEndgame} disabled={disabled}>
        <MaterialCommunityIcons
          name="flag-checkered"
          size={28}
          color={disabled ? '#999' : '#000'}
        />
        <Text style={[styles.label, disabled && styles.labelDisabled]}>Endgame</Text>
      </Pressable>
    </View>
  );
});

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'stretch',
  },
  cell: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 8,
    paddingHorizontal: 16,
  },
  label: {
    fontSize: 11,
    fontWeight: '600',
    color: '#000',
    marginTop: 2,
  },
  labelDisabled: {
    color: '#999',
  },
});
