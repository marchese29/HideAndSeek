import { useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Alert, BackHandler, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { DepartureWarningBanner } from '@/components/DepartureWarningBanner';
import { FoundClaimModal } from '@/components/FoundClaimModal';
import { FreezeWarningBanner } from '@/components/FreezeWarningBanner';
import { GameMap } from '@/components/GameMap';
import { LocationDeniedBanner } from '@/components/LocationDeniedBanner';
import { QuestionBanner } from '@/components/question-banner';
import { QuestionCutoffModal } from '@/components/QuestionCutoffModal';
import { UtilityBelt } from '@/components/utility-belt';
import { useCandidateStations } from '@/hooks/useCandidateStations';
import { useEndgameExclusions } from '@/hooks/useEndgameExclusions';
import { useGameInfo } from '@/hooks/useGameInfo';
import { useGameplayEvents } from '@/hooks/useGameplayEvents';
import { useLocationTracking } from '@/hooks/useLocationTracking';
import { useGameplayStore } from '@/stores/gameplayStore';
import type { GamePlayer, SeekerGameState } from '@/types/gameplay';

export default function GameplayScreen() {
  const { game_id } = useLocalSearchParams<{ game_id: string }>();
  const { connected } = useGameplayEvents(game_id);
  const { permissionDenied } = useLocationTracking(game_id);
  const { gameInfo } = useGameInfo(game_id);
  const status = useGameplayStore((s) => s.status);
  const role = useGameplayStore((s) => s.role);
  const state = useGameplayStore((s) => s.state);

  // Departure / freeze warnings: hider zone violations
  const notInZone = useGameplayStore((s) =>
    s.status === 'connected' && s.role === 'hider' ? s.state.not_in_zone : null,
  );
  const freezeDeparted = useGameplayStore((s) =>
    s.status === 'connected' && s.role === 'hider' ? s.state.freeze_departed : null,
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
    if (
      prev &&
      stationElectionStatus === 'auto_assigned' &&
      prev !== 'auto_assigned' &&
      hiderStationId
    ) {
      const stopName = gameInfo?.stops.find((s) => s.id === hiderStationId)?.name ?? 'Unknown stop';
      Alert.alert('Station Auto-Assigned', `Your hiding station was set to ${stopName}.`);
    }
  }, [stationElectionStatus, hiderStationId, gameInfo?.stops]);

  // ── Hider candidate stop selection ────────────────────────────────────────
  const [highlightedStopId, setHighlightedStopId] = useState<string | null>(null);

  // Guard: marker onPress and MapView onPress both fire on the same tap on Apple Maps.
  const markerPressedRef = useRef(false);

  const handleHighlightStop = useCallback((stopId: string | null) => {
    setHighlightedStopId(stopId);
  }, []);

  const handleCandidateStopPress = useCallback((stopId: string) => {
    markerPressedRef.current = true;
    setHighlightedStopId(stopId);
  }, []);

  // ── Endgame flow state ────────────────────────────────────────────────────
  const [endgameStationPicking, setEndgameStationPicking] = useState(false);
  const [endgameHighlightedStopId, setEndgameHighlightedStopId] = useState<string | null>(null);
  const [cutoffModalVisible, setCutoffModalVisible] = useState(false);
  const [pendingStationId, setPendingStationId] = useState<string | null>(null);
  const [pendingAfterQuestion, setPendingAfterQuestion] = useState<number | null>(null);

  const { stations: endgameCandidateStations } = useCandidateStations(endgameStationPicking);
  useEndgameExclusions(pendingStationId, pendingAfterQuestion);

  const handleEndgame = useCallback(() => {
    setEndgameStationPicking(true);
    setEndgameHighlightedStopId(null);
  }, []);

  const handleEndgameCandidatePress = useCallback((stopId: string) => {
    markerPressedRef.current = true;
    setEndgameHighlightedStopId(stopId);
  }, []);

  const handleEndgameStationSelect = useCallback(() => {
    setCutoffModalVisible(true);
  }, []);

  const handleEndgameCancel = useCallback(() => {
    setEndgameStationPicking(false);
    setEndgameHighlightedStopId(null);
  }, []);

  const handleCutoffSelect = useCallback(
    (afterQuestion: number) => {
      setPendingStationId(endgameHighlightedStopId);
      setPendingAfterQuestion(afterQuestion);
      setEndgameStationPicking(false);
      setEndgameHighlightedStopId(null);
    },
    [endgameHighlightedStopId],
  );

  const handleMapPress = useCallback(() => {
    if (markerPressedRef.current) {
      markerPressedRef.current = false;
      return;
    }
    // Clear hider candidate highlight
    setHighlightedStopId(null);
    // Clear endgame candidate highlight (stay in picking mode)
    setEndgameHighlightedStopId(null);
  }, []);

  // Clear candidate selection when phase transitions (e.g. hiding → seeking)
  const phase = state?.phase;
  useEffect(() => {
    setHighlightedStopId(null);
    setEndgameStationPicking(false);
    setEndgameHighlightedStopId(null);
  }, [phase]);

  // Clear endgame picking state when endgame view activates (hook set the store)
  const endgameView = useGameplayStore((s) => s.endgameView);
  useEffect(() => {
    if (endgameView) {
      setEndgameStationPicking(false);
      setEndgameHighlightedStopId(null);
    }
  }, [endgameView]);

  // Clear endgame pending params when endgame view is cleared (Long Game pressed)
  const prevEndgameView = useRef(endgameView);
  useEffect(() => {
    if (prevEndgameView.current && !endgameView) {
      setPendingStationId(null);
      setPendingAfterQuestion(null);
    }
    prevEndgameView.current = endgameView;
  }, [endgameView]);

  // Suppress Android hardware back button
  useEffect(() => {
    const sub = BackHandler.addEventListener('hardwareBackPress', () => true);
    return () => sub.remove();
  }, []);

  // Seeker question history for cutoff modal
  const seekerQuestionHistory =
    status === 'connected' && role === 'seeker' ? (state as SeekerGameState).question_history : [];

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
            endgameStationPicking={endgameStationPicking}
            endgameCandidateStations={endgameCandidateStations}
            endgameHighlightedStopId={endgameHighlightedStopId}
            onEndgameCandidatePress={handleEndgameCandidatePress}
          />
        )}
        {freezeDeparted && freezeDeparted.length > 0 ? (
          <FreezeWarningBanner freezeDeparted={freezeDeparted} hiders={hiders} />
        ) : (
          notInZone &&
          notInZone.length > 0 && <DepartureWarningBanner notInZone={notInZone} hiders={hiders} />
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
            endgameStationPicking={endgameStationPicking}
            endgameHighlightedStopId={endgameHighlightedStopId}
            endgameCandidateStations={endgameCandidateStations}
            onEndgame={handleEndgame}
            onEndgameStationSelect={handleEndgameStationSelect}
            onEndgameCancel={handleEndgameCancel}
          />
        </View>
      )}

      <QuestionCutoffModal
        visible={cutoffModalVisible}
        onClose={() => setCutoffModalVisible(false)}
        onSelect={handleCutoffSelect}
        questions={seekerQuestionHistory}
        convention={gameInfo?.distance_convention ?? 'imperial'}
      />

      <FoundClaimModal />
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
