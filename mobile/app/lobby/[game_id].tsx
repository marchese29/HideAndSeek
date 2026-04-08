import { useQuery } from '@tanstack/react-query';
import * as Clipboard from 'expo-clipboard';
import { router, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useRef } from 'react';
import { Alert, Platform, Pressable, StyleSheet, Text, View } from 'react-native';

import { authHeader } from '@/api/auth';
import { api } from '@/api/client';
import type { components } from '@/api/schema';
import { ConnectionDot } from '@/components/ConnectionDot';
import { PlayerList } from '@/components/PlayerList';
import { useLobbyEvents } from '@/hooks/useLobbyEvents';
import { useAppStore } from '@/store';

type GameResponse = components['schemas']['GameResponse'];

export default function LobbyScreen() {
  const { game_id } = useLocalSearchParams<{ game_id: string }>();
  const playerId = useAppStore((s) => s.playerId);

  const { connected } = useLobbyEvents(game_id);

  // PATCH the player if the push token rotates while in the lobby
  const pushToken = useAppStore((s) => s.pushToken);
  const initialToken = useRef(pushToken);
  useEffect(() => {
    if (!playerId || !pushToken || pushToken === initialToken.current) return;
    initialToken.current = pushToken;
    void api.PATCH('/games/{game_id}/players/{player_id}', {
      params: {
        path: { game_id, player_id: playerId },
        header: authHeader(),
      },
      body: {
        device_token: pushToken,
        device_token_provider: Platform.OS === 'ios' ? 'apns' : 'fcm',
      },
    });
  }, [pushToken, playerId, game_id]);

  const { data: game } = useQuery<GameResponse>({
    queryKey: ['game', game_id],
    queryFn: async () => {
      const { data, error } = await api.GET('/games/{game_id}', {
        params: { path: { game_id } },
      });
      if (error) throw error;
      return data;
    },
  });

  const isHost = game?.host_player_id === playerId;

  const handleCopyCode = useCallback(async () => {
    if (game?.join_code) {
      await Clipboard.setStringAsync(game.join_code);
      Alert.alert('Copied!', 'Join code copied to clipboard.');
    }
  }, [game?.join_code]);

  const handleLeave = useCallback(() => {
    if (!game || !playerId) return;

    const isHostLeaving = game.host_player_id === playerId;
    const otherPlayers = game.players.filter((p) => p.id !== playerId);

    if (isHostLeaving && otherPlayers.length > 0) {
      // Host must pick a new host before leaving
      Alert.alert('Transfer Host', 'Choose a new host before leaving.', [
        { text: 'Cancel', style: 'cancel' },
        ...otherPlayers.map((p) => ({
          text: p.name,
          onPress: () => {
            Alert.alert('Leave Game', 'Are you sure you want to leave?', [
              { text: 'Cancel', style: 'cancel' },
              { text: 'Leave', style: 'destructive', onPress: () => void doLeave(p.id) },
            ]);
          },
        })),
      ]);
    } else {
      void doLeave();
    }

    async function doLeave(newHostId?: string) {
      await api.DELETE('/games/{game_id}/players/{player_id}', {
        params: {
          path: { game_id, player_id: playerId! },
          header: authHeader(),
        },
        body: newHostId ? { new_host_id: newHostId } : null,
      });
      useAppStore.getState().clearSession();
      router.replace('/');
    }
  }, [game, game_id, playerId]);

  const handleStart = useCallback(async () => {
    const { error } = await api.POST('/games/{game_id}/start', {
      params: { path: { game_id }, header: authHeader() },
    });
    if (error) {
      const detail = (error as { detail?: string }).detail;
      Alert.alert('Cannot Start', detail ?? 'Failed to start game.');
    }
  }, [game_id]);

  if (!game) {
    return (
      <View style={styles.container}>
        <Text style={styles.loading}>Loading...</Text>
      </View>
    );
  }

  // Start button validation
  const allHaveRoles = game.players.every((p) => p.role !== null);
  const hasHider = game.players.some((p) => p.role === 'hider');
  const hasSeeker = game.players.some((p) => p.role === 'seeker');
  const canStart = allHaveRoles && hasHider && hasSeeker;

  let startHelper = '';
  if (!allHaveRoles) startHelper = 'All players must pick a role';
  else if (!hasHider) startHelper = 'Need at least one hider';
  else if (!hasSeeker) startHelper = 'Need at least one seeker';

  return (
    <View style={styles.container}>
      {game.join_code && (
        <Pressable
          style={styles.codeBanner}
          onPress={() => void handleCopyCode()}
          disabled={!connected}
        >
          <ConnectionDot connected={connected} />
          <Text style={styles.codeText}>{game.join_code}</Text>
          <Text style={styles.codeSubtext}>Tap to copy join code</Text>
        </Pressable>
      )}

      <View style={[styles.listContainer, !connected && styles.disabled]}>
        <PlayerList game={game} playerId={playerId!} disabled={!connected} />
      </View>

      <View style={styles.footer}>
        {isHost && (
          <View style={styles.startSection}>
            <Pressable
              style={[styles.startButton, (!canStart || !connected) && styles.buttonDisabled]}
              onPress={() => void handleStart()}
              disabled={!canStart || !connected}
            >
              <Text style={styles.startButtonText}>Start Game</Text>
            </Pressable>
            {startHelper !== '' && <Text style={styles.helperText}>{startHelper}</Text>}
          </View>
        )}

        <Pressable
          style={[styles.leaveButton, !connected && styles.buttonDisabled]}
          onPress={handleLeave}
          disabled={!connected}
        >
          <Text style={styles.leaveButtonText}>Leave Game</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#fff',
  },
  loading: {
    textAlign: 'center',
    marginTop: 48,
    color: '#888',
  },
  codeBanner: {
    alignItems: 'center',
    padding: 20,
    backgroundColor: '#EBF5FB',
    borderBottomWidth: 1,
    borderBottomColor: '#D4E6F1',
  },
  codeText: {
    fontSize: 36,
    fontWeight: 'bold',
    fontFamily: 'Courier',
    letterSpacing: 8,
    color: '#2C3E50',
  },
  codeSubtext: {
    fontSize: 13,
    color: '#7F8C8D',
    marginTop: 4,
  },
  listContainer: {
    flex: 1,
  },
  disabled: {
    opacity: 0.5,
  },
  footer: {
    padding: 16,
    gap: 12,
    borderTopWidth: 1,
    borderTopColor: '#eee',
  },
  startSection: {
    gap: 4,
  },
  startButton: {
    backgroundColor: '#2ECC71',
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
  },
  buttonDisabled: {
    opacity: 0.5,
  },
  startButtonText: {
    color: '#fff',
    fontSize: 18,
    fontWeight: '600',
  },
  helperText: {
    textAlign: 'center',
    fontSize: 13,
    color: '#888',
  },
  leaveButton: {
    paddingVertical: 14,
    borderRadius: 12,
    borderWidth: 2,
    borderColor: '#E74C3C',
    alignItems: 'center',
  },
  leaveButtonText: {
    color: '#E74C3C',
    fontSize: 16,
    fontWeight: '600',
  },
});
