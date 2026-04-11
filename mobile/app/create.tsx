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
type MapSize = 'small' | 'medium' | 'large';

const HIDING_TIME_DEFAULTS: Record<MapSize, number> = { small: 30, medium: 60, large: 180 };
const DEFAULT_QUESTION_DELAY = 5;
const SELECTABLE_SIZES: MapSize[] = ['small', 'medium', 'large'];

function resolveHidingTime(mapOverride: number | null | undefined, size: MapSize): number {
  return mapOverride ?? HIDING_TIME_DEFAULTS[size];
}

function resolveQuestionDelay(mapOverride: number | null | undefined): number {
  return mapOverride ?? DEFAULT_QUESTION_DELAY;
}

export default function CreateGameScreen() {
  const [selectedMapId, setSelectedMapId] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const [selectedSize, setSelectedSize] = useState<MapSize | null>(null);
  const [hidingTime, setHidingTime] = useState('');
  const [questionDelay, setQuestionDelay] = useState('');

  const { data: maps, isLoading: mapsLoading } = useQuery<MapSummary[]>({
    queryKey: ['maps'],
    queryFn: async () => {
      const { data, error } = await api.GET('/maps');
      if (error) throw error;
      return data;
    },
    staleTime: 0,
  });

  const selectedMap = maps?.find((m) => m.id === selectedMapId);
  const isSpecialMap = selectedMap?.size === 'special';
  const canSubmit = selectedMapId !== null && name.trim().length > 0 && !loading;

  function handleMapSelect(map: MapSummary) {
    setSelectedMapId(map.id);
    if (map.size === 'special') {
      // Special maps: no size picker, use map overrides directly
      setSelectedSize(null);
      setHidingTime(String(map.default_hiding_time_min ?? ''));
      setQuestionDelay(String(resolveQuestionDelay(map.default_base_question_delay_min)));
    } else {
      const size = map.size as MapSize;
      setSelectedSize(size);
      setHidingTime(String(resolveHidingTime(map.default_hiding_time_min, size)));
      setQuestionDelay(String(resolveQuestionDelay(map.default_base_question_delay_min)));
    }
  }

  function handleSizeChange(size: MapSize) {
    setSelectedSize(size);
    setHidingTime(String(resolveHidingTime(selectedMap?.default_hiding_time_min ?? null, size)));
  }

  async function handleCreate() {
    if (!selectedMapId) return;
    setError(null);
    setLoading(true);

    await requestLocationPermission();

    const { pushToken, pushProvider } = useAppStore.getState();
    const parsedHidingTime = parseInt(hidingTime, 10);
    const parsedQuestionDelay = parseInt(questionDelay, 10);

    const { data, error: apiError } = await api.POST('/games', {
      body: {
        map_id: selectedMapId,
        name: name.trim(),
        size: selectedSize ?? undefined,
        hiding_time_min: Number.isFinite(parsedHidingTime) ? parsedHidingTime : undefined,
        base_question_delay_min: Number.isFinite(parsedQuestionDelay)
          ? parsedQuestionDelay
          : undefined,
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
        onPress={() => handleMapSelect(item)}
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

      {selectedMap && !isSpecialMap && (
        <>
          <Text style={styles.label}>Game Size</Text>
          <View style={styles.sizeRow}>
            {SELECTABLE_SIZES.map((size) => (
              <Pressable
                key={size}
                style={[styles.sizeButton, selectedSize === size && styles.sizeButtonSelected]}
                onPress={() => handleSizeChange(size)}
              >
                <Text
                  style={[
                    styles.sizeButtonText,
                    selectedSize === size && styles.sizeButtonTextSelected,
                  ]}
                >
                  {size.charAt(0).toUpperCase() + size.slice(1)}
                </Text>
              </Pressable>
            ))}
          </View>
        </>
      )}

      {selectedMap && (
        <>
          <View style={styles.timingRow}>
            <View style={styles.timingField}>
              <Text style={styles.label}>Hiding Time</Text>
              <View style={styles.inputWithUnit}>
                <TextInput
                  style={styles.timingInput}
                  value={hidingTime}
                  onChangeText={setHidingTime}
                  keyboardType="number-pad"
                  maxLength={4}
                />
                <Text style={styles.unitText}>min</Text>
              </View>
            </View>
            <View style={styles.timingField}>
              <Text style={styles.label}>Answer Time</Text>
              <View style={styles.inputWithUnit}>
                <TextInput
                  style={styles.timingInput}
                  value={questionDelay}
                  onChangeText={setQuestionDelay}
                  keyboardType="number-pad"
                  maxLength={4}
                />
                <Text style={styles.unitText}>min</Text>
              </View>
            </View>
          </View>
        </>
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
  sizeRow: {
    flexDirection: 'row',
    gap: 8,
  },
  sizeButton: {
    flex: 1,
    paddingVertical: 12,
    borderWidth: 2,
    borderColor: '#ddd',
    borderRadius: 12,
    alignItems: 'center',
  },
  sizeButtonSelected: {
    borderColor: '#3498DB',
    backgroundColor: '#EBF5FB',
  },
  sizeButtonText: {
    fontSize: 15,
    fontWeight: '600',
    color: '#888',
  },
  sizeButtonTextSelected: {
    color: '#2C3E50',
  },
  timingRow: {
    flexDirection: 'row',
    gap: 16,
  },
  timingField: {
    flex: 1,
  },
  inputWithUnit: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: 2,
    borderColor: '#ddd',
    borderRadius: 12,
    paddingHorizontal: 12,
  },
  timingInput: {
    flex: 1,
    fontSize: 18,
    paddingVertical: 12,
  },
  unitText: {
    fontSize: 14,
    color: '#888',
    fontWeight: '600',
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
