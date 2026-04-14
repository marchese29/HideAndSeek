import { useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Alert, BackHandler, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { DepartureWarningBanner } from '@/components/DepartureWarningBanner';
import { GameMap } from '@/components/GameMap';
import { LocationDeniedBanner } from '@/components/LocationDeniedBanner';
import { QuestionBanner } from '@/components/question-banner';
import { UtilityBelt } from '@/components/utility-belt';
import { useGameInfo } from '@/hooks/useGameInfo';
import { useGameplayEvents } from '@/hooks/useGameplayEvents';
import { useLocationTracking } from '@/hooks/useLocationTracking';
import { useGameplayStore } from '@/stores/gameplayStore';
import type { GamePlayer } from '@/types/gameplay';

export default function GameplayScreen() {
  const { game_id } = useLocalSearchParams<{ game_id: string }>();
  const { connected } = useGameplayEvents(game_id);
  const { permissionDenied } = useLocationTracking(game_id);
  const { gameInfo } = useGameInfo(game_id);
  const status = useGameplayStore((s) => s.status);
  const role = useGameplayStore((s) => s.role);
  const state = useGameplayStore((s) => s.state);

  // Departure warning: hider zone violations
  const notInZone = useGameplayStore((s) =>
    s.status === 'connected' && s.role === 'hider' ? s.state.not_in_zone : null,
  );
  const hiders = useGameplayStore((s) =>
    s.status === 'connected' && s.role === 'hider' ? s.state.hiders : EMPTY_HIDERS,
  );

  // Auto-assigned station toast
  const stationElectionStatus = useGameplayStore((s) =>
    s.status === 'connected' && s.role === 'hider' ? s.state.station_election_status : null,
  );
  const hiderStationId = useGameplayStore((s) =>
    s.status === 'connected' && s.role === 'hider' ? s.state.hider_station_id : null,
  );
  const prevStationStatusRef = useRef<string | null>(stationElectionStatus);
  useEffect(() => {
    const prev = prevStationStatusRef.current;
    prevStationStatusRef.current = stationElectionStatus;
    if (prev && stationElectionStatus === 'auto_assigned' && prev !== 'auto_assigned' && hiderStationId) {
      const stopName =
        gameInfo?.stops.find((s) => s.id === hiderStationId)?.name ?? 'Unknown stop';
      Alert.alert('Station Auto-Assigned', `Your hiding station was set to ${stopName}.`);
    }
  }, [stationElectionStatus, hiderStationId, gameInfo?.stops]);

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
      <View style={styles.mapArea}>
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
        {notInZone && notInZone.length > 0 && (
          <DepartureWarningBanner notInZone={notInZone} hiders={hiders} />
        )}
      </View>

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

const EMPTY_HIDERS: GamePlayer[] = [];

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#1C1C1E',
  },
  mapArea: {
    flex: 1,
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
