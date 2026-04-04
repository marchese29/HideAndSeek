import { useLocalSearchParams } from 'expo-router';
import { useEffect } from 'react';
import { ActivityIndicator, BackHandler, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { GameMap } from '@/components/GameMap';
import { LocationDeniedBanner } from '@/components/LocationDeniedBanner';
import { UtilityBelt } from '@/components/utility-belt';
import { useGameplayEvents } from '@/hooks/useGameplayEvents';
import { useLocationTracking } from '@/hooks/useLocationTracking';
import { useGameplayStore } from '@/stores/gameplayStore';

export default function GameplayScreen() {
  const { game_id } = useLocalSearchParams<{ game_id: string }>();
  const { connected } = useGameplayEvents(game_id);
  const { permissionDenied } = useLocationTracking(game_id);
  const status = useGameplayStore((s) => s.status);
  const role = useGameplayStore((s) => s.role);
  const state = useGameplayStore((s) => s.state);

  // Suppress Android hardware back button
  useEffect(() => {
    const sub = BackHandler.addEventListener('hardwareBackPress', () => true);
    return () => sub.remove();
  }, []);

  return (
    <SafeAreaView style={styles.container} edges={['bottom']}>
      {status === 'connecting' || !role || !state ? (
        <View style={styles.loading}>
          <ActivityIndicator size="large" color="#7F8C8D" />
        </View>
      ) : (
        <GameMap role={role} state={state} />
      )}

      {permissionDenied && <LocationDeniedBanner />}

      {role && state && <UtilityBelt role={role} state={state} connected={connected} />}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#fff',
  },
  loading: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#ECF0F1',
  },
});
