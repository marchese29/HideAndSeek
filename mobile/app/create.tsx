import { useQuery } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import { api } from '@/api/client';
import { queryClient } from '@/api/queryClient';
import type { components } from '@/api/schema';
import { useAppStore } from '@/store';
import { requestLocationPermission } from '@/utils/locationPermission';

type MapSummary = components['schemas']['MapSummary'];

export default function CreateGameScreen() {
  const [selectedMapId, setSelectedMapId] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const { data: maps, isLoading: mapsLoading } = useQuery<MapSummary[]>({
    queryKey: ['maps'],
    queryFn: async () => {
      const { data, error } = await api.GET('/maps');
      if (error) throw error;
      return data;
    },
  });

  const canSubmit = selectedMapId !== null && name.trim().length > 0 && !loading;

  async function handleCreate() {
    if (!selectedMapId) return;
    setError(null);
    setLoading(true);

    await requestLocationPermission();

    const { pushToken, pushProvider } = useAppStore.getState();
    const { data, error: apiError } = await api.POST('/games', {
      body: {
        map_id: selectedMapId,
        name: name.trim(),
        device_token: pushToken ?? undefined,
        device_token_provider: pushProvider ?? 'apns',
      },
    });

    setLoading(false);

    if (apiError) {
      const detail = (apiError as { detail?: string }).detail;
      setError(detail ?? 'Failed to create game.');
      return;
    }

    useAppStore.getState().setSession(data.game.id, data.player_id, data.player_secret);
    queryClient.setQueryData(['game', data.game.id], data.game);
    router.replace(`/lobby/${data.game.id}`);
  }

  function renderMapItem({ item }: { item: MapSummary }) {
    const selected = item.id === selectedMapId;
    return (
      <Pressable
        style={[styles.mapItem, selected && styles.mapItemSelected]}
        onPress={() => setSelectedMapId(item.id)}
      >
        <View style={styles.mapInfo}>
          <Text style={[styles.mapName, selected && styles.mapNameSelected]}>{item.name}</Text>
          <Text style={styles.mapRegion}>{item.region}</Text>
        </View>
        <Text style={styles.mapSize}>{item.size}</Text>
      </Pressable>
    );
  }

  return (
    <View style={styles.container}>
      <Text style={styles.label}>Your Name</Text>
      <TextInput
        style={styles.nameInput}
        value={name}
        onChangeText={setName}
        placeholder="Enter your name"
        placeholderTextColor="#aaa"
        maxLength={30}
      />

      <Text style={styles.label}>Select Map</Text>
      {mapsLoading ? (
        <ActivityIndicator style={styles.loader} />
      ) : (
        <FlatList
          data={maps}
          keyExtractor={(item) => item.id}
          renderItem={renderMapItem}
          contentContainerStyle={styles.mapList}
          style={styles.mapListContainer}
        />
      )}

      {error && <Text style={styles.error}>{error}</Text>}

      <Pressable
        style={[styles.button, !canSubmit && styles.buttonDisabled]}
        onPress={() => void handleCreate()}
        disabled={!canSubmit}
      >
        {loading ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <Text style={styles.buttonText}>Create Game</Text>
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
  nameInput: {
    fontSize: 18,
    borderWidth: 2,
    borderColor: '#ddd',
    borderRadius: 12,
    padding: 16,
  },
  loader: {
    marginTop: 24,
  },
  mapListContainer: {
    flex: 1,
  },
  mapList: {
    gap: 8,
  },
  mapItem: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: 16,
    borderWidth: 2,
    borderColor: '#eee',
    borderRadius: 12,
  },
  mapItemSelected: {
    borderColor: '#3498DB',
    backgroundColor: '#EBF5FB',
  },
  mapInfo: {
    flex: 1,
  },
  mapName: {
    fontSize: 16,
    fontWeight: '600',
  },
  mapNameSelected: {
    color: '#2C3E50',
  },
  mapRegion: {
    fontSize: 13,
    color: '#888',
    marginTop: 2,
  },
  mapSize: {
    fontSize: 13,
    fontWeight: '600',
    color: '#888',
    textTransform: 'uppercase',
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
    marginTop: 16,
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
