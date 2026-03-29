import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';

import { api } from '@/api/client';
import { usePushToken } from '@/hooks/usePushToken';
import { useAppStore } from '@/store';

export default function HomeScreen() {
  const [checking, setChecking] = useState(true);
  usePushToken();

  useEffect(() => {
    const { gameId, playerId, playerSecret } = useAppStore.getState();
    if (!gameId || !playerId || !playerSecret) {
      setChecking(false);
      return;
    }

    // Validate stored credentials against the server
    void api
      .GET('/games/{game_id}/me', {
        params: {
          path: { game_id: gameId },
          header: { 'x-player-id': playerId, 'x-player-secret': playerSecret },
        },
      })
      .then(({ data, error }) => {
        if (error || !data) {
          useAppStore.getState().clearSession();
          setChecking(false);
          return;
        }
        if (data.game_status === 'lobby') {
          router.replace(`/lobby/${gameId}`);
        } else {
          // Game is no longer in lobby — clear session for now
          useAppStore.getState().clearSession();
          setChecking(false);
        }
      });
  }, []);

  if (checking) {
    return (
      <View style={styles.container}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Text style={styles.title}>HideAndSeek</Text>
      <View style={styles.buttons}>
        <Pressable style={styles.button} onPress={() => router.push('/create')}>
          <Text style={styles.buttonText}>Create Game</Text>
        </Pressable>
        <Pressable
          style={[styles.button, styles.secondaryButton]}
          onPress={() => router.push('/join')}
        >
          <Text style={[styles.buttonText, styles.secondaryButtonText]}>Join Game</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 24,
    backgroundColor: '#fff',
  },
  title: {
    fontSize: 32,
    fontWeight: 'bold',
    marginBottom: 48,
  },
  buttons: {
    width: '100%',
    gap: 16,
  },
  button: {
    backgroundColor: '#3498DB',
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
  },
  buttonText: {
    color: '#fff',
    fontSize: 18,
    fontWeight: '600',
  },
  secondaryButton: {
    backgroundColor: 'transparent',
    borderWidth: 2,
    borderColor: '#3498DB',
  },
  secondaryButtonText: {
    color: '#3498DB',
  },
});
