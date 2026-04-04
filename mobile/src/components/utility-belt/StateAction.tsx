import { MaterialCommunityIcons } from '@expo/vector-icons';
import { memo, useCallback } from 'react';
import { Alert, Pressable, StyleSheet, Text } from 'react-native';

interface StateActionProps {
  role: 'hider' | 'seeker';
  phase: string;
  stationElectionStatus?: string;
  disabled: boolean;
}

interface ActionConfig {
  icon: keyof typeof MaterialCommunityIcons.glyphMap;
  label: string;
  pressable: boolean;
}

function resolveAction(
  role: 'hider' | 'seeker',
  phase: string,
  stationElectionStatus?: string,
): ActionConfig {
  if (phase === 'hiding') {
    if (role === 'seeker') {
      return { icon: 'domino-mask', label: 'Hiding', pressable: false };
    }
    // Hider — check station election
    if (stationElectionStatus === 'elected') {
      return { icon: 'domino-mask', label: 'Hidden', pressable: false };
    }
    return { icon: 'bus-stop', label: 'Set Stop', pressable: true };
  }

  if (phase === 'seeking') {
    if (role === 'seeker') {
      return { icon: 'chat-question-outline', label: 'Ask', pressable: true };
    }
    return { icon: 'toolbox-outline', label: 'Toolbox', pressable: true };
  }

  // Fallback for unknown phases
  return { icon: 'help-circle-outline', label: phase, pressable: false };
}

export const StateAction = memo(function StateAction({
  role,
  phase,
  stationElectionStatus,
  disabled,
}: StateActionProps) {
  const { icon, label, pressable } = resolveAction(role, phase, stationElectionStatus);

  const onPress = useCallback(() => {
    Alert.alert(label, 'Coming soon');
  }, [label]);

  const isDisabled = disabled || !pressable;

  return (
    <Pressable
      style={({ pressed }) => [
        styles.container,
        pressable ? styles.actionable : styles.informational,
        isDisabled && styles.disabled,
        pressed && !isDisabled && styles.pressed,
      ]}
      onPress={onPress}
      disabled={isDisabled}
    >
      <MaterialCommunityIcons name={icon} size={20} color="#fff" />
      <Text style={styles.label}>{label}</Text>
    </Pressable>
  );
});

const styles = StyleSheet.create({
  container: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderRadius: 8,
    borderWidth: 1,
  },
  actionable: {
    backgroundColor: 'rgba(255, 255, 255, 0.12)',
    borderColor: 'rgba(255, 255, 255, 0.25)',
  },
  informational: {
    backgroundColor: 'rgba(255, 255, 255, 0.06)',
    borderColor: 'rgba(255, 255, 255, 0.12)',
  },
  pressed: {
    backgroundColor: 'rgba(255, 255, 255, 0.22)',
  },
  disabled: {
    opacity: 0.5,
  },
  label: {
    color: '#fff',
    fontSize: 10,
    fontWeight: '600',
    marginTop: 3,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
});
