import { MaterialCommunityIcons } from '@expo/vector-icons';
import { memo, useCallback } from 'react';
import { Alert, Pressable, StyleSheet, View } from 'react-native';

interface BeltActionsProps {
  disabled: boolean;
}

export const BeltActions = memo(function BeltActions({ disabled }: BeltActionsProps) {
  const onInfoPress = useCallback(() => {
    Alert.alert('Info', 'Coming soon');
  }, []);

  const onLeavePress = useCallback(() => {
    Alert.alert('Leave Game', 'Are you sure you want to leave?', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Leave', style: 'destructive', onPress: () => {} },
    ]);
  }, []);

  return (
    <View style={styles.container}>
      <Pressable
        style={({ pressed }) => [
          styles.button,
          styles.infoButton,
          disabled && styles.disabled,
          pressed && !disabled && styles.pressed,
        ]}
        onPress={onInfoPress}
        disabled={disabled}
      >
        <MaterialCommunityIcons name="information-outline" size={20} color="#fff" />
      </Pressable>
      <Pressable
        style={({ pressed }) => [
          styles.button,
          styles.leaveButton,
          disabled && styles.disabled,
          pressed && !disabled && styles.leavePressed,
        ]}
        onPress={onLeavePress}
        disabled={disabled}
      >
        <MaterialCommunityIcons name="exit-run" size={20} color="#E74C3C" />
      </Pressable>
    </View>
  );
});

const styles = StyleSheet.create({
  container: {
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    backgroundColor: '#2C3E50',
    padding: 8,
    borderTopLeftRadius: 10,
    borderBottomLeftRadius: 10,
  },
  button: {
    padding: 8,
    borderRadius: 8,
    borderWidth: 1,
  },
  infoButton: {
    backgroundColor: 'rgba(255, 255, 255, 0.06)',
    borderColor: 'rgba(255, 255, 255, 0.12)',
  },
  leaveButton: {
    backgroundColor: 'rgba(231, 76, 60, 0.12)',
    borderColor: 'rgba(231, 76, 60, 0.3)',
  },
  pressed: {
    backgroundColor: 'rgba(255, 255, 255, 0.22)',
  },
  leavePressed: {
    backgroundColor: 'rgba(231, 76, 60, 0.25)',
  },
  disabled: {
    opacity: 0.5,
  },
});
