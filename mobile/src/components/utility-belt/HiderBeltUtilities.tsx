import { MaterialCommunityIcons } from '@expo/vector-icons';
import { memo } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

interface HiderBeltUtilitiesProps {
  disabled?: boolean;
  onHistory: () => void;
}

export const HiderBeltUtilities = memo(function HiderBeltUtilities({
  disabled,
  onHistory,
}: HiderBeltUtilitiesProps) {
  return (
    <View style={styles.row}>
      <Pressable style={styles.cell} onPress={onHistory} disabled={disabled}>
        <MaterialCommunityIcons name="history" size={28} color={disabled ? '#999' : '#000'} />
        <Text style={[styles.label, disabled && styles.labelDisabled]}>History</Text>
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
