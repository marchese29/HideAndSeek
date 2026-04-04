import { router } from 'expo-router';
import { useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View } from 'react-native';

import { api } from '@/api/client';
import { queryClient } from '@/api/queryClient';
import { useAppStore } from '@/store';
import { requestLocationPermission } from '@/utils/locationPermission';

export default function JoinGameScreen() {
  const [joinCode, setJoinCode] = useState('');
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const canSubmit = joinCode.length === 4 && name.trim().length > 0 && !loading;

  async function handleJoin() {
    setError(null);
    setLoading(true);

    await requestLocationPermission();

    const { pushToken, pushProvider } = useAppStore.getState();
    const { data, error: apiError } = await api.POST('/games/join', {
      body: {
        join_code: joinCode,
        name: name.trim(),
        device_token: pushToken ?? undefined,
        device_token_provider: pushProvider ?? 'apns',
      },
    });

    setLoading(false);

    if (apiError) {
      const detail = (apiError as { detail?: string }).detail;
      setError(detail ?? 'Failed to join game.');
      return;
    }

    useAppStore.getState().setSession(data.game.id, data.player_id, data.player_secret);
    queryClient.setQueryData(['game', data.game.id], data.game);
    router.replace(`/lobby/${data.game.id}`);
  }

  return (
    <View style={styles.container}>
      <Text style={styles.label}>Join Code</Text>
      <TextInput
        style={styles.codeInput}
        value={joinCode}
        onChangeText={(text) => setJoinCode(text.toUpperCase().slice(0, 4))}
        placeholder="ABCD"
        placeholderTextColor="#aaa"
        autoCapitalize="characters"
        maxLength={4}
        autoFocus
      />

      <Text style={styles.label}>Your Name</Text>
      <TextInput
        style={styles.nameInput}
        value={name}
        onChangeText={setName}
        placeholder="Enter your name"
        placeholderTextColor="#aaa"
        maxLength={30}
      />

      {error && <Text style={styles.error}>{error}</Text>}

      <Pressable
        style={[styles.button, !canSubmit && styles.buttonDisabled]}
        onPress={() => void handleJoin()}
        disabled={!canSubmit}
      >
        {loading ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <Text style={styles.buttonText}>Join Game</Text>
        )}
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    padding: 24,
    backgroundColor: '#fff',
  },
  label: {
    fontSize: 14,
    fontWeight: '600',
    color: '#666',
    marginBottom: 8,
    marginTop: 16,
  },
  codeInput: {
    fontSize: 32,
    fontFamily: 'Courier',
    fontWeight: 'bold',
    letterSpacing: 8,
    textAlign: 'center',
    borderWidth: 2,
    borderColor: '#ddd',
    borderRadius: 12,
    padding: 16,
  },
  nameInput: {
    fontSize: 18,
    borderWidth: 2,
    borderColor: '#ddd',
    borderRadius: 12,
    padding: 16,
  },
  error: {
    color: '#E74C3C',
    marginTop: 16,
    textAlign: 'center',
  },
  button: {
    backgroundColor: '#3498DB',
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
    marginTop: 24,
  },
  buttonDisabled: {
    opacity: 0.5,
  },
  buttonText: {
    color: '#fff',
    fontSize: 18,
    fontWeight: '600',
  },
});
