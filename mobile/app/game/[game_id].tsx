import { useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, BackHandler, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { GameMap } from '@/components/GameMap';
import { LocationDeniedBanner } from '@/components/LocationDeniedBanner';
import { QuestionBanner } from '@/components/question-banner';
import { UtilityBelt } from '@/components/utility-belt';
import { useGameInfo } from '@/hooks/useGameInfo';
import { useGameplayEvents } from '@/hooks/useGameplayEvents';
import { useLocationTracking } from '@/hooks/useLocationTracking';
import { useGameplayStore } from '@/stores/gameplayStore';

export default function GameplayScreen() {
  const { game_id } = useLocalSearchParams<{ game_id: string }>();
  const { connected } = useGameplayEvents(game_id);
  const { permissionDenied } = useLocationTracking(game_id);
  const { gameInfo } = useGameInfo(game_id);
  const status = useGameplayStore((s) => s.status);
  const role = useGameplayStore((s) => s.role);
  const state = useGameplayStore((s) => s.state);

  // Highlighted candidate stop — bridges UtilityBelt and GameMap
  const [highlightedStopId, setHighlightedStopId] = useState<string | null>(null);

  // Guard: marker onPress and MapView onPress both fire on the same tap on Apple Maps.
  // The ref prevents the map press from immediately clearing what the marker press just set.
  const markerPressedRef = useRef(false);

  const handleHighlightStop = useCallback((stopId: string | null) => {
    setHighlightedStopId(stopId);
  }, []);

  const handleCandidateStopPress = useCallback((stopId: string) => {
    markerPressedRef.current = true;
    setHighlightedStopId(stopId);
  }, []);

  const handleMapPress = useCallback(() => {
    if (markerPressedRef.current) {
      markerPressedRef.current = false;
      return;
    }
    setHighlightedStopId(null);
  }, []);

  // Clear candidate selection when phase transitions (e.g. hiding → seeking)
  const phase = state?.phase;
  useEffect(() => {
    setHighlightedStopId(null);
  }, [phase]);

  // Suppress Android hardware back button
  useEffect(() => {
    const sub = BackHandler.addEventListener('hardwareBackPress', () => true);
    return () => sub.remove();
  }, []);

  const ready = status === 'connected' && role && state && gameInfo;

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      {!ready ? (
        <View style={styles.loading}>
          <ActivityIndicator size="large" color="#7F8C8D" />
        </View>
      ) : (
        <GameMap
          role={role}
          state={state}
          gameInfo={gameInfo}
          highlightedStopId={highlightedStopId}
          onCandidateStopPress={handleCandidateStopPress}
          onMapPress={handleMapPress}
        />
      )}

      {permissionDenied && <LocationDeniedBanner />}

      {/* Banner + belt wrapper: banner overlays above the belt */}
      {ready && (
        <View style={styles.beltWrapper}>
          <QuestionBanner role={role} gameId={game_id} connected={connected} />
          <UtilityBelt
            role={role}
            state={state}
            gameInfo={gameInfo}
            connected={connected}
            gameId={game_id}
            highlightedStopId={highlightedStopId}
            onHighlightStop={handleHighlightStop}
          />
        </View>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#2C3E50',
  },
  loading: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#ECF0F1',
  },
  beltWrapper: {
    backgroundColor: '#C5D4DE',
  },
});
