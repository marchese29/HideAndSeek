import { MaterialCommunityIcons } from '@expo/vector-icons';
import { memo } from 'react';
import { Alert, Pressable, StyleSheet, Text, View } from 'react-native';

interface EndgameBeltCenterProps {
  disabled?: boolean;
  onLongGame: () => void;
}

export const EndgameBeltCenter = memo(function EndgameBeltCenter({
  disabled,
  onLongGame,
}: EndgameBeltCenterProps) {
  return (
    <View style={styles.row}>
      <Pressable style={[styles.cell, styles.cellBorder]} onPress={onLongGame} disabled={disabled}>
        <MaterialCommunityIcons name="binoculars" size={28} color={disabled ? '#999' : '#000'} />
        <Text style={[styles.label, disabled && styles.labelDisabled]}>Long Game</Text>
      </Pressable>
      <Pressable
        style={styles.cell}
        onPress={() => Alert.alert('Found Them', 'Coming soon.')}
        disabled={disabled}
      >
        <MaterialCommunityIcons
          name="map-marker-account"
          size={28}
          color={disabled ? '#999' : '#000'}
        />
        <Text style={[styles.label, disabled && styles.labelDisabled]}>Found Them</Text>
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
    flex: 1,
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
