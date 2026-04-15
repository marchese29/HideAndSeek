import { MaterialCommunityIcons } from '@expo/vector-icons';
import { memo } from 'react';
import { Alert, Pressable, StyleSheet, Text, View } from 'react-native';

interface BeltUtilitiesProps {
  disabled?: boolean;
}

const UTILITIES = [
  {
    icon: 'flag-checkered' as const,
    label: 'Endgame',
    onPress: () => Alert.alert('Endgame', 'Coming soon.'),
  },
];

export const BeltUtilities = memo(function BeltUtilities({ disabled }: BeltUtilitiesProps) {
  return (
    <View style={styles.row}>
      {UTILITIES.map((item, index) => (
        <Pressable
          key={item.label}
          style={[styles.cell, index < UTILITIES.length - 1 && styles.cellBorder]}
          onPress={item.onPress}
          disabled={disabled}
        >
          <MaterialCommunityIcons name={item.icon} size={28} color={disabled ? '#999' : '#000'} />
          <Text style={[styles.label, disabled && styles.labelDisabled]}>{item.label}</Text>
        </Pressable>
      ))}
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
  cellBorder: {
    borderRightWidth: StyleSheet.hairlineWidth,
    borderRightColor: 'rgba(0, 0, 0, 0.2)',
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
