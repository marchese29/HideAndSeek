import { MaterialCommunityIcons } from '@expo/vector-icons';
import { router } from 'expo-router';
import { memo, useCallback } from 'react';
import { Alert, Pressable, StyleSheet, View } from 'react-native';

import { authHeader } from '@/api/auth';
import { api } from '@/api/client';
import { useAppStore } from '@/store';
import { useGameplayStore } from '@/stores/gameplayStore';

interface BeltActionsProps {
  disabled: boolean;
}

export const BeltActions = memo(function BeltActions({ disabled }: BeltActionsProps) {
  const gameId = useAppStore((s) => s.gameId);
  const playerId = useAppStore((s) => s.playerId);
  const status = useGameplayStore((s) => s.status);
  const role = useGameplayStore((s) => s.role);
  const state = useGameplayStore((s) => s.state);

  const onInfoPress = useCallback(() => {
    Alert.alert('Info', 'Coming soon');
  }, []);

  const onLeavePress = useCallback(() => {
    if (status !== 'connected' || !state || !playerId || !gameId) return;

    const isHost = state.host_player_id === playerId;
    const myRole = role;

    // Check if leaving would empty the team
    const isLastOfRole =
      myRole === 'hider'
        ? state.hiders.filter((h) => h.id !== playerId).length === 0
        : state.seekers.filter((s) => s.id !== playerId).length === 0;

    // All other players across both teams
    const otherPlayers = [
      ...state.hiders.filter((p) => p.id !== playerId),
      ...state.seekers.filter((p) => p.id !== playerId),
    ];

    async function doLeave(newHostId?: string) {
      try {
        await api.DELETE('/games/{game_id}/players/{player_id}', {
          params: {
            path: { game_id: gameId!, player_id: playerId! },
            header: authHeader(),
          },
          body: newHostId ? { new_host_id: newHostId } : null,
        });
      } catch {
        // Game may already be dissolved — still clear session
      }
      useAppStore.getState().clearSession();
      router.dismissAll();
      router.replace('/');
    }

    if (isLastOfRole) {
      const roleLabel = myRole === 'hider' ? 'hider' : 'seeker';
      Alert.alert(
        'End Game',
        `You are the last ${roleLabel}. Leaving will end the game for everyone.`,
        [
          { text: 'Cancel', style: 'cancel' },
          { text: 'Leave', style: 'destructive', onPress: () => void doLeave() },
        ],
      );
    } else if (isHost && otherPlayers.length > 0) {
      Alert.alert('Transfer Host', 'Choose a new host before leaving.', [
        { text: 'Cancel', style: 'cancel' },
        ...otherPlayers.map((p) => ({
          text: p.name,
          onPress: () => {
            Alert.alert('Leave Game', 'Your data will be deleted and you cannot rejoin.', [
              { text: 'Cancel', style: 'cancel' },
              { text: 'Leave', style: 'destructive', onPress: () => void doLeave(p.id) },
            ]);
          },
        })),
      ]);
    } else {
      Alert.alert('Leave Game', 'Your data will be deleted and you cannot rejoin.', [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Leave', style: 'destructive', onPress: () => void doLeave() },
      ]);
    }
  }, [gameId, playerId, status, role, state]);

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
