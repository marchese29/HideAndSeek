import { useLocalSearchParams } from 'expo-router';
import { useEffect } from 'react';
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
        <GameMap role={role} state={state} gameInfo={gameInfo} />
      )}

      {permissionDenied && <LocationDeniedBanner />}

      {/* Banner + belt wrapper: banner overlays above the belt */}
      {ready && (
        <View style={styles.beltWrapper}>
          <QuestionBanner role={role} gameId={game_id} connected={connected} />
          <UtilityBelt role={role} state={state} gameInfo={gameInfo} connected={connected} />
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
